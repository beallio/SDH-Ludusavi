use std::{
    io,
    sync::{Arc, OnceLock},
    time::Duration,
};

use decky_plugin::Plugin;
use sdh_ludusavi_backend::{service::BackendService, status_theme};
use serde_json::Value;

fn register_rpc(
    plugin: Plugin,
    service: Arc<OnceLock<Arc<BackendService>>>,
    name: &'static str,
) -> Plugin {
    plugin.method(name, move |_context, args| {
        let service = Arc::clone(&service);
        async move {
            let reply = match service.get() {
                Some(service) => service.dispatch(name, args).await,
                None => BackendService::unavailable_reply(name),
            };
            Ok::<Value, String>(reply)
        }
    })
}

async fn run() -> io::Result<()> {
    let service: Arc<OnceLock<Arc<BackendService>>> = Arc::new(OnceLock::new());
    let initialize = Arc::clone(&service);
    let startup_service = Arc::clone(&service);
    let mut plugin = Plugin::new()
        .on_migration(move |context| async move {
            let env = context.env().clone();
            let backend = tokio::task::spawn_blocking(move || BackendService::new(&env))
                .await
                .map_err(|error| format!("service initialization task failed: {error}"))?
                .map_err(|error| error.to_string())?;
            initialize
                .set(Arc::new(backend))
                .map_err(|_| "backend initialized more than once".to_owned())
        })
        .on_main(move |context| async move {
            match tokio::task::spawn_blocking(
                sdh_ludusavi_backend::singleton::enforce_single_instance,
            )
            .await
            {
                Ok(Ok(report)) => log::info!(
                    "Single-instance check completed: status={}, terminated={}, killed={}, skipped={}, failed={}",
                    report.status,
                    report.terminated.len(),
                    report.killed.len(),
                    report.skipped.len(),
                    report.failed.len()
                ),
                Ok(Err(error)) => log::warn!("Single-instance check failed; continuing startup: {error}"),
                Err(error) => log::warn!("Single-instance check task failed; continuing startup: {error}"),
            }
            if let Some(service) = startup_service.get() {
                let service = Arc::clone(service);
                let env = context.env().clone();
                if let Err(error) = tokio::task::spawn_blocking(move || service.startup(&env)).await {
                    log::error!("Backend startup task failed: {error}");
                }
            }
            Ok(())
        })
        .on_uninstall(|context| async move {
            let env = context.env().clone();
            match tokio::task::spawn_blocking(move || {
                status_theme::uninstall_status_theme(&env.decky_home, &env.plugin_runtime_dir)
            })
            .await
            {
                Ok(Ok(())) => (),
                Ok(Err(error)) => {
                    log::warn!("CSS Loader theme was retained during uninstall: {error}")
                }
                Err(error) => log::warn!("CSS Loader theme uninstall task failed: {error}"),
            }
            Ok(())
        });

    for name in [
        "get_update_check_context",
        "check_for_plugin_update",
        "revalidate_plugin_update",
        "record_update_install_requested",
        "confirm_update_install_handoff",
        "mark_update_notified",
        "clear_pending_update_install",
        "consume_theme_refresh_needed",
        "get_settings",
        "update_settings",
        "get_ludusavi_launcher_shortcut_id",
        "set_ludusavi_launcher_shortcut_id",
        "log",
        "get_recent_logs",
        "get_operation_status",
        "get_game_history",
        "check_game_start",
        "restore_game_on_start",
        "resolve_game_start_conflict",
        "check_game_exit",
        "backup_game_on_exit",
        "pause_game_process",
        "renew_game_process_pause",
        "resume_game_process",
        "refresh_games",
        "is_game_cache_current",
        "force_backup",
        "force_restore",
        "list_backups",
        "restore_backup_version",
        "get_versions",
        "get_ludusavi_logs",
        "get_ludusavi_command",
    ] {
        plugin = register_rpc(plugin, Arc::clone(&service), name);
    }

    let unloading = Arc::clone(&service);
    plugin = plugin.on_unload(move |_| async move {
        if let Some(service) = unloading.get()
            && !service.shutdown().await
        {
            log::warn!("Timed out draining in-flight backend calls during unload");
        }
        Ok(())
    });
    plugin.run().await
}

fn main() -> io::Result<()> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    let result = runtime.block_on(run());
    // Leave 750 ms for runtime teardown after the four-second service drain.
    runtime.shutdown_timeout(Duration::from_millis(750));
    result
}
