use std::{
    collections::{BTreeSet, VecDeque},
    io,
    path::{Path, PathBuf},
    sync::{
        Arc, LazyLock, Mutex,
        atomic::{AtomicBool, AtomicI64, Ordering},
    },
    time::{Duration, Instant},
};

use decky_plugin::Env;
use serde_json::{Map, Value, json};
use time::{OffsetDateTime, format_description, format_description::well_known::Rfc3339};
use tokio::sync::Notify;

use crate::{
    lifecycle::{TimestampDirection, timestamp_direction},
    operations::{LudusaviOperations, OperationError},
    persistence::{
        StateLock, ensure_private_directory, existing_mode, read_object, write_json_atomic,
    },
    watchdog::ProcessWatchdog,
};

const LOG_LIMIT: usize = 100;
const DRAIN_BUDGET: Duration = Duration::from_secs(4);
const DEFAULT_NOTIFICATIONS: [&str; 7] = [
    "enabled",
    "auto_sync_progress",
    "auto_sync_results",
    "manual_operations",
    "refresh_status",
    "failures_errors",
    "update_available",
];

pub struct BackendService {
    settings_path: PathBuf,
    cache_path: PathBuf,
    state_lock: Arc<StateLock>,
    settings: Mutex<Map<String, Value>>,
    shortcut_id: AtomicI64,
    operations: LudusaviOperations,
    watchdog: ProcessWatchdog,
    debug_logging: AtomicBool,
    logs: Mutex<VecDeque<Value>>,
    calls: Arc<CallTracker>,
}

impl BackendService {
    pub fn new(env: &Env) -> io::Result<Self> {
        let settings_dir = required_path(&env.plugin_settings_dir, "DECKY_PLUGIN_SETTINGS_DIR")?;
        let runtime_dir = required_path(&env.plugin_runtime_dir, "DECKY_PLUGIN_RUNTIME_DIR")?;
        ensure_private_directory(&settings_dir)?;
        ensure_private_directory(&runtime_dir)?;

        let settings_path = settings_dir.join("settings.json");
        let cache_path = runtime_dir.join("cache.json");
        let state_lock = Arc::new(StateLock::new(&cache_path)?);
        let loaded = state_lock.with_lock(|| {
            let settings = read_object(&settings_path)
                .unwrap_or_else(|error| {
                    log::warn!(
                        "Could not read settings at {}: {error}",
                        settings_path.display()
                    );
                    None
                })
                .unwrap_or_default();
            let cache = read_object(&cache_path)
                .unwrap_or_else(|error| {
                    log::warn!("Could not read cache at {}: {error}", cache_path.display());
                    None
                })
                .unwrap_or_default();
            Ok((settings, cache))
        });
        let (settings, cache) = match loaded {
            Ok(state) => state,
            Err(error) => {
                log::warn!("Failed to acquire state lock during startup: {error}");
                (Map::new(), Map::new())
            }
        };
        let debug_logging = setting_bool(&settings, "debug_logging", true);
        let history = normalize_history(cache.get("game_history"));
        let operations =
            LudusaviOperations::new(cache_path.clone(), Arc::clone(&state_lock), &cache, history);
        let shortcut_id = cache
            .get("ludusaviLauncherShortcutAppId")
            .and_then(python_integer)
            .unwrap_or(-1);

        log::set_max_level(if debug_logging {
            log::LevelFilter::Debug
        } else {
            log::LevelFilter::Info
        });

        let service = Self {
            settings_path,
            cache_path,
            state_lock,
            settings: Mutex::new(settings),
            shortcut_id: AtomicI64::new(shortcut_id),
            operations,
            watchdog: ProcessWatchdog::default(),
            debug_logging: AtomicBool::new(debug_logging),
            logs: Mutex::new(VecDeque::with_capacity(LOG_LIMIT)),
            calls: Arc::new(CallTracker::default()),
        };
        service.log(
            "info",
            "SDH-ludusavi service initialized",
            Some("init"),
            None,
        );
        Ok(service)
    }

    pub async fn dispatch(self: &Arc<Self>, method: &'static str, args: Vec<Value>) -> Value {
        let Some(call) = self.calls.enter() else {
            return unloading_reply(method);
        };
        let service = Arc::clone(self);
        match tokio::task::spawn_blocking(move || {
            let _call = call;
            service.invoke(method, &args)
        })
        .await
        {
            Ok(Ok(result)) => result,
            Ok(Err(message)) => failed_dispatch_reply(method, message),
            Err(error) => failed_dispatch_reply(method, format!("{method} failed: {error}")),
        }
    }

    pub async fn shutdown(&self) -> bool {
        self.shutdown_until(Instant::now() + DRAIN_BUDGET).await
    }

    async fn shutdown_until(&self, deadline: Instant) -> bool {
        self.calls.stop_admission();
        self.operations.cancel_processes();
        let tokio_deadline = tokio::time::Instant::from_std(deadline);
        let calls_stopped = self.calls.wait_for_drain_until(tokio_deadline).await;
        if !calls_stopped || !self.operations.processes_exited() {
            self.log(
                "error",
                "Managed Ludusavi shutdown could not confirm process exit; retaining launch gates (reason=cancellation_unconfirmed retained_gate=true)",
                Some("launch_gate"),
                None,
            );
            return false;
        }
        let watchdog = self.watchdog.clone();
        if !matches!(
            tokio::time::timeout_at(
                tokio_deadline,
                tokio::task::spawn_blocking(move || watchdog.stop_until(deadline))
            )
            .await,
            Ok(Ok(true))
        ) {
            self.log(
                "error",
                "Launch-gate shutdown could not confirm guarded callbacks; retaining launch gates (reason=cancellation_unconfirmed retained_gate=true)",
                Some("launch_gate"),
                None,
            );
            return false;
        }
        true
    }
    pub fn unavailable_reply(method: &str) -> Value {
        python_wrapper_fallback(method)
            .unwrap_or_else(|| failed_reply("Backend has not completed startup".to_owned()))
    }

    fn invoke(&self, method: &str, args: &[Value]) -> Result<Value, String> {
        match method {
            "get_settings" => {
                expect_args(method, args, 0)?;
                Ok(self.get_settings())
            }
            "update_settings" => {
                expect_args(method, args, 1)?;
                let patch = args[0]
                    .as_object()
                    .ok_or_else(|| "Settings patch requires a JSON object".to_owned())?;
                self.update_settings(patch)
            }
            "get_ludusavi_launcher_shortcut_id" => {
                expect_args(method, args, 0)?;
                Ok(json!(self.shortcut_id.load(Ordering::Relaxed)))
            }
            "set_ludusavi_launcher_shortcut_id" => {
                expect_args(method, args, 1)?;
                let app_id = python_integer(&args[0])
                    .ok_or_else(|| "Ludusavi launcher shortcut ID must be an integer".to_owned())?;
                self.set_shortcut_id(app_id)?;
                Ok(Value::Bool(true))
            }
            "log" => {
                if !(2..=4).contains(&args.len()) {
                    return Err(format!(
                        "Plugin.log() expected between 2 and 4 arguments, got {}",
                        args.len()
                    ));
                }
                let level = args[0]
                    .as_str()
                    .ok_or_else(|| "log level must be a string".to_owned())?;
                let message = args[1]
                    .as_str()
                    .ok_or_else(|| "log message must be a string".to_owned())?;
                let operation = args
                    .get(2)
                    .and_then(Value::as_str)
                    .filter(|operation| !operation.is_empty())
                    .unwrap_or("frontend");
                let game_name = args.get(3).and_then(Value::as_str);
                self.log(level, message, Some(operation), game_name);
                Ok(Value::Null)
            }
            "get_recent_logs" => {
                expect_args(method, args, 0)?;
                Ok(self.get_recent_logs())
            }
            "get_operation_status" => {
                expect_args(method, args, 0)?;
                Ok(self.operations.get_operation_status())
            }
            "get_game_history" => {
                expect_args(method, args, 0)?;
                Ok(self.operations.get_game_history())
            }
            "check_game_start" => {
                expect_range(method, args, 1, 2)?;
                self.check_game_start(required_game_name(method, args)?, optional_app_id(args, 1))
            }
            "restore_game_on_start" => {
                expect_range(method, args, 1, 4)?;
                Ok(self.restore_game_on_start(
                    required_game_name(method, args)?,
                    optional_app_id(args, 1),
                    args.get(2).and_then(strict_pid),
                    args.get(3).and_then(Value::as_str),
                ))
            }
            "resolve_game_start_conflict" => {
                expect_range(method, args, 3, 5)?;
                let resolution = args[2]
                    .as_str()
                    .ok_or_else(|| "resolution must be a string".to_owned())?;
                Ok(self.resolve_game_start_conflict(
                    required_game_name(method, args)?,
                    optional_app_id(args, 1),
                    resolution,
                    args.get(3).and_then(strict_pid),
                    args.get(4).and_then(Value::as_str),
                ))
            }
            "check_game_exit" => {
                expect_range(method, args, 1, 2)?;
                self.check_game_exit(required_game_name(method, args)?, optional_app_id(args, 1))
            }
            "backup_game_on_exit" => {
                expect_range(method, args, 1, 2)?;
                Ok(self.backup_game_on_exit(
                    required_game_name(method, args)?,
                    optional_app_id(args, 1),
                ))
            }
            "pause_game_process" => {
                expect_args(method, args, 1)?;
                let pid = args[0]
                    .as_i64()
                    .and_then(|pid| i32::try_from(pid).ok())
                    .ok_or_else(|| "PID must be an integer".to_owned())?;
                Ok(self.watchdog.pause(pid))
            }
            "renew_game_process_pause" => {
                expect_args(method, args, 2)?;
                let pid = args[0]
                    .as_i64()
                    .and_then(|pid| i32::try_from(pid).ok())
                    .ok_or_else(|| "PID must be an integer".to_owned())?;
                let lease_id = args[1]
                    .as_str()
                    .ok_or_else(|| "lease ID must be a string".to_owned())?;
                Ok(self.watchdog.renew(pid, lease_id))
            }
            "resume_game_process" => {
                expect_range(method, args, 1, 2)?;
                let pid = args[0]
                    .as_i64()
                    .and_then(|pid| i32::try_from(pid).ok())
                    .ok_or_else(|| "PID must be an integer".to_owned())?;
                let lease_id = match args.get(1) {
                    None | Some(Value::Null) => None,
                    Some(Value::String(lease_id)) => Some(lease_id.as_str()),
                    Some(_) => return Err("lease ID must be a string or null".to_owned()),
                };
                Ok(self.watchdog.resume(pid, lease_id))
            }
            "refresh_games" => {
                if args.len() > 2 {
                    return Err(format!(
                        "Plugin.{method}() expected at most 2 arguments, got {}",
                        args.len()
                    ));
                }
                let force = args.first().is_some_and(python_truthy);
                let installed_ids = args.get(1).and_then(Value::as_str);
                Ok(self.operations.refresh_games(force, installed_ids))
            }
            "is_game_cache_current" => {
                if args.len() > 1 {
                    return Err(format!(
                        "Plugin.{method}() expected at most 1 argument, got {}",
                        args.len()
                    ));
                }
                Ok(Value::Bool(self.operations.is_game_cache_current(
                    args.first().and_then(Value::as_str),
                )))
            }
            "force_backup" | "force_restore" | "list_backups" => {
                expect_args(method, args, 1)?;
                let name = args[0]
                    .as_str()
                    .ok_or_else(|| format!("{method} requires a game name string"))?;
                match method {
                    "force_backup" => self.operations.force_backup(name),
                    "force_restore" => self.operations.force_restore(name),
                    _ => self.operations.list_backups(name),
                }
            }
            "restore_backup_version" => {
                expect_args(method, args, 2)?;
                let name = args[0].as_str().ok_or_else(|| {
                    "restore_backup_version requires a game name string".to_owned()
                })?;
                let backup_id = args[1].as_str().ok_or_else(|| {
                    "restore_backup_version requires a backup ID string".to_owned()
                })?;
                self.operations.restore_backup_version(name, backup_id)
            }
            "get_versions" => {
                expect_args(method, args, 0)?;
                self.operations.get_versions()
            }
            "get_ludusavi_logs" => {
                expect_args(method, args, 0)?;
                self.operations.get_ludusavi_logs()
            }
            "get_ludusavi_command" => {
                expect_args(method, args, 0)?;
                Ok(self.operations.get_ludusavi_command())
            }
            _ => Err(format!("Plugin has no method {method}")),
        }
    }
    fn check_game_start(&self, name: &str, app_id: Option<&str>) -> Result<Value, String> {
        let game_name = sanitize_game_name(name);
        self.log(
            "info",
            &format!("check_game_start triggered for game='{game_name}', app_id='{app_id:?}'"),
            Some("start"),
            Some(&game_name),
        );
        if !self.auto_sync_enabled() {
            return Ok(self.skip_lifecycle("start", &game_name, "auto_sync_disabled"));
        }
        let game = match self.operations.matching_lifecycle_game(&game_name, app_id) {
            Ok(Some(game)) => game,
            Ok(None) => return Ok(self.skip_lifecycle("start", &game_name, "unmatched_game")),
            Err(OperationError::Locked(_)) => {
                return Ok(self.skip_lifecycle("start", &game_name, "operation_running"));
            }
            Err(OperationError::Cancelled) => {
                return Ok(self.skip_lifecycle("start", &game_name, "cancelled"));
            }
            Err(OperationError::Failed(message)) => return Err(message),
        };
        let game_name = game["name"].as_str().unwrap_or(&game_name);
        if !self.game_sync_enabled(game_name) {
            return Ok(self.skip_lifecycle("start", game_name, "game_sync_disabled"));
        }
        if !game["has_backup"].as_bool().unwrap_or(false) {
            return Ok(self.skip_lifecycle("start", game_name, "no_backup"));
        }
        if game["error"]
            .as_str()
            .is_some_and(|error| !error.is_empty())
        {
            return Ok(self.skip_lifecycle("start", game_name, "game_error"));
        }

        let recency = match self.operations.start_recency(game_name) {
            Ok(result) => result,
            Err(OperationError::Locked(_)) => {
                return Ok(self.skip_lifecycle("start", game_name, "operation_running"));
            }
            Err(OperationError::Cancelled) => {
                return Ok(self.skip_lifecycle("start", game_name, "cancelled"));
            }
            Err(OperationError::Failed(message)) => return Err(message),
        };
        let direction = recency
            .get("recency")
            .and_then(Value::as_str)
            .unwrap_or("ambiguous");
        let metadata = recency
            .get("metadata")
            .cloned()
            .unwrap_or_else(|| json!({}));
        if direction == "backup_newer" {
            self.log(
                "info",
                &format!("Restore needed for {game_name}: backup is newer than the local save"),
                Some("start"),
                Some(game_name),
            );
            return Ok(json!({"status":"needed","operation":"restore","game":game_name}));
        }
        if direction == "local_current" {
            return Ok(self.skip_lifecycle("start", game_name, "local_current"));
        }

        let local_modified_at = metadata.get("localModifiedAt").and_then(Value::as_str);
        let backup_modified_at = metadata.get("backupModifiedAt").and_then(Value::as_str);
        if direction == "backup_differs" {
            match timestamp_direction(local_modified_at, backup_modified_at) {
                TimestampDirection::BackupNewer => {
                    self.log(
                        "info",
                        &format!(
                            "Backup for {game_name} differs and is newer by timestamp; proceeding with restore (local={local_modified_at:?}, backup={backup_modified_at:?})"
                        ),
                        Some("start"),
                        Some(game_name),
                    );
                    return Ok(json!({"status":"needed","operation":"restore","game":game_name}));
                }
                direction => self.log(
                    "info",
                    &format!(
                        "Backup for {game_name} differs but direction is {direction:?}; deferring to conflict resolution (local={local_modified_at:?}, backup={backup_modified_at:?})"
                    ),
                    Some("start"),
                    Some(game_name),
                ),
            }
        }

        self.log(
            "info",
            &format!(
                "Recency for {game_name} is {direction}; prompting user to resolve conflict (local={local_modified_at:?}, backup={backup_modified_at:?})"
            ),
            Some("start"),
            Some(game_name),
        );
        self.record_lifecycle_history(
            game_name,
            "start",
            "auto_start",
            "skipped",
            Some("ambiguous_recency"),
            None,
        );
        let mut result = json!({
            "status":"conflict",
            "operation":"restore",
            "game":game_name,
            "reason":"ambiguous_recency",
            "localLabel":"Keep Local Save",
            "backupLabel":"Restore Backup Save",
        });
        if let (Some(output), Some(input)) = (result.as_object_mut(), metadata.as_object()) {
            output.extend(
                input
                    .iter()
                    .map(|(key, value)| (key.clone(), value.clone())),
            );
        }
        Ok(result)
    }

    fn check_game_exit(&self, name: &str, app_id: Option<&str>) -> Result<Value, String> {
        let game_name = sanitize_game_name(name);
        self.log(
            "info",
            &format!("check_game_exit triggered for game='{game_name}', app_id='{app_id:?}'"),
            Some("exit"),
            Some(&game_name),
        );
        if !self.auto_sync_enabled() {
            return Ok(self.skip_lifecycle("exit", &game_name, "auto_sync_disabled"));
        }
        let game = match self.operations.matching_lifecycle_game(&game_name, app_id) {
            Ok(Some(game)) => game,
            Ok(None) => return Ok(self.skip_lifecycle("exit", &game_name, "unmatched_game")),
            Err(OperationError::Locked(_)) => {
                return Ok(self.skip_lifecycle("exit", &game_name, "operation_running"));
            }
            Err(OperationError::Cancelled | OperationError::Failed(_)) => {
                return Ok(self.skip_lifecycle("exit", &game_name, "preview_failed"));
            }
        };
        let game_name = game["name"].as_str().unwrap_or(&game_name);
        if !self.game_sync_enabled(game_name) {
            return Ok(self.skip_lifecycle("exit", game_name, "game_sync_disabled"));
        }
        if game["error"]
            .as_str()
            .is_some_and(|error| !error.is_empty())
        {
            return Ok(self.skip_lifecycle("exit", game_name, "game_error"));
        }
        let preview = match self.operations.exit_preview(game_name) {
            Ok(preview) => preview,
            Err(OperationError::Locked(_)) => {
                return Ok(self.skip_lifecycle("exit", game_name, "operation_running"));
            }
            Err(OperationError::Cancelled | OperationError::Failed(_)) => {
                return Ok(self.skip_lifecycle("exit", game_name, "preview_failed"));
            }
        };
        let games = preview.get("games").and_then(Value::as_object);
        let Some(output) = games.and_then(|games| games.get(game_name)) else {
            return Ok(self.skip_lifecycle("exit", game_name, "not_in_preview"));
        };
        let decision = output.get("decision").and_then(Value::as_str);
        let files = output.get("files");
        let registry = output.get("registry");
        let change = output.get("change").and_then(Value::as_str);
        let file_count = files.and_then(Value::as_object).map_or(0, Map::len);
        let registry_count = registry.and_then(Value::as_object).map_or(0, Map::len);
        self.log(
            "info",
            &format!(
                "Exit preview for {game_name}: decision={decision:?} change={change:?} files={file_count} registry={registry_count}"
            ),
            Some("exit"),
            Some(game_name),
        );
        if matches!(decision, Some("Ignored" | "Cancelled")) {
            return Ok(self.skip_lifecycle("exit", game_name, "not_processed"));
        }
        if !python_truthy(files.unwrap_or(&Value::Null))
            && !python_truthy(registry.unwrap_or(&Value::Null))
        {
            return Ok(self.skip_lifecycle("exit", game_name, "no_files_found"));
        }
        if change == Some("Same") {
            return Ok(self.skip_lifecycle("exit", game_name, "local_current"));
        }
        Ok(json!({"status":"needed","operation":"backup","game":game_name}))
    }

    fn restore_game_on_start(
        &self,
        name: &str,
        app_id: Option<&str>,
        gate_pid: Option<i32>,
        gate_lease_id: Option<&str>,
    ) -> Value {
        let game_name = sanitize_game_name(name);
        self.log(
            "info",
            &format!("restore_game_on_start triggered for game='{game_name}', app_id='{app_id:?}'"),
            Some("restore"),
            Some(&game_name),
        );
        if !self.auto_sync_enabled() {
            return self.skip_lifecycle("start", &game_name, "auto_sync_disabled");
        }
        let game = match self.operations.matching_lifecycle_game(&game_name, app_id) {
            Ok(Some(game)) => game,
            Ok(None) => return self.skip_lifecycle("start", &game_name, "unmatched_game"),
            Err(OperationError::Locked(_)) => {
                return self.skip_lifecycle("start", &game_name, "operation_running");
            }
            Err(OperationError::Cancelled) => {
                return self.skip_lifecycle("start", &game_name, "cancelled");
            }
            Err(OperationError::Failed(message)) => {
                return json!({"status":"failed","game":game_name,"message":message});
            }
        };
        let game_name = game["name"].as_str().unwrap_or(&game_name);
        if !self.game_sync_enabled(game_name) {
            return self.skip_lifecycle("start", game_name, "game_sync_disabled");
        }
        if !game["has_backup"].as_bool().unwrap_or(false) {
            return self.skip_lifecycle("start", game_name, "no_backup");
        }
        if game["error"]
            .as_str()
            .is_some_and(|error| !error.is_empty())
        {
            return self.skip_lifecycle("start", game_name, "game_error");
        }
        let (Some(pid), Some(lease_id)) = (gate_pid, gate_lease_id.filter(|id| !id.is_empty()))
        else {
            return self.skip_lifecycle("start", game_name, "gate_lost");
        };
        if !self.watchdog.verify_gate(pid, lease_id) {
            return self.skip_lifecycle("start", game_name, "gate_lost");
        }
        self.execute_start_mutation(
            game_name,
            "restore",
            pid,
            lease_id,
            false,
            "Restored {game_name} before launch",
        )
    }

    fn resolve_game_start_conflict(
        &self,
        name: &str,
        app_id: Option<&str>,
        resolution: &str,
        gate_pid: Option<i32>,
        gate_lease_id: Option<&str>,
    ) -> Value {
        let game_name = sanitize_game_name(name);
        if !matches!(resolution, "keep_local" | "restore_backup") {
            return self.skip_lifecycle("start", &game_name, "invalid_resolution");
        }
        if !self.auto_sync_enabled() {
            return self.skip_lifecycle("start", &game_name, "auto_sync_disabled");
        }
        let game = match self.operations.matching_lifecycle_game(&game_name, app_id) {
            Ok(Some(game)) => game,
            Ok(None) => return self.skip_lifecycle("start", &game_name, "unmatched_game"),
            Err(OperationError::Locked(_)) => {
                return self.skip_lifecycle("start", &game_name, "operation_running");
            }
            Err(OperationError::Cancelled) => {
                return self.skip_lifecycle("start", &game_name, "cancelled");
            }
            Err(OperationError::Failed(message)) => {
                return json!({"status":"failed","game":game_name,"message":message});
            }
        };
        let game_name = game["name"].as_str().unwrap_or(&game_name);
        if !self.game_sync_enabled(game_name) {
            return self.skip_lifecycle("start", game_name, "game_sync_disabled");
        }
        if game["error"]
            .as_str()
            .is_some_and(|error| !error.is_empty())
        {
            return self.skip_lifecycle("start", game_name, "game_error");
        }
        let (Some(pid), Some(lease_id)) = (gate_pid, gate_lease_id.filter(|id| !id.is_empty()))
        else {
            return self.skip_lifecycle("start", game_name, "gate_lost");
        };
        if !self.watchdog.verify_gate(pid, lease_id) {
            return self.skip_lifecycle("start", game_name, "gate_lost");
        }
        let restore = resolution == "restore_backup";
        if restore && !game["has_backup"].as_bool().unwrap_or(false) {
            return self.skip_lifecycle("start", game_name, "no_backup");
        }
        self.execute_start_mutation(
            game_name,
            if restore { "restore" } else { "backup" },
            pid,
            lease_id,
            true,
            if restore {
                "Restored backup save for {game_name}"
            } else {
                "Kept local save for {game_name}"
            },
        )
    }

    fn execute_start_mutation(
        &self,
        game_name: &str,
        operation: &str,
        pid: i32,
        lease_id: &str,
        record_before_log: bool,
        success_message: &str,
    ) -> Value {
        let watchdog = self.watchdog.clone();
        let guarded_lease = lease_id.to_owned();
        let result =
            self.operations
                .start_mutation(
                    game_name,
                    operation == "restore",
                    move |command| match watchdog.run_guarded(pid, &guarded_lease, command) {
                        Some(result) => result,
                        None => Err("launch_gate_lost".to_owned()),
                    },
                );
        let (status, trigger) = if operation == "restore" {
            ("restored", "auto_start")
        } else {
            ("backed_up", "auto_start")
        };
        match result {
            Ok(value) => {
                if record_before_log {
                    self.record_lifecycle_history(
                        game_name, operation, trigger, status, None, None,
                    );
                }
                let message = success_message.replace("{game_name}", game_name);
                self.log("info", &message, Some(operation), Some(game_name));
                if !record_before_log {
                    self.record_lifecycle_history(
                        game_name, operation, trigger, status, None, None,
                    );
                }
                json!({"status":status,"game":game_name,"result":value})
            }
            Err(OperationError::Locked(_)) => {
                self.skip_lifecycle("start", game_name, "operation_running")
            }
            Err(OperationError::Cancelled) => {
                self.record_lifecycle_history(
                    game_name,
                    operation,
                    trigger,
                    "skipped",
                    Some("cancelled"),
                    None,
                );
                self.log(
                    "info",
                    &format!("{operation} cancelled for {game_name}"),
                    Some(operation),
                    Some(game_name),
                );
                json!({"status":"skipped","reason":"cancelled","game":game_name})
            }
            Err(OperationError::Failed(message)) if message == "launch_gate_lost" => {
                self.skip_lifecycle("start", game_name, "gate_lost")
            }
            Err(OperationError::Failed(message)) => {
                self.record_lifecycle_history(
                    game_name,
                    operation,
                    trigger,
                    "failed",
                    None,
                    Some(&message),
                );
                json!({"status":"failed","game":game_name,"message":message})
            }
        }
    }

    fn backup_game_on_exit(&self, name: &str, app_id: Option<&str>) -> Value {
        let game_name = sanitize_game_name(name);
        self.log(
            "info",
            &format!("backup_game_on_exit triggered for game='{game_name}', app_id='{app_id:?}'"),
            Some("backup"),
            Some(&game_name),
        );
        if !self.auto_sync_enabled() {
            return self.skip_lifecycle("exit", &game_name, "auto_sync_disabled");
        }
        let game = match self.operations.matching_lifecycle_game(&game_name, app_id) {
            Ok(Some(game)) => game,
            Ok(None) => return self.skip_lifecycle("exit", &game_name, "unmatched_game"),
            Err(OperationError::Locked(_)) => {
                return self.skip_lifecycle("exit", &game_name, "operation_running");
            }
            Err(OperationError::Cancelled) => {
                return self.skip_lifecycle("exit", &game_name, "cancelled");
            }
            Err(OperationError::Failed(message)) => {
                return json!({"status":"failed","game":game_name,"message":message});
            }
        };
        let game_name = game["name"].as_str().unwrap_or(&game_name);
        if !self.game_sync_enabled(game_name) {
            return self.skip_lifecycle("exit", game_name, "game_sync_disabled");
        }
        if game["error"]
            .as_str()
            .is_some_and(|error| !error.is_empty())
        {
            return self.skip_lifecycle("exit", game_name, "game_error");
        }
        match self.operations.backup_on_exit(game_name) {
            Ok(result) => {
                self.record_lifecycle_history(
                    game_name,
                    "backup",
                    "auto_exit",
                    "backed_up",
                    None,
                    None,
                );
                self.operations.refresh_after_lifecycle(game_name);
                self.log(
                    "info",
                    &format!("Backed up {game_name} after exit"),
                    Some("backup"),
                    Some(game_name),
                );
                json!({"status":"backed_up","game":game_name,"result":result})
            }
            Err(OperationError::Locked(_)) => {
                self.skip_lifecycle("exit", game_name, "operation_running")
            }
            Err(OperationError::Cancelled) => {
                self.record_lifecycle_history(
                    game_name,
                    "backup",
                    "auto_exit",
                    "skipped",
                    Some("cancelled"),
                    None,
                );
                self.log(
                    "info",
                    &format!("backup cancelled for {game_name}"),
                    Some("backup"),
                    Some(game_name),
                );
                json!({"status":"skipped","reason":"cancelled","game":game_name})
            }
            Err(OperationError::Failed(message)) => {
                self.record_lifecycle_history(
                    game_name,
                    "backup",
                    "auto_exit",
                    "failed",
                    None,
                    Some(&message),
                );
                json!({"status":"failed","game":game_name,"message":message})
            }
        }
    }

    fn auto_sync_enabled(&self) -> bool {
        setting_bool(&lock(&self.settings), "auto_sync_enabled", false)
    }

    fn game_sync_enabled(&self, game_name: &str) -> bool {
        !lock(&self.settings)
            .get("sync_disabled_games")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(sanitize_game_name)
            .any(|disabled| disabled == game_name)
    }

    fn skip_lifecycle(&self, operation: &str, game_name: &str, reason: &str) -> Value {
        self.log(
            "info",
            &format!("Skipped {operation} for {game_name}: {reason}"),
            Some(operation),
            Some(game_name),
        );
        if !matches!(
            reason,
            "auto_sync_disabled" | "game_sync_disabled" | "operation_running" | "unmatched_game"
        ) {
            let (history_operation, trigger) = match operation {
                "start" => ("start", "auto_start"),
                "exit" => ("exit", "auto_exit"),
                _ => (operation, "unknown"),
            };
            self.record_lifecycle_history(
                game_name,
                history_operation,
                trigger,
                "skipped",
                Some(reason),
                None,
            );
        }
        json!({"status":"skipped","game":game_name,"reason":reason})
    }

    fn record_lifecycle_history(
        &self,
        game_name: &str,
        operation: &str,
        trigger: &str,
        status: &str,
        reason: Option<&str>,
        message: Option<&str>,
    ) {
        if let Err(error) = self
            .operations
            .record_lifecycle_history(game_name, operation, trigger, status, reason, message)
        {
            log::error!("Could not record lifecycle history for {game_name}: {error}");
        }
    }

    fn get_settings(&self) -> Value {
        settings_view(&lock(&self.settings))
    }

    fn update_settings(&self, patch: &Map<String, Value>) -> Result<Value, String> {
        let kind = patch
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| "Settings patch requires a string kind".to_owned())?;
        if kind == "game_sync" && patch_game_name(patch)?.is_empty() {
            return Ok(self.get_settings());
        }
        self.state_lock
            .with_lock(|| {
                let mut settings = match read_object(&self.settings_path) {
                    Ok(Some(settings)) => settings,
                    Ok(None) => lock(&self.settings).clone(),
                    Err(error) => {
                        log::warn!(
                            "Could not reload settings at {}: {error}; retaining last good state",
                            self.settings_path.display()
                        );
                        lock(&self.settings).clone()
                    }
                };
                apply_settings_patch(&mut settings, patch)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
                let mode = existing_mode(&self.settings_path, 0o644)?;
                write_json_atomic(&self.settings_path, &settings, mode, b"    ")?;
                let debug_logging = setting_bool(&settings, "debug_logging", true);
                *lock(&self.settings) = settings;
                self.debug_logging.store(debug_logging, Ordering::Relaxed);
                log::set_max_level(if debug_logging {
                    log::LevelFilter::Debug
                } else {
                    log::LevelFilter::Info
                });
                Ok(())
            })
            .map_err(|error| error.to_string())?;
        self.log(
            "info",
            &format!("Settings patch applied: {kind}"),
            None,
            None,
        );
        Ok(self.get_settings())
    }

    fn set_shortcut_id(&self, app_id: i64) -> Result<(), String> {
        self.state_lock
            .with_lock(|| {
                let mut cache = read_object(&self.cache_path)?.unwrap_or_default();
                cache.insert("ludusaviLauncherShortcutAppId".to_owned(), json!(app_id));
                write_json_atomic(&self.cache_path, &cache, 0o600, b"  ")?;
                self.shortcut_id.store(app_id, Ordering::Relaxed);
                Ok(())
            })
            .map_err(|error| error.to_string())?;
        self.log(
            "info",
            &format!("Saved Ludusavi launcher shortcut ID: {app_id}"),
            None,
            None,
        );
        Ok(())
    }

    fn log(&self, level: &str, message: &str, operation: Option<&str>, game_name: Option<&str>) {
        let entry = json!({
            "level": level,
            "message": message,
            "timestamp": log_timestamp(),
            "operation": operation,
            "game_name": game_name,
        });
        {
            let mut logs = lock(&self.logs);
            if logs.len() == LOG_LIMIT {
                logs.pop_front();
            }
            logs.push_back(entry);
        }
        if level == "debug" && !self.debug_logging.load(Ordering::Relaxed) {
            return;
        }

        let context = operation.unwrap_or("backend");
        let formatted = match game_name.filter(|name| !name.is_empty()) {
            Some(name) => format!("[{name}] {context}: {message}"),
            None => format!("{context}: {message}"),
        };
        match level {
            "debug" => log::debug!("{formatted}"),
            "info" => log::info!("{formatted}"),
            "warning" => log::warn!("{formatted}"),
            "error" | "critical" => log::error!("{formatted}"),
            _ => log::info!("{formatted}"),
        }
    }

    fn get_recent_logs(&self) -> Value {
        Value::Array(lock(&self.logs).iter().cloned().collect())
    }
}

fn required_path(path: &Path, name: &str) -> io::Result<PathBuf> {
    if path.as_os_str().is_empty() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("{name} is required for SDH-ludusavi storage"),
        ));
    }
    Ok(path.to_owned())
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

fn expect_range(
    method: &str,
    args: &[Value],
    minimum: usize,
    maximum: usize,
) -> Result<(), String> {
    if (minimum..=maximum).contains(&args.len()) {
        Ok(())
    } else {
        Err(format!(
            "Plugin.{method}() expected between {minimum} and {maximum} arguments, got {}",
            args.len()
        ))
    }
}

fn required_game_name<'a>(method: &str, args: &'a [Value]) -> Result<&'a str, String> {
    args.first()
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{method} requires a game name string"))
}

fn optional_app_id(args: &[Value], index: usize) -> Option<&str> {
    args.get(index).and_then(Value::as_str)
}

fn strict_pid(value: &Value) -> Option<i32> {
    value.as_i64().and_then(|pid| i32::try_from(pid).ok())
}

fn expect_args(method: &str, args: &[Value], expected: usize) -> Result<(), String> {
    if args.len() == expected {
        Ok(())
    } else {
        Err(format!(
            "Plugin.{method}() expected {expected} arguments, got {}",
            args.len()
        ))
    }
}

fn failed_reply(message: String) -> Value {
    json!({"status": "failed", "message": message})
}

fn failed_dispatch_reply(method: &str, message: String) -> Value {
    python_wrapper_fallback(method).unwrap_or_else(|| failed_reply(message))
}

fn python_wrapper_fallback(method: &str) -> Option<Value> {
    match method {
        "get_recent_logs" => Some(json!([])),
        "get_operation_status" => Some(idle_operation_status()),
        "get_ludusavi_launcher_shortcut_id" => Some(json!(-1)),
        "is_game_cache_current" => Some(Value::Bool(false)),
        "log" => Some(Value::Null),
        _ => None,
    }
}

fn idle_operation_status() -> Value {
    json!({
        "is_running": false,
        "name": null,
        "game_name": null,
        "last_result": null,
        "last_error": null,
    })
}

fn unloading_reply(method: &str) -> Value {
    python_wrapper_fallback(method).unwrap_or_else(|| {
        json!({
            "status": "skipped",
            "reason": "unloading",
            "message": "Plugin unload is in progress.",
        })
    })
}

fn python_integer(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_u64().and_then(|value| i64::try_from(value).ok()))
            .or_else(|| number.as_f64().map(|value| value as i64)),
        Value::String(value) => value.trim().parse().ok(),
        Value::Bool(value) => Some(i64::from(*value)),
        _ => None,
    }
}

fn setting_bool(settings: &Map<String, Value>, key: &str, default: bool) -> bool {
    settings.get(key).map_or(default, python_truthy)
}

fn python_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|value| value != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_owned(),
        Value::Bool(true) => "True".to_owned(),
        Value::Bool(false) => "False".to_owned(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn sanitize_game_name(value: &str) -> String {
    let mut normalized = String::new();
    for word in value.split_whitespace() {
        if !normalized.is_empty() {
            normalized.push(' ');
        }
        normalized.push_str(word);
    }
    normalized
}

fn settings_view(settings: &Map<String, Value>) -> Value {
    let disabled_games = settings
        .get("sync_disabled_games")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(sanitize_game_name)
        .filter(|name| !name.is_empty())
        .collect::<BTreeSet<_>>();
    let notifications = notification_settings(settings.get("notifications"));
    let update_channel = match settings.get("update_channel").and_then(Value::as_str) {
        Some("development") => "development",
        Some("stable") => "stable",
        _ => "stable",
    };

    json!({
        "auto_sync_enabled": setting_bool(settings, "auto_sync_enabled", false),
        "sync_disabled_games": disabled_games,
        "selected_game": settings
            .get("selected_game")
            .map(python_string)
            .unwrap_or_default(),
        "debug_logging": setting_bool(settings, "debug_logging", true),
        "notifications": notifications,
        "update_channel": update_channel,
        "automatic_update_checks": settings
            .get("automatic_update_checks")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    })
}

fn notification_settings(value: Option<&Value>) -> Map<String, Value> {
    let mut notifications = Map::new();
    for key in DEFAULT_NOTIFICATIONS {
        let value = value
            .and_then(Value::as_object)
            .and_then(|settings| settings.get(key))
            .and_then(Value::as_bool)
            .unwrap_or(true);
        notifications.insert(key.to_owned(), Value::Bool(value));
    }
    notifications
}

fn apply_settings_patch(
    settings: &mut Map<String, Value>,
    patch: &Map<String, Value>,
) -> Result<(), String> {
    let kind = patch
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| "Settings patch requires a string kind".to_owned())?;

    match kind {
        "auto_sync" => {
            settings.insert(
                "auto_sync_enabled".to_owned(),
                Value::Bool(patch_bool(patch, "enabled")?),
            );
        }
        "game_sync" => {
            let game_name = patch_game_name(patch)?;
            let mut disabled_games = settings
                .get("sync_disabled_games")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(sanitize_game_name)
                .filter(|name| !name.is_empty())
                .collect::<BTreeSet<_>>();
            if patch_bool(patch, "enabled")? {
                disabled_games.remove(&game_name);
            } else {
                disabled_games.insert(game_name);
            }
            settings.insert(
                "sync_disabled_games".to_owned(),
                serde_json::to_value(disabled_games).map_err(|error| error.to_string())?,
            );
        }
        "selected_game" => {
            settings.insert(
                "selected_game".to_owned(),
                Value::String(patch_game_name(patch)?),
            );
        }
        "notification" => {
            let key = patch
                .get("key")
                .and_then(Value::as_str)
                .filter(|key| DEFAULT_NOTIFICATIONS.contains(key))
                .ok_or_else(|| "Settings notification patch has an invalid key".to_owned())?;
            let mut notifications = notification_settings(settings.get("notifications"));
            notifications.insert(key.to_owned(), Value::Bool(patch_bool(patch, "enabled")?));
            settings.insert("notifications".to_owned(), Value::Object(notifications));
        }
        "update_channel" => {
            let channel = patch
                .get("channel")
                .and_then(Value::as_str)
                .filter(|channel| matches!(*channel, "stable" | "development"))
                .ok_or_else(|| "Settings update channel is invalid".to_owned())?;
            settings.insert(
                "update_channel".to_owned(),
                Value::String(channel.to_owned()),
            );
        }
        "automatic_update_checks" => {
            settings.insert(
                "automatic_update_checks".to_owned(),
                Value::Bool(patch_bool(patch, "enabled")?),
            );
        }
        "debug_logging" => {
            settings.insert(
                "debug_logging".to_owned(),
                Value::Bool(patch_bool(patch, "enabled")?),
            );
        }
        _ => return Err(format!("Unknown settings patch kind: {kind}")),
    }
    Ok(())
}

fn patch_bool(patch: &Map<String, Value>, key: &str) -> Result<bool, String> {
    patch
        .get(key)
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("Settings patch requires boolean {key}"))
}

fn patch_game_name(patch: &Map<String, Value>) -> Result<String, String> {
    patch
        .get("game_name")
        .and_then(Value::as_str)
        .map(sanitize_game_name)
        .ok_or_else(|| "Settings patch requires string game_name".to_owned())
}

fn normalize_history(value: Option<&Value>) -> Value {
    let Some(history) = value.and_then(Value::as_object) else {
        return Value::Object(Map::new());
    };
    let mut normalized = Map::new();
    for (game, records) in history {
        let Some(records) = records.as_object() else {
            continue;
        };
        let mut result = Map::new();
        let mut newest: Option<(i128, &str)> = None;
        for field in ["last_backup", "last_restore", "last_skip", "last_failure"] {
            let entry = records.get(field).and_then(valid_history_entry);
            if let Some(timestamp) = entry
                .as_ref()
                .and_then(|entry| entry.get("timestamp"))
                .and_then(Value::as_str)
                .filter(|timestamp| !timestamp.is_empty())
            {
                let order = parse_iso_timestamp(timestamp).unwrap_or(i128::MIN);
                if newest
                    .as_ref()
                    .is_none_or(|(previous, _)| order > *previous)
                {
                    newest = Some((order, field));
                }
            }
            result.insert(field.to_owned(), entry.unwrap_or(Value::Null));
        }
        let last_operation = newest
            .and_then(|(_, field)| result.get(field).cloned())
            .unwrap_or(Value::Null);
        result.insert("last_operation".to_owned(), last_operation);
        normalized.insert(game.clone(), Value::Object(result));
    }
    Value::Object(normalized)
}

fn valid_history_entry(value: &Value) -> Option<Value> {
    let entry = value.as_object()?;
    let operation = entry.get("operation")?.as_str()?;
    if !matches!(operation, "backup" | "restore" | "start" | "exit") {
        return None;
    }
    let trigger = entry.get("trigger")?.as_str()?;
    if !matches!(
        trigger,
        "manual_backup" | "manual_restore" | "auto_start" | "auto_exit"
    ) {
        return None;
    }
    let status = entry.get("status")?.as_str()?;
    if !matches!(status, "backed_up" | "restored" | "skipped" | "failed") {
        return None;
    }
    let timestamp = entry.get("timestamp")?.as_str()?;
    let mut normalized = Map::new();
    normalized.insert("operation".to_owned(), Value::String(operation.to_owned()));
    normalized.insert("trigger".to_owned(), Value::String(trigger.to_owned()));
    normalized.insert("status".to_owned(), Value::String(status.to_owned()));
    for key in ["reason", "message"] {
        let value = entry
            .get(key)
            .filter(|value| value.is_string() || value.is_null())
            .cloned()
            .unwrap_or(Value::Null);
        normalized.insert(key.to_owned(), value);
    }
    normalized.insert("timestamp".to_owned(), Value::String(timestamp.to_owned()));
    Some(Value::Object(normalized))
}

fn parse_iso_timestamp(value: &str) -> Option<i128> {
    let normalized = if value.contains(' ') && !value.contains('T') {
        value.replacen(' ', "T", 1)
    } else if let Some(timestamp) = value.strip_suffix('z') {
        format!("{timestamp}Z")
    } else {
        value.to_owned()
    };
    let candidate = if normalized.contains('T') {
        let time = normalized.split_once('T')?.1;
        if time.ends_with('Z') || time.contains('+') || time.contains('-') {
            normalized
        } else {
            format!("{normalized}Z")
        }
    } else {
        format!("{normalized}T00:00:00Z")
    };
    OffsetDateTime::parse(&candidate, &Rfc3339)
        .ok()
        .map(|timestamp| timestamp.unix_timestamp_nanos())
}

fn log_timestamp() -> String {
    static FORMAT: LazyLock<Vec<time::format_description::FormatItem<'static>>> =
        LazyLock::new(|| {
            format_description::parse_borrowed::<1>("[year]-[month]-[day] [hour]:[minute]:[second]")
                .expect("valid static log timestamp format")
        });
    OffsetDateTime::now_local()
        .unwrap_or_else(|_| OffsetDateTime::now_utc())
        .format(&FORMAT)
        .unwrap_or_else(|_| "1970-01-01 00:00:00".to_owned())
}

#[derive(Default)]
struct TrackerState {
    stopping: bool,
    active: usize,
}

#[derive(Default)]
struct CallTracker {
    state: Mutex<TrackerState>,
    changed: Notify,
}

impl CallTracker {
    fn enter(self: &Arc<Self>) -> Option<ActiveCall> {
        let mut state = lock(&self.state);
        if state.stopping {
            return None;
        }
        state.active += 1;
        Some(ActiveCall(Arc::clone(self)))
    }

    fn stop_admission(&self) {
        lock(&self.state).stopping = true;
    }

    async fn wait_for_drain_until(&self, deadline: tokio::time::Instant) -> bool {
        loop {
            let notified = self.changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            if lock(&self.state).active == 0 {
                return true;
            }
            if tokio::time::timeout_at(deadline, notified).await.is_err() {
                return lock(&self.state).active == 0;
            }
        }
    }
}

struct ActiveCall(Arc<CallTracker>);

impl Drop for ActiveCall {
    fn drop(&mut self) {
        let mut state = lock(&self.0.state);
        state.active -= 1;
        drop(state);
        self.0.changed.notify_waiters();
    }
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        sync::{Arc, Barrier},
        thread,
        time::{Duration, Instant},
    };

    use decky_plugin::Env;
    use serde_json::{Value, json};
    use tempfile::tempdir_in;

    use super::{BackendService, LOG_LIMIT};

    fn test_service() -> (tempfile::TempDir, Arc<BackendService>) {
        let directory = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let env = Env {
            plugin_settings_dir: directory.path().join("settings"),
            plugin_runtime_dir: directory.path().join("runtime"),
            ..Env::default()
        };
        let service = Arc::new(BackendService::new(&env).unwrap());
        (directory, service)
    }
    #[tokio::test]
    async fn list_backups_cancellation_returns_skipped_through_dispatch() {
        for include_game in [true, false] {
            let (_directory, service) = test_service();
            service
                .operations
                .prepare_cancelled_list_backups_test(include_game);
            assert_eq!(
                service.dispatch("list_backups", vec![json!("Hades")]).await,
                json!({"status":"skipped","reason":"cancelled"})
            );
        }
    }

    #[test]
    fn lifecycle_match_lazily_refreshes_an_empty_registry() {
        let (directory, service) = test_service();
        let config_path = directory.path().join("config.yaml");
        fs::write(&config_path, "fixture").unwrap();
        let flatpak = directory.path().join("flatpak");
        let script = r#"#!/bin/sh
case "$3" in
    backup) printf '%s\n' '{"games":{"Hades":{"files":{"save":{}},"decision":"Same","steamId":"300"}}}' ;;
    backups) printf '%s\n' '{"games":{"Hades":{"backups":[{"name":"latest"}]}}}' ;;
    restore) printf '%s\n' '{"games":{"Hades":{"change":"Same"}}}' ;;
    config)
        if [ "$4" = path ]; then
            printf '%s\n' '@CONFIG_PATH@'
        else
            printf '%s\n' '{"customGames":[]}'
        fi
        ;;
esac
"#
        .replace("@CONFIG_PATH@", &config_path.display().to_string());
        fs::write(&flatpak, script).unwrap();
        fs::set_permissions(&flatpak, fs::Permissions::from_mode(0o755)).unwrap();
        service.operations.use_ludusavi_test_command(flatpak);
        service
            .update_settings(
                json!({"kind":"auto_sync","enabled":true})
                    .as_object()
                    .unwrap(),
            )
            .unwrap();

        let result = service.check_game_start("Hades", Some("300")).unwrap();

        assert_eq!(
            result,
            json!({"status":"skipped","game":"Hades","reason":"local_current"})
        );
    }

    #[test]
    fn lifecycle_registry_refresh_failure_is_not_unmatched() {
        let (directory, service) = test_service();
        let flatpak = directory.path().join("flatpak");
        fs::write(&flatpak, "#!/bin/sh\nexit 7\n").unwrap();
        fs::set_permissions(&flatpak, fs::Permissions::from_mode(0o755)).unwrap();
        service.operations.use_ludusavi_test_command(flatpak);
        service
            .update_settings(
                json!({"kind":"auto_sync","enabled":true})
                    .as_object()
                    .unwrap(),
            )
            .unwrap();

        let error = service.check_game_start("Hades", None).unwrap_err();

        assert!(!error.is_empty());
    }

    #[test]
    fn lifecycle_registry_lock_failure_is_operation_running() {
        let (directory, service) = test_service();
        let flatpak = directory.path().join("flatpak");
        fs::write(&flatpak, "#!/bin/sh\nexit 7\n").unwrap();
        fs::set_permissions(&flatpak, fs::Permissions::from_mode(0o755)).unwrap();
        service.operations.use_ludusavi_test_command(flatpak);
        service
            .update_settings(
                json!({"kind":"auto_sync","enabled":true})
                    .as_object()
                    .unwrap(),
            )
            .unwrap();
        let _operation = service.operations.hold_operation_lock_for_test();

        assert_eq!(
            service.check_game_start("Hades", None).unwrap(),
            json!({"status":"skipped","game":"Hades","reason":"operation_running"})
        );
    }

    #[test]
    fn history_validation_drops_invalid_entries_and_derives_latest() {
        let valid = json!({"operation":"backup","trigger":"manual_backup","status":"backed_up","timestamp":"2026-01-01T00:00:00Z","reason":4});
        assert_eq!(
            super::valid_history_entry(&valid).unwrap()["reason"],
            Value::Null
        );
        for invalid in [
            json!(null),
            json!({"operation":"unknown","trigger":"manual_backup","status":"backed_up","timestamp":"x"}),
            json!({"operation":"backup","trigger":"unknown","status":"backed_up","timestamp":"x"}),
            json!({"operation":"backup","trigger":"manual_backup","status":"unknown","timestamp":"x"}),
            json!({"operation":"backup","trigger":"manual_backup","status":"backed_up","timestamp":1}),
        ] {
            assert!(super::valid_history_entry(&invalid).is_none(), "{invalid}");
        }
        let history = super::normalize_history(Some(&json!({
            "Hades": {
                "last_backup": {"operation":"backup","trigger":"manual_backup","status":"backed_up","timestamp":"2026-01-01T00:00:00Z"},
                "last_failure": {"operation":"restore","trigger":"manual_restore","status":"failed","timestamp":"2026-01-02T00:00:00Z"}
            },
            "Broken": "not a map"
        })));
        assert_eq!(history["Hades"]["last_operation"]["status"], "failed");
        assert!(history.get("Broken").is_none());
    }

    #[test]
    fn recent_logs_keep_the_newest_hundred_entries() {
        let (_directory, service) = test_service();
        for index in 0..105 {
            service.log("info", &format!("ring-{index}"), Some("frontend"), None);
        }
        let Value::Array(logs) = service.get_recent_logs() else {
            panic!("recent logs must be an array");
        };
        assert_eq!(logs.len(), LOG_LIMIT);
        assert_eq!(logs[0]["message"], "ring-5");
        assert_eq!(logs[99]["message"], "ring-104");
    }
    #[test]
    fn empty_game_sync_patch_does_not_write_or_log() {
        let (_directory, service) = test_service();
        let logs_before = service.get_recent_logs();
        let patch = json!({
            "kind": "game_sync",
            "game_name": "",
            "enabled": "invalid",
        });
        let settings = service.update_settings(patch.as_object().unwrap()).unwrap();

        assert_eq!(settings["sync_disabled_games"], json!([]));
        assert!(!service.settings_path.exists());
        assert_eq!(service.get_recent_logs(), logs_before);
    }

    #[test]
    fn update_settings_keeps_last_good_snapshot_after_read_failure() {
        let (_directory, service) = test_service();
        service
            .update_settings(
                json!({"kind": "selected_game", "game_name": "Keep this setting"})
                    .as_object()
                    .unwrap(),
            )
            .unwrap();

        fs::write(&service.settings_path, b"{ invalid json").unwrap();
        let updated = service
            .update_settings(
                json!({"kind": "auto_sync", "enabled": true})
                    .as_object()
                    .unwrap(),
            )
            .unwrap();

        assert_eq!(updated["selected_game"], "Keep this setting");
        let persisted: Value =
            serde_json::from_slice(&fs::read(&service.settings_path).unwrap()).unwrap();
        assert_eq!(persisted["selected_game"], "Keep this setting");
    }

    #[test]
    fn set_shortcut_id_does_not_replace_unreadable_cache() {
        let (_directory, service) = test_service();
        service.set_shortcut_id(123).unwrap();
        fs::write(&service.cache_path, b"{ invalid json").unwrap();

        let unreadable_cache = fs::read(&service.cache_path).unwrap();
        assert!(service.set_shortcut_id(456).is_err());
        assert_eq!(fs::read(&service.cache_path).unwrap(), unreadable_cache);
    }

    #[tokio::test]
    async fn dispatcher_errors_use_python_getter_fallbacks() {
        let (_directory, service) = test_service();
        assert_eq!(
            service.dispatch("get_recent_logs", vec![Value::Null]).await,
            json!([])
        );
        assert_eq!(
            service
                .dispatch("get_operation_status", vec![Value::Null])
                .await,
            json!({
                "is_running": false,
                "name": null,
                "game_name": null,
                "last_result": null,
                "last_error": null,
            })
        );
        assert_eq!(
            service
                .dispatch("get_ludusavi_launcher_shortcut_id", vec![Value::Null])
                .await,
            json!(-1)
        );
        assert_eq!(service.dispatch("log", Vec::new()).await, Value::Null);
        assert_eq!(
            BackendService::unavailable_reply("get_recent_logs"),
            json!([])
        );
        assert_eq!(
            BackendService::unavailable_reply("get_operation_status"),
            json!({
                "is_running": false,
                "name": null,
                "game_name": null,
                "last_result": null,
                "last_error": null,
            })
        );
        assert_eq!(
            BackendService::unavailable_reply("get_ludusavi_launcher_shortcut_id"),
            json!(-1)
        );
        assert_eq!(BackendService::unavailable_reply("log"), Value::Null);
    }

    #[tokio::test]
    async fn unloading_uses_python_getter_fallbacks() {
        let (_directory, service) = test_service();
        assert!(service.shutdown().await);
        assert_eq!(
            service.dispatch("get_recent_logs", Vec::new()).await,
            json!([])
        );
        assert_eq!(
            service.dispatch("get_operation_status", Vec::new()).await,
            super::idle_operation_status()
        );
        assert_eq!(
            service
                .dispatch("get_ludusavi_launcher_shortcut_id", Vec::new())
                .await,
            json!(-1)
        );
        assert_eq!(service.dispatch("log", Vec::new()).await, Value::Null);
    }

    #[tokio::test]
    async fn admission_rejects_calls_after_shutdown_begins() {
        let (_directory, service) = test_service();
        assert!(service.shutdown().await);
        assert_eq!(
            service.dispatch("get_settings", Vec::new()).await,
            json!({
                "status": "skipped",
                "reason": "unloading",
                "message": "Plugin unload is in progress.",
            })
        );
    }

    #[tokio::test]
    async fn shutdown_waits_for_tracked_calls() {
        let tracker = Arc::new(super::CallTracker::default());
        let call = tracker.enter().unwrap();
        tracker.stop_admission();
        assert!(tracker.enter().is_none());
        let waiting = tokio::spawn({
            let tracker = Arc::clone(&tracker);
            async move {
                tracker
                    .wait_for_drain_until(tokio::time::Instant::now() + Duration::from_secs(1))
                    .await
            }
        });
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert!(!waiting.is_finished());
        drop(call);
        assert!(waiting.await.unwrap());
    }
    #[tokio::test]
    async fn shutdown_keeps_the_tokio_runtime_responsive_during_watchdog_cleanup() {
        let (_directory, service) = test_service();
        let barrier = Arc::new(Barrier::new(2));
        let hook_barrier = Arc::clone(&barrier);
        service.watchdog.set_stop_hook(Arc::new(move || {
            hook_barrier.wait();
        }));
        let release_barrier = Arc::clone(&barrier);
        let releaser = thread::spawn(move || {
            thread::sleep(Duration::from_millis(150));
            release_barrier.wait();
        });
        let started = Instant::now();
        let (shutdown_ok, heartbeat_elapsed) = tokio::join!(service.shutdown(), async {
            tokio::time::sleep(Duration::from_millis(10)).await;
            started.elapsed()
        });
        releaser.join().unwrap();
        assert!(shutdown_ok);
        assert!(
            heartbeat_elapsed < Duration::from_millis(100),
            "watchdog cleanup blocked the async runtime for {heartbeat_elapsed:?}"
        );
    }
    #[tokio::test]
    async fn shutdown_deadline_reports_retained_gates_without_blocking_runtime() {
        let (_directory, service) = test_service();
        let barrier = Arc::new(Barrier::new(2));
        let hook_barrier = Arc::clone(&barrier);
        service.watchdog.set_stop_hook(Arc::new(move || {
            hook_barrier.wait();
        }));
        let release_barrier = Arc::clone(&barrier);
        let releaser = thread::spawn(move || {
            thread::sleep(Duration::from_millis(150));
            release_barrier.wait();
        });
        let started = Instant::now();
        let deadline = started + Duration::from_millis(30);
        let (shutdown_ok, heartbeat_elapsed) =
            tokio::join!(service.shutdown_until(deadline), async {
                tokio::time::sleep(Duration::from_millis(10)).await;
                started.elapsed()
            });
        releaser.join().unwrap();
        assert!(!shutdown_ok);
        assert!(
            heartbeat_elapsed < Duration::from_millis(100),
            "shutdown deadline blocked the async runtime for {heartbeat_elapsed:?}"
        );
        assert!(
            service
                .get_recent_logs()
                .to_string()
                .contains("retained_gate=true"),
            "shutdown deadline was not reported as retaining launch gates"
        );
    }
}
