use std::{
    collections::{BTreeSet, VecDeque},
    io,
    path::{Path, PathBuf},
    sync::{
        Arc, LazyLock, Mutex,
        atomic::{AtomicBool, AtomicI64, Ordering},
    },
    time::Duration,
};

use decky_plugin::Env;
use serde_json::{Map, Value, json};
use time::{OffsetDateTime, format_description, format_description::well_known::Rfc3339};
use tokio::sync::Notify;

use crate::persistence::{
    StateLock, ensure_private_directory, existing_mode, read_object, write_json_atomic,
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
    state_lock: StateLock,
    settings: Mutex<Map<String, Value>>,
    shortcut_id: AtomicI64,
    history: Value,
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
        let state_lock = StateLock::new(&cache_path)?;
        let loaded =
            state_lock.with_lock(|| Ok((read_object(&settings_path), read_object(&cache_path))));
        let (settings, cache) = match loaded {
            Ok(state) => state,
            Err(error) => {
                log::warn!("Failed to acquire state lock during startup: {error}");
                (Map::new(), Map::new())
            }
        };
        let debug_logging = setting_bool(&settings, "debug_logging", true);
        let history = normalize_history(cache.get("game_history"));
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
            history,
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
            return unloading_reply();
        };
        let service = Arc::clone(self);
        match tokio::task::spawn_blocking(move || {
            let _call = call;
            service.invoke(method, &args)
        })
        .await
        {
            Ok(Ok(result)) => result,
            Ok(Err(message)) => failed_reply(message),
            Err(error) => failed_reply(format!("{method} failed: {error}")),
        }
    }

    pub async fn shutdown(&self) -> bool {
        self.calls.stop_and_wait(DRAIN_BUDGET).await
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
                Ok(json!({
                    "is_running": false,
                    "name": null,
                    "game_name": null,
                    "last_result": null,
                    "last_error": null,
                }))
            }
            "get_game_history" => {
                expect_args(method, args, 0)?;
                Ok(self.history.clone())
            }
            _ => Err(format!("Plugin has no method {method}")),
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
                let mut settings = read_object(&self.settings_path);
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
                let mut cache = read_object(&self.cache_path);
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

fn unloading_reply() -> Value {
    json!({
        "status": "skipped",
        "reason": "unloading",
        "message": "Plugin unload is in progress.",
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

    async fn stop_and_wait(&self, budget: Duration) -> bool {
        {
            let mut state = lock(&self.state);
            state.stopping = true;
        }
        let deadline = tokio::time::Instant::now() + budget;
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
    use std::{sync::Arc, time::Duration};

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
        let waiting = tokio::spawn({
            let tracker = Arc::clone(&tracker);
            async move { tracker.stop_and_wait(Duration::from_secs(1)).await }
        });
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert!(!waiting.is_finished());
        drop(call);
        assert!(waiting.await.unwrap());
    }
}
