use std::{
    io,
    sync::{Arc, OnceLock},
    time::Duration,
};

use decky_plugin::Plugin;
use sdh_ludusavi_backend::service::BackendService;
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
    let mut plugin = Plugin::new().on_migration(move |context| async move {
        let env = context.env().clone();
        let backend = tokio::task::spawn_blocking(move || BackendService::new(&env))
            .await
            .map_err(|error| format!("service initialization task failed: {error}"))?
            .map_err(|error| error.to_string())?;
        initialize
            .set(Arc::new(backend))
            .map_err(|_| "backend initialized more than once".to_owned())
    });

    for name in [
        "get_settings",
        "update_settings",
        "get_ludusavi_launcher_shortcut_id",
        "set_ludusavi_launcher_shortcut_id",
        "log",
        "get_recent_logs",
        "get_operation_status",
        "get_game_history",
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
