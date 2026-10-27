use std::{
    collections::{BTreeMap, BTreeSet},
    env, fs,
    io::{self, Read},
    os::unix::{ffi::OsStrExt, process::CommandExt},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        Arc, Mutex, MutexGuard,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant, SystemTime},
};

use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use time::{OffsetDateTime, format_description::well_known::Rfc3339};
use unicode_casefold::UnicodeCaseFold;

use crate::{
    lifecycle::{RestorePreview, classify_restore_change},
    persistence::{StateLock, read_object, write_json_atomic},
};

const FLATPAK_ID: &str = "com.github.mtkennerly.ludusavi";
const DISCOVERY_TIMEOUT: Duration = Duration::from_secs(15);
const DEPLOYMENT_TIMEOUT: Duration = Duration::from_secs(1);
const OPERATION_TIMEOUT: Duration = Duration::from_secs(180);
const BACKUPS_TIMEOUT: Duration = Duration::from_secs(30);
const TERMINATE_GRACE: Duration = Duration::from_millis(200);
const KILL_CONFIRM_TIMEOUT: Duration = Duration::from_secs(2);
const MAX_INSTALLED_APP_IDS_BYTES: usize = 16_384;
const MAX_BACKUP_STAT_ENTRIES: usize = 1_000;
const OPERATION_CANCELLED: &str = "Ludusavi operation cancelled";
type GuardedMutation =
    Box<dyn FnOnce(Arc<AtomicBool>, &mut ProcessGroupCompletion) -> Result<Value, String>>;
type ProcessOutputReader = thread::JoinHandle<io::Result<Vec<u8>>>;
type ProcessReaders = (Option<ProcessOutputReader>, Option<ProcessOutputReader>);
#[cfg(test)]
type AfterTrackHook = Box<dyn FnOnce(i32) + Send>;

#[derive(Clone, Debug)]
struct Game {
    name: String,
    configured: bool,
    has_backup: bool,
    needs_first_backup: bool,
    steam_id: Option<String>,
    error: Option<String>,
}

impl Game {
    fn from_cache(value: &Value) -> Option<Self> {
        Some(Self {
            name: value.get("name")?.as_str()?.to_owned(),
            configured: value
                .get("configured")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            has_backup: value
                .get("has_backup")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            needs_first_backup: value
                .get("needs_first_backup")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            steam_id: value
                .get("steam_id")
                .and_then(Value::as_str)
                .map(str::to_owned),
            error: value
                .get("error")
                .and_then(Value::as_str)
                .map(str::to_owned),
        })
    }

    fn status(&self) -> &'static str {
        if self.error.as_ref().is_some_and(|error| !error.is_empty()) {
            "error"
        } else if self.has_backup {
            "has_backup"
        } else if self.needs_first_backup {
            "needs_first_backup"
        } else if self.configured {
            "configured"
        } else {
            "error"
        }
    }

    fn to_value(&self) -> Value {
        json!({
            "name": self.name,
            "configured": self.configured,
            "has_backup": self.has_backup,
            "needs_first_backup": self.needs_first_backup,
            "steam_id": self.steam_id,
            "error": self.error,
            "status": self.status(),
        })
    }
}

#[derive(Default)]
struct Registry {
    games: BTreeMap<String, Game>,
    aliases: BTreeMap<String, String>,
    aliases_marker: Option<i64>,
    ids: BTreeMap<String, String>,
    installed_app_ids: Option<String>,
    config_marker: Option<i64>,
}

impl Registry {
    fn load(cache: &Map<String, Value>) -> Self {
        let mut registry = Self::default();
        if let Some(games) = cache.get("games").and_then(Value::as_array) {
            for value in games {
                if let Some(game) = Game::from_cache(value) {
                    registry.games.insert(game.name.clone(), game);
                }
            }
        }
        if let Some(aliases) = cache.get("aliases").and_then(Value::as_object) {
            registry.aliases = aliases
                .iter()
                .filter_map(|(key, value)| {
                    value.as_str().map(|value| (key.clone(), value.to_owned()))
                })
                .collect();
        }
        if let Some(ids) = cache.get("ids").and_then(Value::as_object) {
            registry.ids = ids
                .iter()
                .filter_map(|(key, value)| {
                    value.as_str().map(|value| (key.clone(), value.to_owned()))
                })
                .collect();
        }
        registry.installed_app_ids = cache
            .get("installed_app_ids")
            .and_then(Value::as_str)
            .map(str::to_owned);
        registry.config_marker = cache
            .get("ludusavi_config_mtime_ns")
            .and_then(Value::as_i64);
        registry
    }

    fn cache_payload(&self) -> Map<String, Value> {
        Map::from_iter([
            (
                "games".to_owned(),
                Value::Array(self.games.values().map(Game::to_value).collect()),
            ),
            ("aliases".to_owned(), json!(self.aliases)),
            ("ids".to_owned(), json!(self.ids)),
            (
                "installed_app_ids".to_owned(),
                self.installed_app_ids
                    .clone()
                    .map_or(Value::Null, Value::String),
            ),
            (
                "ludusavi_config_mtime_ns".to_owned(),
                self.config_marker.map_or(Value::Null, Value::from),
            ),
        ])
    }

    fn is_current(
        &self,
        target_ids: Option<&str>,
        target_marker: Option<i64>,
        marker_failed: bool,
    ) -> bool {
        !self.games.is_empty()
            && target_ids.is_none_or(|ids| self.installed_app_ids.as_deref() == Some(ids))
            && !marker_failed
            && self.config_marker == target_marker
    }

    fn matching_game(&self, name: &str, app_id: Option<&str>) -> Option<Game> {
        if let Some(target) = app_id.and_then(|id| self.ids.get(id))
            && let Some(game) = self.games.get(target)
        {
            return Some(game.clone());
        }
        if let Some(target) = self.aliases.get(name)
            && let Some(game) = self.games.get(target)
        {
            return Some(game.clone());
        }
        let normalized = normalize_game_name(name);
        if let Some(game) = self
            .games
            .values()
            .find(|game| normalize_game_name(&game.name) == normalized)
        {
            return Some(game.clone());
        }
        let candidates: Vec<_> = self
            .games
            .values()
            .filter(|game| {
                let target = normalize_game_name(&game.name);
                (target.contains(&normalized) || normalized.contains(&target))
                    && fuzzy_match_allowed(&normalized, &target, game.configured)
            })
            .collect();
        (candidates.len() == 1).then(|| candidates[0].clone())
    }
}

#[derive(Default)]
struct OperationStatus {
    running: bool,
    name: Option<String>,
    game_name: Option<String>,
    last_result: Option<String>,
    last_error: Option<String>,
}

impl OperationStatus {
    fn to_value(&self) -> Value {
        json!({
            "is_running": self.running,
            "name": self.name,
            "game_name": self.game_name,
            "last_result": self.last_result,
            "last_error": self.last_error,
        })
    }
}

pub struct LudusaviOperations {
    cache_path: PathBuf,
    state_lock: Arc<StateLock>,
    registry: Mutex<Registry>,
    history: Mutex<Value>,
    client: Mutex<Option<Arc<LudusaviClient>>>,
    processes: Arc<ProcessManager>,
    operation_lock: Mutex<()>,
    status: Mutex<OperationStatus>,
}

impl LudusaviOperations {
    pub fn new(
        cache_path: PathBuf,
        state_lock: Arc<StateLock>,
        cache: &Map<String, Value>,
        history: Value,
    ) -> Self {
        Self {
            cache_path,
            state_lock,
            registry: Mutex::new(Registry::load(cache)),
            history: Mutex::new(history),
            client: Mutex::new(None),
            processes: Arc::new(ProcessManager::default()),
            operation_lock: Mutex::new(()),
            status: Mutex::new(OperationStatus::default()),
        }
    }

    pub fn cancel_processes(&self) {
        self.processes.cancel_all();
    }
    #[cfg(test)]
    pub(crate) fn prepare_cancelled_list_backups_test(&self, include_game: bool) {
        if include_game {
            lock(&self.registry).games.insert(
                "Hades".to_owned(),
                Game {
                    name: "Hades".to_owned(),
                    configured: true,
                    has_backup: true,
                    needs_first_backup: false,
                    steam_id: None,
                    error: None,
                },
            );
        }
        *lock(&self.client) = Some(Arc::new(LudusaviClient {
            processes: Arc::clone(&self.processes),
            flatpak: PathBuf::new(),
            config_path: Mutex::new(None),
            deployment: None,
            execution_failed: AtomicBool::new(false),
            version: Mutex::new(None),
        }));
        self.cancel_processes();
    }
    #[cfg(test)]
    pub(crate) fn use_ludusavi_test_command(&self, flatpak: PathBuf) {
        *lock(&self.client) = Some(Arc::new(LudusaviClient {
            processes: Arc::clone(&self.processes),
            flatpak,
            config_path: Mutex::new(None),
            deployment: None,
            execution_failed: AtomicBool::new(false),
            version: Mutex::new(None),
        }));
    }
    #[cfg(test)]
    pub(crate) fn hold_operation_lock_for_test(&self) -> std::sync::MutexGuard<'_, ()> {
        lock(&self.operation_lock)
    }

    pub fn processes_exited(&self) -> bool {
        self.processes.groups_exited()
    }

    pub fn get_operation_status(&self) -> Value {
        lock(&self.status).to_value()
    }

    pub fn get_game_history(&self) -> Value {
        lock(&self.history).clone()
    }
    pub(crate) fn matching_lifecycle_game(
        &self,
        name: &str,
        app_id: Option<&str>,
    ) -> Result<Option<Value>, OperationError> {
        self.ensure_registry()?;
        Ok(lock(&self.registry)
            .matching_game(name, app_id)
            .map(|game| game.to_value()))
    }

    pub(crate) fn start_recency(&self, name: &str) -> Result<Value, OperationError> {
        self.run_operation_wait("start_check", Some(name), Duration::from_secs(30), || {
            let client = self.client()?;
            let backups = game_objects(&client.backups(Some(name))?)?;
            let recency = if backups
                .get(name)
                .and_then(|game| game.get("backups"))
                .and_then(Value::as_array)
                .is_none_or(Vec::is_empty)
            {
                "no_backup"
            } else {
                let preview = client.restore(name, true).ok();
                let change = preview
                    .as_ref()
                    .and_then(|value| {
                        value.pointer(&format!("/games/{}/change", escape_pointer(name)))
                    })
                    .and_then(Value::as_str);
                match classify_restore_change(change) {
                    RestorePreview::LocalCurrent => "local_current",
                    RestorePreview::BackupNewer => "backup_newer",
                    RestorePreview::BackupDiffers => "backup_differs",
                    RestorePreview::Ambiguous => "ambiguous",
                }
            };
            let metadata = if matches!(recency, "backup_newer" | "local_current") {
                json!({})
            } else {
                conflict_metadata(&client, name)
            };
            Ok(json!({"recency":recency, "metadata":metadata}))
        })
    }

    pub(crate) fn exit_preview(&self, name: &str) -> Result<Value, OperationError> {
        self.run_operation_wait("exit_check", Some(name), Duration::from_secs(30), || {
            self.client()?.backup_preview(Some(name))
        })
    }

    pub(crate) fn start_mutation(
        &self,
        name: &str,
        restore: bool,
        guard: impl FnOnce(GuardedMutation) -> Result<Value, String>,
    ) -> Result<Value, OperationError> {
        let operation = if restore { "restore" } else { "backup" };
        let game = name.to_owned();
        self.run_operation(operation, Some(name), || {
            let client = self.client()?;
            let mutation: GuardedMutation = Box::new(move |cancel, completion| {
                if restore {
                    client.restore_cancellable(&game, cancel, completion)
                } else {
                    client.backup_cancellable(&game, cancel, completion)
                }
            });
            guard(mutation)
        })
    }

    pub(crate) fn backup_on_exit(&self, name: &str) -> Result<Value, OperationError> {
        self.run_operation("backup", Some(name), || self.client()?.backup(name, false))
    }

    pub fn refresh_after_lifecycle(&self, name: &str) {
        let _ = self.refresh_targeted(name);
    }

    pub fn record_lifecycle_history(
        &self,
        game: &str,
        operation: &str,
        trigger: &str,
        status: &str,
        reason: Option<&str>,
        message: Option<&str>,
    ) -> Result<(), String> {
        self.record_history(game, operation, trigger, status, reason, message)
    }

    pub fn get_versions(&self) -> Result<Value, String> {
        let client = self.client()?;
        let ludusavi = client.version()?;
        let normalized = ludusavi.to_lowercase();
        let normalized = normalized
            .strip_prefix("ludusavi")
            .unwrap_or(&normalized)
            .trim()
            .to_owned();
        let mut versions = Map::new();
        versions.insert("ludusavi".to_owned(), Value::String(normalized));
        versions.insert(
            "sdh_ludusavi".to_owned(),
            Value::String(
                env::var("DECKY_PLUGIN_VERSION")
                    .unwrap_or_else(|_| env!("CARGO_PKG_VERSION").to_owned()),
            ),
        );
        versions.insert(
            "decky".to_owned(),
            Value::String(env::var("DECKY_VERSION").unwrap_or_else(|_| "unknown".to_owned())),
        );
        Ok(Value::Object(versions))
    }
    pub fn get_backup_path(&self) -> Result<Option<String>, String> {
        let output = self
            .client()?
            .json(&["config".to_owned(), "show".to_owned()], BACKUPS_TIMEOUT)?;
        Ok(output
            .pointer("/backup/path")
            .and_then(Value::as_str)
            .filter(|path| !path.trim().is_empty() && *path != "unknown")
            .map(str::to_owned))
    }

    pub fn get_ludusavi_command(&self) -> Value {
        match self.client() {
            Ok(_) => json!({
                "commandPath": "flatpak",
                "args": ["run", FLATPAK_ID],
                "compatTool": "",
            }),
            Err(_) => Value::Null,
        }
    }

    pub fn get_ludusavi_logs(&self) -> Result<Value, String> {
        Ok(Value::String(self.client()?.logs()?))
    }

    pub fn is_game_cache_current(&self, app_ids: Option<&str>) -> bool {
        let Some(target_ids) = normalize_installed_app_ids(app_ids) else {
            return false;
        };
        let target_marker = self.config_marker();
        let marker_failed = target_marker.is_err();
        lock(&self.registry).is_current(target_ids.as_deref(), target_marker.ok(), marker_failed)
    }

    pub fn refresh_games(&self, force: bool, app_ids: Option<&str>) -> Value {
        let normalized_ids = normalize_installed_app_ids(app_ids);
        let marker = self.config_marker();
        let (target_marker, marker_failed) = match marker {
            Ok(marker) => (Some(marker), false),
            Err(_) => (None, true),
        };
        let needs_refresh = {
            let registry = lock(&self.registry);
            force
                || registry.games.is_empty()
                || normalized_ids
                    .as_ref()
                    .and_then(Option::as_ref)
                    .is_some_and(|ids| registry.installed_app_ids.as_deref() != Some(ids))
                || marker_failed
                || registry.config_marker != target_marker
        };
        if !needs_refresh {
            return self.refresh_result(None);
        }
        if force {
            let mut client = lock(&self.client);
            if let Some(existing) = client.as_ref()
                && !existing.execution_failed.load(Ordering::Acquire)
                && existing.deployment.is_some()
                && find_flatpak().as_ref() == Some(&existing.flatpak)
                && existing.deployment == deployment_location(&self.processes, &existing.flatpak)
            {
                *lock(&existing.config_path) = None;
            } else {
                *client = None;
            }
        }
        let result = self.run_operation("refresh", None, || {
            self.refresh_statuses(normalized_ids.clone().unwrap_or(None), target_marker)
        });
        match result {
            Ok(_) => self.refresh_result(None),
            Err(OperationError::Locked(message)) => self.refresh_result(Some(message)),
            Err(OperationError::Failed(message)) => self.refresh_result(Some(message)),
            Err(OperationError::Cancelled) => {
                self.refresh_result(Some(OPERATION_CANCELLED.to_owned()))
            }
        }
    }

    pub fn force_backup(&self, name: &str) -> Result<Value, String> {
        self.force_operation(name, false, None)
    }

    pub fn force_restore(&self, name: &str) -> Result<Value, String> {
        self.force_operation(name, true, None)
    }

    pub fn restore_backup_version(&self, name: &str, backup_id: &str) -> Result<Value, String> {
        if backup_id.is_empty()
            || backup_id.contains('/')
            || backup_id.contains('\\')
            || backup_id.contains("..")
        {
            return Err(format!("Invalid backup ID: {backup_id}"));
        }
        self.force_operation(name, true, Some(backup_id))
    }

    fn ensure_registry(&self) -> Result<(), OperationError> {
        if lock(&self.registry).games.is_empty() {
            let marker = self.config_marker().ok();
            self.run_operation("refresh", None, || self.refresh_statuses(None, marker))?;
        }
        Ok(())
    }

    fn force_operation(
        &self,
        name: &str,
        restore: bool,
        backup_id: Option<&str>,
    ) -> Result<Value, String> {
        let name = sanitize_game_name(name);
        if let Err(error) = self.ensure_registry() {
            return match error {
                OperationError::Locked(message) => Ok(json!({
                    "status":"skipped",
                    "reason":"operation_running",
                    "message":message,
                })),
                OperationError::Failed(message) => Err(message),
                OperationError::Cancelled => Ok(json!({
                    "status":"skipped",
                    "reason":"cancelled",
                    "game":name,
                })),
            };
        }
        let Some(game) = lock(&self.registry).matching_game(&name, None) else {
            return Ok(skip_result(&name, "unmatched_game"));
        };
        if restore && !game.has_backup {
            self.record_history(
                &game.name,
                "restore",
                "manual_restore",
                "skipped",
                Some("no_backup"),
                None,
            )?;
            return Ok(skip_result(&game.name, "no_backup"));
        }
        let operation = if restore { "restore" } else { "backup" };
        let trigger = if restore {
            "manual_restore"
        } else {
            "manual_backup"
        };
        let command_result = self.run_operation(operation, Some(&game.name), || {
            let client = self.client()?;
            if restore {
                if let Some(backup_id) = backup_id {
                    client.restore_backup(&game.name, backup_id)
                } else {
                    client.restore(&game.name, false)
                }
            } else {
                client.backup(&game.name, false)
            }
        });
        let result = match command_result {
            Ok(result) => result,
            Err(OperationError::Locked(message)) => {
                return Ok(
                    json!({"status":"skipped", "reason":"operation_running", "message":message}),
                );
            }
            Err(OperationError::Cancelled) => {
                self.record_history(
                    &game.name,
                    operation,
                    trigger,
                    "skipped",
                    Some("cancelled"),
                    None,
                )?;
                return Ok(json!({
                    "status":"skipped",
                    "reason":"cancelled",
                    "game":game.name,
                }));
            }
            Err(OperationError::Failed(message)) => {
                self.record_history(
                    &game.name,
                    operation,
                    trigger,
                    "failed",
                    None,
                    Some(&message),
                )?;
                return Err(message);
            }
        };
        let same = result
            .pointer(&format!("/games/{}/change", escape_pointer(&game.name)))
            .and_then(Value::as_str)
            == Some("Same");
        if same {
            self.record_history(
                &game.name,
                operation,
                trigger,
                "skipped",
                Some("local_current"),
                None,
            )?;
        } else {
            self.record_history(
                &game.name,
                operation,
                trigger,
                if restore { "restored" } else { "backed_up" },
                None,
                None,
            )?;
        }
        let _ = self.refresh_targeted(&game.name);
        if same {
            let mut response = json!({"status":"skipped", "reason":"local_current", "game":game.name, "result":result});
            if let Some(backup_id) = backup_id {
                response["backup_id"] = Value::String(backup_id.to_owned());
            }
            return Ok(response);
        }
        let mut response = json!({
            "status": if restore { "restored" } else { "backed_up" },
            "game": game.name,
            "result": result,
        });
        if let Some(backup_id) = backup_id {
            response["backup_id"] = Value::String(backup_id.to_owned());
        }
        Ok(response)
    }

    pub fn list_backups(&self, name: &str) -> Result<Value, String> {
        let name = sanitize_game_name(name);
        if let Err(error) = self.ensure_registry() {
            return match error {
                OperationError::Locked(message) => Ok(json!({
                    "status":"skipped",
                    "reason":"operation_running",
                    "message":message,
                })),
                OperationError::Failed(message) => Err(message),
                OperationError::Cancelled => Ok(json!({"status":"skipped","reason":"cancelled"})),
            };
        }
        let Some(game) = lock(&self.registry).matching_game(&name, None) else {
            return Ok(skip_result(&name, "unmatched_game"));
        };
        match self.run_operation("backups_list", Some(&game.name), || {
            self.client()?.list_backups(&game.name)
        }) {
            Ok(result) => Ok(result),
            Err(OperationError::Locked(message)) => Ok(json!({
                "status":"skipped",
                "reason":"operation_running",
                "message":message,
            })),
            Err(OperationError::Failed(message)) => Err(message),
            Err(OperationError::Cancelled) => Ok(json!({"status":"skipped","reason":"cancelled"})),
        }
    }

    fn run_operation<T>(
        &self,
        name: &str,
        game_name: Option<&str>,
        operation: impl FnOnce() -> Result<T, String>,
    ) -> Result<T, OperationError> {
        self.run_operation_inner(name, game_name, None, operation)
    }

    fn run_operation_wait<T>(
        &self,
        name: &str,
        game_name: Option<&str>,
        timeout: Duration,
        operation: impl FnOnce() -> Result<T, String>,
    ) -> Result<T, OperationError> {
        self.run_operation_inner(name, game_name, Some(timeout), operation)
    }

    fn run_operation_inner<T>(
        &self,
        name: &str,
        game_name: Option<&str>,
        wait_timeout: Option<Duration>,
        operation: impl FnOnce() -> Result<T, String>,
    ) -> Result<T, OperationError> {
        let deadline = wait_timeout.map(|timeout| Instant::now() + timeout);
        let guard = loop {
            match self.operation_lock.try_lock() {
                Ok(guard) => break guard,
                Err(std::sync::TryLockError::Poisoned(error)) => break error.into_inner(),
                Err(std::sync::TryLockError::WouldBlock) => {
                    let current = lock(&self.status)
                        .name
                        .clone()
                        .unwrap_or_else(|| "operation".to_owned());
                    let Some(deadline) = deadline else {
                        return Err(OperationError::Locked(format!(
                            "{current} is already running"
                        )));
                    };
                    let now = Instant::now();
                    if now >= deadline {
                        return Err(OperationError::Locked(format!(
                            "{current} is already running"
                        )));
                    }
                    thread::sleep(Duration::from_millis(10).min(deadline - now));
                }
            }
        };
        {
            let mut status = lock(&self.status);
            status.running = true;
            status.name = Some(name.to_owned());
            status.game_name = game_name.map(str::to_owned);
            status.last_error = None;
        }
        let result = operation();
        {
            let mut status = lock(&self.status);
            status.running = false;
            status.name = None;
            status.game_name = None;
            match &result {
                Ok(_) => status.last_result = Some("ok".to_owned()),
                Err(message) if message == OPERATION_CANCELLED => {
                    status.last_result = Some("cancelled".to_owned())
                }
                Err(message) => {
                    status.last_result = Some("failed".to_owned());
                    status.last_error = Some(message.clone());
                }
            }
        }
        drop(guard);
        result.map_err(|message| {
            if message == OPERATION_CANCELLED {
                OperationError::Cancelled
            } else {
                OperationError::Failed(message)
            }
        })
    }

    fn refresh_statuses(
        &self,
        installed_ids: Option<String>,
        marker: Option<i64>,
    ) -> Result<(), String> {
        let client = self.client()?;
        let (preview, backups) = thread::scope(|scope| {
            let preview = scope.spawn(|| client.backup_preview(None));
            let backups = scope.spawn(|| client.backups(None));
            (preview.join(), backups.join())
        });
        let preview = preview.map_err(|_| "Ludusavi preview worker panicked".to_owned())??;
        let backups = backups.map_err(|_| "Ludusavi backups worker panicked".to_owned())??;
        let preview_games = game_objects(&preview)?;
        let backup_games = game_objects(&backups)?;
        let mut games = Vec::new();
        for (name, output) in preview_games {
            let files = output.get("files").and_then(Value::as_object);
            let registry = output.get("registry").and_then(Value::as_object);
            if !files.is_some_and(|value| !value.is_empty())
                && !registry.is_some_and(|value| !value.is_empty())
            {
                continue;
            }
            if matches!(
                output.get("decision").and_then(Value::as_str),
                Some("Ignored" | "Cancelled")
            ) {
                continue;
            }
            let has_backup = backup_games
                .get(&name)
                .and_then(|game| game.get("backups"))
                .and_then(Value::as_array)
                .is_some_and(|backups| !backups.is_empty());
            let steam_id = output.get("steamId").and_then(|value| match value {
                Value::String(value) => Some(value.clone()),
                Value::Number(value) => Some(value.to_string()),
                _ => None,
            });
            games.push(Game {
                name,
                configured: true,
                has_backup,
                needs_first_backup: !has_backup,
                steam_id,
                error: game_error(&output),
            });
        }
        let reload_aliases = marker.is_none() || lock(&self.registry).aliases_marker != marker;
        let aliases = reload_aliases.then(|| client.aliases());
        {
            let mut registry = lock(&self.registry);
            registry.games = games
                .into_iter()
                .map(|game| (game.name.clone(), game))
                .collect();
            if let Some(aliases) = aliases {
                registry.aliases_marker = if aliases.is_ok() { marker } else { None };
                registry.aliases = aliases.unwrap_or_default();
            }
            registry.ids = registry
                .games
                .values()
                .filter_map(|game| {
                    game.steam_id
                        .as_ref()
                        .map(|id| (id.clone(), game.name.clone()))
                })
                .collect();
            registry.installed_app_ids = installed_ids;
            registry.config_marker = marker;
        }
        self.save_cache()
    }

    fn refresh_targeted(&self, name: &str) -> Result<(), String> {
        let client = self.client()?;
        let (preview, backups) = thread::scope(|scope| {
            let preview = scope.spawn(|| client.backup_preview(Some(name)));
            let backups = scope.spawn(|| client.backups(Some(name)));
            (preview.join(), backups.join())
        });
        let preview = preview.map_err(|_| "Ludusavi preview worker panicked".to_owned())??;
        let backups = backups.map_err(|_| "Ludusavi backups worker panicked".to_owned())??;
        let backup_games = game_objects(&backups)?;
        let Some((found_name, output)) = game_objects(&preview)?.into_iter().next() else {
            return Ok(());
        };
        let has_backup = backup_games
            .get(&found_name)
            .and_then(|game| game.get("backups"))
            .and_then(Value::as_array)
            .is_some_and(|backups| !backups.is_empty());
        let game = Game {
            name: found_name.clone(),
            configured: true,
            has_backup,
            needs_first_backup: !has_backup,
            steam_id: output.get("steamId").and_then(|value| match value {
                Value::String(value) => Some(value.clone()),
                Value::Number(value) => Some(value.to_string()),
                _ => None,
            }),
            error: game_error(&output),
        };
        {
            let mut registry = lock(&self.registry);
            let old_id = registry
                .games
                .get(&found_name)
                .and_then(|old| old.steam_id.clone());
            if let Some(old_id) = old_id {
                registry.ids.remove(&old_id);
            }
            if let Some(id) = &game.steam_id {
                registry.ids.insert(id.clone(), found_name.clone());
            }
            registry.games.insert(found_name, game);
        }
        self.save_cache()
    }

    fn refresh_result(&self, error: Option<String>) -> Value {
        let registry = lock(&self.registry);
        let mut games: Vec<_> = registry.games.values().collect();
        games.sort_by_cached_key(|game| game.name.case_fold().collect::<String>());
        json!({
            "games": games.into_iter().map(Game::to_value).collect::<Vec<_>>(),
            "aliases": registry.aliases,
            "history": self.get_game_history(),
            "dependency_error": error,
        })
    }

    fn config_marker(&self) -> Result<i64, String> {
        self.client()?.config_marker()
    }

    fn client(&self) -> Result<Arc<LudusaviClient>, String> {
        let mut client = lock(&self.client);
        if let Some(client) = client.as_ref()
            && !client.execution_failed.load(Ordering::Acquire)
        {
            return Ok(Arc::clone(client));
        }
        *client = None;
        let created = Arc::new(LudusaviClient::new(Arc::clone(&self.processes))?);
        *client = Some(Arc::clone(&created));
        Ok(created)
    }

    fn record_history(
        &self,
        game: &str,
        operation: &str,
        trigger: &str,
        status: &str,
        reason: Option<&str>,
        message: Option<&str>,
    ) -> Result<(), String> {
        let entry = json!({
            "operation": operation,
            "trigger": trigger,
            "status": status,
            "reason": reason,
            "message": message,
            "timestamp": OffsetDateTime::now_utc().format(&Rfc3339).unwrap_or_else(|_| "1970-01-01T00:00:00Z".to_owned()),
        });
        if valid_history_entry(&entry).is_none() {
            return Ok(());
        }
        {
            let mut history = lock(&self.history);
            let histories = history
                .as_object_mut()
                .ok_or_else(|| "History is not an object".to_owned())?;
            let game_history = histories.entry(game.to_owned()).or_insert_with(|| {
                json!({
                    "last_backup": null,
                    "last_restore": null,
                    "last_skip": null,
                    "last_failure": null,
                    "last_operation": null,
                })
            });
            let record = game_history
                .as_object_mut()
                .ok_or_else(|| "Game history is not an object".to_owned())?;
            let field = match status {
                "backed_up" => "last_backup",
                "restored" => "last_restore",
                "failed" => "last_failure",
                _ => "last_skip",
            };
            record.insert(field.to_owned(), entry);
            let latest = ["last_backup", "last_restore", "last_skip", "last_failure"]
                .iter()
                .filter_map(|field| record.get(*field))
                .filter_map(valid_history_entry)
                .filter(|entry| {
                    entry
                        .get("timestamp")
                        .and_then(Value::as_str)
                        .is_some_and(|value| !value.is_empty())
                })
                .max_by_key(|entry| {
                    entry
                        .get("timestamp")
                        .and_then(Value::as_str)
                        .and_then(parse_timestamp)
                        .unwrap_or(i128::MIN)
                });
            record.insert("last_operation".to_owned(), latest.unwrap_or(Value::Null));
        }
        self.save_cache()
    }

    fn save_cache(&self) -> Result<(), String> {
        self.state_lock
            .with_lock(|| {
                let registry = lock(&self.registry).cache_payload();
                let history = self.get_game_history();
                let mut cache = read_object(&self.cache_path)?.unwrap_or_default();
                for (key, value) in registry {
                    cache.insert(key, value);
                }
                cache.insert("game_history".to_owned(), history);
                write_json_atomic(&self.cache_path, &cache, 0o600, b"  ")
            })
            .map_err(|error| error.to_string())
    }
}

#[derive(Debug)]
pub(crate) enum OperationError {
    Locked(String),
    Failed(String),
    Cancelled,
}

struct LudusaviClient {
    processes: Arc<ProcessManager>,
    flatpak: PathBuf,
    deployment: Option<PathBuf>,
    execution_failed: AtomicBool,
    config_path: Mutex<Option<PathBuf>>,
    version: Mutex<Option<String>>,
}

impl LudusaviClient {
    fn new(processes: Arc<ProcessManager>) -> Result<Self, String> {
        let flatpak = find_flatpak()
            .ok_or_else(|| "Ludusavi Flatpak is not available to Decky".to_owned())?;
        let deployment = deployment_location(&processes, &flatpak);
        let version = processes.run_at(
            &flatpak,
            &[
                "run".to_owned(),
                FLATPAK_ID.to_owned(),
                "--version".to_owned(),
            ],
            DISCOVERY_TIMEOUT,
            false,
        )?;
        Ok(Self {
            processes,
            flatpak,
            deployment,
            execution_failed: AtomicBool::new(false),
            config_path: Mutex::new(None),
            version: Mutex::new(Some(version.trim().to_owned())),
        })
    }

    fn json(&self, args: &[String], timeout: Duration) -> Result<Value, String> {
        let mut completion = ProcessGroupCompletion::confirmed();
        let result = self.json_cancellable(args, timeout, None, &mut completion);
        completion.wait(Some(&self.processes.stopping));
        result
    }

    fn json_cancellable(
        &self,
        args: &[String],
        timeout: Duration,
        cancellation: Option<&AtomicBool>,
        completion: &mut ProcessGroupCompletion,
    ) -> Result<Value, String> {
        let mut args = args.to_vec();
        if !args.iter().any(|arg| arg == "--api") {
            args.push("--api".to_owned());
        }
        let arguments: Vec<_> = std::iter::once("run".to_owned())
            .chain(std::iter::once(FLATPAK_ID.to_owned()))
            .chain(args)
            .collect();
        self.processes
            .run_at_cancellable(
                &self.flatpak,
                &arguments,
                timeout,
                false,
                cancellation,
                completion,
            )
            .inspect_err(|message| self.note_failure(message))
            .and_then(|output| parse_ludusavi_json(&output))
    }

    fn text(&self, args: &[String], timeout: Duration) -> Result<String, String> {
        let arguments: Vec<_> = std::iter::once("run".to_owned())
            .chain(std::iter::once(FLATPAK_ID.to_owned()))
            .chain(args.iter().cloned())
            .collect();
        self.processes
            .run_at(&self.flatpak, &arguments, timeout, true)
            .inspect_err(|message| self.note_failure(message))
    }

    fn note_failure(&self, message: &str) {
        // Cancellation stops a healthy Ludusavi; only real failures force rediscovery.
        if message != OPERATION_CANCELLED {
            self.execution_failed.store(true, Ordering::Release);
        }
    }

    fn version(&self) -> Result<String, String> {
        let mut cached = lock(&self.version);
        if let Some(version) = cached.as_ref() {
            return Ok(version.clone());
        }
        let version = self
            .text(&["--version".to_owned()], BACKUPS_TIMEOUT)?
            .trim()
            .to_owned();
        *cached = Some(version.clone());
        Ok(version)
    }

    fn backup_preview(&self, game: Option<&str>) -> Result<Value, String> {
        let mut args = vec![
            "backup".to_owned(),
            "--preview".to_owned(),
            "--force".to_owned(),
        ];
        if let Some(game) = game {
            args.push(game.to_owned());
        }
        self.json(&args, OPERATION_TIMEOUT)
    }

    fn backups(&self, game: Option<&str>) -> Result<Value, String> {
        let mut args = vec!["backups".to_owned()];
        if let Some(game) = game {
            args.push(game.to_owned());
        }
        self.json(&args, BACKUPS_TIMEOUT)
    }

    fn backup(&self, game: &str, preview: bool) -> Result<Value, String> {
        let mut args = vec!["backup".to_owned()];
        if preview {
            args.push("--preview".to_owned());
        }
        args.extend(["--force".to_owned(), game.to_owned()]);
        self.json(&args, OPERATION_TIMEOUT)
    }

    fn restore(&self, game: &str, preview: bool) -> Result<Value, String> {
        let mut args = vec!["restore".to_owned()];
        if preview {
            args.push("--preview".to_owned());
        }
        args.extend(["--force".to_owned(), game.to_owned()]);
        self.json(&args, OPERATION_TIMEOUT)
    }
    fn backup_cancellable(
        &self,
        game: &str,
        cancellation: Arc<AtomicBool>,
        completion: &mut ProcessGroupCompletion,
    ) -> Result<Value, String> {
        self.json_cancellable(
            &["backup".to_owned(), "--force".to_owned(), game.to_owned()],
            OPERATION_TIMEOUT,
            Some(&cancellation),
            completion,
        )
    }

    fn restore_cancellable(
        &self,
        game: &str,
        cancellation: Arc<AtomicBool>,
        completion: &mut ProcessGroupCompletion,
    ) -> Result<Value, String> {
        self.json_cancellable(
            &["restore".to_owned(), "--force".to_owned(), game.to_owned()],
            OPERATION_TIMEOUT,
            Some(&cancellation),
            completion,
        )
    }

    fn restore_backup(&self, game: &str, backup_id: &str) -> Result<Value, String> {
        self.json(
            &[
                "restore".to_owned(),
                "--force".to_owned(),
                "--backup".to_owned(),
                backup_id.to_owned(),
                game.to_owned(),
            ],
            OPERATION_TIMEOUT,
        )
    }

    fn aliases(&self) -> Result<BTreeMap<String, String>, String> {
        let output = self.json(&["config".to_owned(), "show".to_owned()], BACKUPS_TIMEOUT)?;
        let mut aliases = BTreeMap::new();
        if let Some(games) = output.get("customGames").and_then(Value::as_array) {
            for game in games {
                if let (Some(name), Some(alias)) = (
                    game.get("name").and_then(Value::as_str),
                    game.get("alias").and_then(Value::as_str),
                ) {
                    aliases.insert(name.to_owned(), alias.to_owned());
                }
            }
        }
        Ok(aliases)
    }

    fn config_path(&self) -> Result<PathBuf, String> {
        let mut cached = lock(&self.config_path);
        if cached.is_none() {
            let path = self.text(&["config".to_owned(), "path".to_owned()], BACKUPS_TIMEOUT)?;
            *cached = Some(PathBuf::from(path.trim()));
        }
        cached
            .as_ref()
            .cloned()
            .ok_or_else(|| "Ludusavi config path discovery returned no path".to_owned())
    }

    fn config_marker(&self) -> Result<i64, String> {
        let config_path = self
            .config_path()?
            .canonicalize()
            .map_err(|error| error.to_string())?;
        let config_metadata = fs::metadata(&config_path).map_err(|error| error.to_string())?;
        let mut mtimes = vec![
            config_metadata
                .modified()
                .map_err(|error| error.to_string())?,
        ];
        for filename in ["cache.yaml", "manifest.yaml"] {
            if let Ok(metadata) = fs::metadata(config_path.with_file_name(filename))
                && metadata.is_file()
                && let Ok(modified) = metadata.modified()
            {
                mtimes.push(modified);
            }
        }
        mtimes.sort();
        let text = mtimes
            .iter()
            .map(|time| {
                time.duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos()
                    .to_string()
            })
            .collect::<Vec<_>>()
            .join(",");
        let digest = Sha256::digest(text.as_bytes());
        Ok(i64::from_be_bytes(
            digest[..8]
                .try_into()
                .expect("SHA-256 has eight leading bytes"),
        ))
    }

    fn list_backups(&self, game: &str) -> Result<Value, String> {
        let output = self.backups(Some(game))?;
        let games = game_objects(&output)?;
        let game_output = games.get(game).or_else(|| games.values().next());
        let Some(game_output) = game_output else {
            return Ok(
                json!({"game":game,"backup_path":null,"total_size_bytes":null,"backups":[]}),
            );
        };
        let backup_path = game_output.get("backupPath").and_then(Value::as_str);
        let mut total_size: u64 = 0;
        let mut all_unknown = true;
        let backups = game_output
            .get("backups")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .enumerate()
            .map(|(index, backup)| {
                let name = backup.get("name").and_then(Value::as_str);
                let (size, count) = if backup.get("size").is_some() {
                    (
                        backup.get("size").cloned(),
                        backup.get("file_count").cloned(),
                    )
                } else if index < 10 {
                    name.and_then(|name| backup_path.and_then(|path| backup_disk_stats(path, name)))
                        .map_or((None, None), |(size, count)| {
                            (Some(json!(size)), count.map(|count| json!(count)))
                        })
                } else {
                    (None, None)
                };
                if let Some(size) = size.as_ref().and_then(Value::as_u64) {
                    total_size = total_size.saturating_add(size);
                    all_unknown = false;
                }
                json!({
                    "id": name,
                    "when": backup.get("when"),
                    "locked": backup.get("locked").and_then(Value::as_bool).unwrap_or(false),
                    "os": backup.get("os"),
                    "comment": backup.get("comment"),
                    "size_bytes": size,
                    "file_count": count,
                })
            })
            .collect::<Vec<_>>();
        let mut backups = backups;
        backups.sort_by(|left, right| {
            right
                .get("when")
                .and_then(Value::as_str)
                .unwrap_or("")
                .cmp(left.get("when").and_then(Value::as_str).unwrap_or(""))
        });
        Ok(json!({
            "game": game,
            "backup_path": backup_path,
            "total_size_bytes": (!all_unknown).then_some(total_size),
            "backups": backups,
        }))
    }

    fn logs(&self) -> Result<String, String> {
        let path = self.config_path()?.with_file_name("ludusavi_rCURRENT.log");
        match fs::read_to_string(path) {
            Ok(contents) => Ok(contents),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(String::new()),
            Err(error) => Err(error.to_string()),
        }
    }
}

pub(crate) struct ProcessGroupCompletion {
    pid: Option<i32>,
    confirmed: bool,
    groups: Option<Arc<Mutex<BTreeSet<i32>>>>,
    child: Option<Child>,
    readers: ProcessReaders,
}

impl ProcessGroupCompletion {
    pub(crate) fn confirmed() -> Self {
        Self {
            pid: None,
            confirmed: true,
            groups: None,
            child: None,
            readers: (None, None),
        }
    }

    #[cfg(test)]
    pub(crate) fn pending(pid: i32) -> Self {
        Self {
            pid: Some(pid),
            confirmed: false,
            groups: None,
            child: None,
            readers: (None, None),
        }
    }

    fn track(&mut self, pid: i32, groups: Arc<Mutex<BTreeSet<i32>>>, child: Child) {
        self.pid = Some(pid);
        self.confirmed = false;
        self.groups = Some(groups);
        self.child = Some(child);
    }

    fn child_mut(&mut self) -> &mut Child {
        self.child
            .as_mut()
            .expect("tracked process group has child")
    }

    fn set_stdout_reader(&mut self, reader: ProcessOutputReader) {
        self.readers.0 = Some(reader);
    }

    fn set_stderr_reader(&mut self, reader: ProcessOutputReader) {
        self.readers.1 = Some(reader);
    }

    fn take_stdout_reader(&mut self) -> Option<ProcessOutputReader> {
        self.readers.0.take()
    }

    fn take_stderr_reader(&mut self) -> Option<ProcessOutputReader> {
        self.readers.1.take()
    }

    fn confirm_exit(&mut self) {
        if let (Some(pid), Some(groups)) = (self.pid, &self.groups) {
            lock(groups).remove(&pid);
        }
        self.confirmed = true;
    }

    pub(crate) fn wait(&mut self, cancellation: Option<&AtomicBool>) {
        if !self.confirmed
            && let Some(pid) = self.pid
        {
            while group_exists(pid) {
                if cancellation.is_some_and(|token| token.load(Ordering::Acquire)) {
                    let _ = signal_group(pid, libc::SIGKILL);
                }
                if let Some(child) = self.child.as_mut() {
                    let _ = child.try_wait();
                }
                thread::sleep(Duration::from_millis(10));
            }
        }
        self.reap_child();
        if !self.confirmed {
            self.confirm_exit();
        }
        if let Some(reader) = self.readers.0.take() {
            let _ = reader.join();
        }
        if let Some(reader) = self.readers.1.take() {
            let _ = reader.join();
        }
    }

    fn reap_child(&mut self) {
        if let Some(child) = self.child.as_mut() {
            if child.try_wait().ok().flatten().is_none() {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
    }
}

impl Drop for ProcessGroupCompletion {
    fn drop(&mut self) {
        let cancellation = AtomicBool::new(true);
        self.wait(Some(&cancellation));
    }
}

#[derive(Default)]
struct ProcessManager {
    stopping: AtomicBool,
    groups: Arc<Mutex<BTreeSet<i32>>>,
    #[cfg(test)]
    fail_reader_at: std::sync::atomic::AtomicUsize,
    #[cfg(test)]
    reader_attempt: std::sync::atomic::AtomicUsize,
    #[cfg(test)]
    after_track_hook: Mutex<Option<AfterTrackHook>>,
}

impl ProcessManager {
    fn spawn_output_reader(
        &self,
        pipe: impl Read + Send + 'static,
    ) -> io::Result<ProcessOutputReader> {
        #[cfg(test)]
        {
            let attempt = self.reader_attempt.fetch_add(1, Ordering::AcqRel) + 1;
            if self.fail_reader_at.load(Ordering::Acquire) == attempt {
                return Err(io::Error::other("fixture output reader creation failure"));
            }
        }
        thread::Builder::new().spawn(move || read_pipe(pipe))
    }
    fn run_at(
        &self,
        program: &Path,
        args: &[String],
        timeout: Duration,
        text: bool,
    ) -> Result<String, String> {
        let mut completion = ProcessGroupCompletion::confirmed();
        let result = self.run_at_cancellable(program, args, timeout, text, None, &mut completion);
        completion.wait(Some(&self.stopping));
        result
    }

    fn run_at_cancellable(
        &self,
        program: &Path,
        args: &[String],
        timeout: Duration,
        text: bool,
        cancellation: Option<&AtomicBool>,
        completion: &mut ProcessGroupCompletion,
    ) -> Result<String, String> {
        if self.stopping.load(Ordering::Acquire)
            || cancellation.is_some_and(|token| token.load(Ordering::Acquire))
        {
            return Err("Ludusavi operation cancelled".to_owned());
        }
        let mut command = Command::new(program);
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        command.env("LD_LIBRARY_PATH", "");
        if env::var_os("XDG_RUNTIME_DIR").is_none() {
            let uid = unsafe { libc::getuid() };
            let candidate = format!("/run/user/{uid}");
            command.env(
                "XDG_RUNTIME_DIR",
                if Path::new(&candidate).is_dir() {
                    candidate
                } else {
                    "/run/user/1000".to_owned()
                },
            );
        }
        command.process_group(0);
        let mut child = command
            .spawn()
            .map_err(|error| format!("Could not start Ludusavi command: {error}"))?;
        let pid = match i32::try_from(child.id()) {
            Ok(pid) => pid,
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Ludusavi process ID is out of range".to_owned());
            }
        };
        completion.track(pid, Arc::clone(&self.groups), child);
        lock(&self.groups).insert(pid);
        #[cfg(test)]
        if let Some(hook) = lock(&self.after_track_hook).take() {
            hook(pid);
        }
        if self.stopping.load(Ordering::Acquire)
            || cancellation.is_some_and(|token| token.load(Ordering::Acquire))
        {
            let _ = signal_group(pid, libc::SIGTERM);
        }
        let stdout = completion.child_mut().stdout.take().expect("piped stdout");
        let stderr = completion.child_mut().stderr.take().expect("piped stderr");
        let stdout_reader = match self.spawn_output_reader(stdout) {
            Ok(reader) => reader,
            Err(error) => {
                if terminate_group(pid, completion.child_mut()) {
                    completion.confirm_exit();
                    completion.wait(None);
                }
                return Err(format!("Could not start Ludusavi stdout reader: {error}"));
            }
        };
        completion.set_stdout_reader(stdout_reader);
        let stderr_reader = match self.spawn_output_reader(stderr) {
            Ok(reader) => reader,
            Err(error) => {
                if terminate_group(pid, completion.child_mut()) {
                    completion.confirm_exit();
                    completion.wait(None);
                }
                return Err(format!("Could not start Ludusavi stderr reader: {error}"));
            }
        };
        completion.set_stderr_reader(stderr_reader);
        let started = Instant::now();
        let mut status = None;
        let mut outcome = None;
        loop {
            if self.stopping.load(Ordering::Acquire)
                || cancellation.is_some_and(|token| token.load(Ordering::Acquire))
            {
                outcome = Some("cancelled".to_owned());
                break;
            }
            match completion.child_mut().try_wait() {
                Ok(Some(child_status)) => {
                    status = Some(child_status);
                    if !group_exists(pid) {
                        break;
                    }
                }
                Ok(None) => {}
                Err(error) => {
                    outcome = Some(format!("Could not wait for Ludusavi: {error}"));
                    break;
                }
            }
            if started.elapsed() >= timeout {
                outcome = Some(format!("timeout:{timeout:?}"));
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        let group_exited = if outcome.is_some() || group_exists(pid) {
            terminate_group(pid, completion.child_mut())
        } else {
            true
        };
        if !group_exited {
            return Err("Could not confirm Ludusavi process group exit".to_owned());
        }
        if status.is_none() {
            status = completion.child_mut().wait().ok();
        }
        completion.confirm_exit();
        let stdout = match completion
            .take_stdout_reader()
            .ok_or_else(|| "Ludusavi stdout reader was not started".to_owned())?
            .join()
            .unwrap_or_else(|_| Err(io::Error::other("stdout reader panicked")))
        {
            Ok(stdout) => stdout,
            Err(error) => return Err(format!("Could not read Ludusavi stdout: {error}")),
        };
        let stderr = match completion
            .take_stderr_reader()
            .ok_or_else(|| "Ludusavi stderr reader was not started".to_owned())?
            .join()
            .unwrap_or_else(|_| Err(io::Error::other("stderr reader panicked")))
        {
            Ok(stderr) => stderr,
            Err(error) => return Err(format!("Could not read Ludusavi stderr: {error}")),
        };
        if let Some(outcome) = outcome {
            if outcome == "cancelled" {
                Err("Ludusavi operation cancelled".to_owned())
            } else if let Some(timeout) = outcome.strip_prefix("timeout:") {
                Err(format!(
                    "Ludusavi command exceeded its configured timeout after {timeout}: {}",
                    args.join(" ")
                ))
            } else {
                Err(outcome)
            }
        } else if let Some(status) = status {
            if !status.success() {
                Err(format!(
                    "Ludusavi command failed with exit code {}: {}",
                    status.code().unwrap_or(-1),
                    String::from_utf8_lossy(&stderr).trim()
                ))
            } else if text {
                Ok(String::from_utf8_lossy(&stdout).into_owned())
            } else {
                String::from_utf8(stdout)
                    .map_err(|error| format!("Ludusavi output is not UTF-8: {error}"))
            }
        } else {
            Err("Could not reap Ludusavi child process".to_owned())
        }
    }

    fn cancel_all(&self) {
        self.stopping.store(true, Ordering::Release);
        for pid in lock(&self.groups).iter().copied() {
            let _ = signal_group(pid, libc::SIGTERM);
        }
    }
    fn groups_exited(&self) -> bool {
        let mut groups = lock(&self.groups);
        groups.retain(|pid| group_exists(*pid));
        groups.is_empty()
    }
}

#[cfg(test)]
pub(crate) fn run_test_process_after_registration(
    completion: &mut ProcessGroupCompletion,
    after_registration: impl FnOnce(i32) + Send + 'static,
) {
    let processes = ProcessManager::default();
    *lock(&processes.after_track_hook) = Some(Box::new(after_registration));
    let _ = processes.run_at_cancellable(
        Path::new("/bin/true"),
        &[],
        Duration::from_secs(1),
        false,
        None,
        completion,
    );
}

#[cfg(test)]
pub(crate) fn run_test_cancellable_process(
    completion: &mut ProcessGroupCompletion,
    cancellation: &AtomicBool,
    after_registration: impl FnOnce(i32) + Send + 'static,
) -> Result<String, String> {
    let processes = ProcessManager::default();
    *lock(&processes.after_track_hook) = Some(Box::new(after_registration));
    processes.run_at_cancellable(
        Path::new("/bin/sleep"),
        &["30".to_owned()],
        Duration::from_secs(30),
        false,
        Some(cancellation),
        completion,
    )
}

fn read_pipe(mut pipe: impl Read) -> io::Result<Vec<u8>> {
    let mut output = Vec::new();
    pipe.read_to_end(&mut output)?;
    Ok(output)
}

fn terminate_group(pid: i32, child: &mut Child) -> bool {
    let _ = signal_group(pid, libc::SIGTERM);
    let grace_end = Instant::now() + TERMINATE_GRACE;
    while Instant::now() < grace_end && group_exists(pid) {
        let _ = child.try_wait();
        thread::sleep(Duration::from_millis(10));
    }
    if group_exists(pid) {
        let _ = signal_group(pid, libc::SIGKILL);
    }
    let deadline = Instant::now() + KILL_CONFIRM_TIMEOUT;
    while group_exists(pid) && Instant::now() < deadline {
        let _ = child.try_wait();
        thread::sleep(Duration::from_millis(10));
    }
    if child.try_wait().ok().flatten().is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
    !group_exists(pid)
}
fn signal_group(pid: i32, signal: i32) -> bool {
    if pid <= 1 {
        return false;
    }
    unsafe { libc::kill(-pid, signal) == 0 }
}

fn group_exists(pid: i32) -> bool {
    if pid <= 1 {
        return false;
    }
    if unsafe { libc::kill(-pid, 0) } == 0 {
        true
    } else {
        io::Error::last_os_error().raw_os_error() != Some(libc::ESRCH)
    }
}

fn deployment_location(processes: &ProcessManager, flatpak: &Path) -> Option<PathBuf> {
    let output = processes
        .run_at(
            flatpak,
            &[
                "info".to_owned(),
                "--show-location".to_owned(),
                FLATPAK_ID.to_owned(),
            ],
            DEPLOYMENT_TIMEOUT,
            false,
        )
        .ok()?;
    let path = Path::new(output.trim());
    if !path.is_absolute() {
        return None;
    }
    let path = path.canonicalize().ok()?;
    path.is_dir().then_some(path)
}

fn find_flatpak() -> Option<PathBuf> {
    let path = env::var_os("PATH").unwrap_or_else(|| "/bin:/usr/bin".into());
    find_executable("flatpak", &path)
}

fn find_executable(name: &str, path: &std::ffi::OsStr) -> Option<PathBuf> {
    env::split_paths(path)
        .map(|directory| {
            if directory.as_os_str().is_empty() {
                PathBuf::from(".")
            } else {
                directory
            }
        })
        .map(|directory| directory.join(name))
        .find(|candidate| {
            candidate.is_file()
                && std::ffi::CString::new(candidate.as_os_str().as_bytes())
                    .is_ok_and(|path| unsafe { libc::access(path.as_ptr(), libc::X_OK) == 0 })
        })
}

fn game_objects(value: &Value) -> Result<BTreeMap<String, Value>, String> {
    let root = value
        .as_object()
        .ok_or_else(|| "Ludusavi output root is not an object".to_owned())?;
    Ok(root
        .get("games")
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .filter_map(|(name, game)| game.as_object().map(|_| (name.clone(), game.clone())))
        .collect())
}

fn parse_ludusavi_json(output: &str) -> Result<Value, String> {
    serde_json::from_str(output)
        .map_err(|error| format!("Failed to parse Ludusavi JSON output: {error}"))
}
fn conflict_metadata(client: &LudusaviClient, game: &str) -> Value {
    let mut local_modified_at = None;
    let mut backup_modified_at: Option<String> = None;
    let mut backup_path: Option<String> = None;
    if let Ok(output) = client.backups(Some(game))
        && let Ok(games) = game_objects(&output)
        && let Some(data) = games.get(game)
    {
        backup_path = data
            .get("backupPath")
            .and_then(Value::as_str)
            .filter(|path| !path.is_empty())
            .map(str::to_owned);
        if let Some(backups) = data.get("backups").and_then(Value::as_array) {
            for when in backups
                .iter()
                .filter_map(|backup| backup.get("when").and_then(Value::as_str))
            {
                if backup_modified_at
                    .as_deref()
                    .is_none_or(|current| when > current)
                {
                    backup_modified_at = Some(when.to_owned());
                }
            }
        }
    }
    if let Ok(output) = client.backup_preview(Some(game))
        && let Ok(games) = game_objects(&output)
        && let Some(files) = games
            .get(game)
            .and_then(|data| data.get("files"))
            .and_then(Value::as_object)
    {
        let mut newest: Option<SystemTime> = None;
        for (path, data) in files {
            let mut candidates = Vec::with_capacity(3);
            for candidate in [
                Some(path.as_str()),
                data.get("originalPath").and_then(Value::as_str),
                data.get("redirectedPath").and_then(Value::as_str),
            ]
            .into_iter()
            .flatten()
            {
                let candidate = PathBuf::from(candidate);
                if candidate.is_absolute() && !candidates.contains(&candidate) {
                    candidates.push(candidate);
                }
            }
            for candidate in candidates {
                if let Ok(modified) =
                    fs::metadata(candidate).and_then(|metadata| metadata.modified())
                {
                    if newest.is_none_or(|previous| modified > previous) {
                        newest = Some(modified);
                    }
                    break;
                }
            }
        }
        local_modified_at =
            newest.and_then(|modified| OffsetDateTime::from(modified).format(&Rfc3339).ok());
    }
    json!({
        "localModifiedAt": local_modified_at,
        "backupModifiedAt": backup_modified_at,
        "backupPath": backup_path,
    })
}

fn game_error(game: &Value) -> Option<String> {
    for collection in ["files", "registry"] {
        if let Some(items) = game.get(collection).and_then(Value::as_object) {
            for item in items.values() {
                if item.get("failed").and_then(Value::as_bool) == Some(true) {
                    return Some(
                        item.get("error")
                            .filter(|error| json_truthy(error))
                            .map(python_string)
                            .unwrap_or_else(|| "Ludusavi reported a failed item".to_owned()),
                    );
                }
            }
        }
    }
    None
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_owned(),
        Value::Bool(value) => if *value { "True" } else { "False" }.to_owned(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => value.clone(),
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(python_repr)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(values) => format!(
            "{{{}}}",
            values
                .iter()
                .map(|(key, value)| format!(
                    "{}: {}",
                    python_repr(&Value::String(key.clone())),
                    python_repr(value)
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

fn python_repr(value: &Value) -> String {
    let Value::String(value) = value else {
        return python_string(value);
    };
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut repr = String::with_capacity(value.len() + 2);
    repr.push(quote);
    for character in value.chars() {
        match character {
            '\\' => repr.push_str("\\\\"),
            '\n' => repr.push_str("\\n"),
            '\r' => repr.push_str("\\r"),
            '\t' => repr.push_str("\\t"),
            character if character == quote => {
                repr.push('\\');
                repr.push(character);
            }
            character => repr.push(character),
        }
    }
    repr.push(quote);
    repr
}

fn normalize_game_name(name: &str) -> String {
    name.case_fold()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '.' | '-') {
                character
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn fuzzy_match_allowed(input: &str, target: &str, configured: bool) -> bool {
    if input.len() > 4 && target.len() > 4 {
        return true;
    }
    if !configured || target.len() != 4 || !input.starts_with(target) {
        return false;
    }
    input.len() == target.len()
        || input
            .as_bytes()
            .get(target.len())
            .is_some_and(|byte| matches!(*byte, b' ' | b'.' | b'-'))
}

fn sanitize_game_name(name: &str) -> String {
    name.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn normalize_installed_app_ids(raw: Option<&str>) -> Option<Option<String>> {
    let Some(raw) = raw else { return Some(None) };
    if raw.len() > MAX_INSTALLED_APP_IDS_BYTES {
        return Some(None);
    }
    if raw.trim().is_empty() {
        return Some(Some(String::new()));
    }
    let mut ids = BTreeSet::new();
    for token in raw.split(',') {
        if token.is_empty() || !token.bytes().all(|byte| byte.is_ascii_digit()) {
            return Some(None);
        }
        let canonical = token.trim_start_matches('0');
        ids.insert(if canonical.is_empty() { "0" } else { canonical });
    }
    let mut ids = ids.into_iter().collect::<Vec<_>>();
    ids.sort_by(|left, right| left.len().cmp(&right.len()).then_with(|| left.cmp(right)));
    Some(Some(ids.join(",")))
}

fn skip_result(game: &str, reason: &str) -> Value {
    json!({"status":"skipped", "game":game, "reason":reason})
}

fn escape_pointer(value: &str) -> String {
    value.replace('~', "~0").replace('/', "~1")
}

fn backup_disk_stats(path: &str, name: &str) -> Option<(u64, Option<usize>)> {
    let target = Path::new(path).join(name);
    if !target.is_dir() {
        let target = if target.is_file() {
            target
        } else {
            let mut fallback = target.as_os_str().to_os_string();
            fallback.push(".zip");
            let fallback = PathBuf::from(fallback);
            fallback.is_file().then_some(fallback)?
        };
        return backup_file_stats(&target);
    }
    let simple_layout = name == ".";
    let mut stack = vec![(target, true)];
    let mut size = 0u64;
    let mut count = 0usize;
    let mut scanned = 0usize;
    while let Some((directory, is_root)) = stack.pop() {
        for entry in fs::read_dir(directory).ok()? {
            let entry = entry.ok()?;
            let metadata = entry.metadata().ok()?;
            let file_name = entry.file_name();
            if simple_layout
                && is_root
                && ((metadata.is_dir() && file_name.to_string_lossy().starts_with("backup-"))
                    || (!metadata.is_dir()
                        && file_name.as_os_str() == std::ffi::OsStr::new("mapping.yaml")))
            {
                continue;
            }
            scanned += 1;
            if scanned > MAX_BACKUP_STAT_ENTRIES {
                return None;
            }
            if metadata.is_dir() {
                stack.push((entry.path(), false));
            } else if metadata.is_file() {
                size = size.saturating_add(metadata.len());
                count += 1;
            }
        }
    }
    Some((size, Some(count)))
}
fn backup_file_stats(path: &Path) -> Option<(u64, Option<usize>)> {
    let size = fs::metadata(path).ok()?.len();
    let count = match zip::ZipArchive::new(fs::File::open(path).ok()?) {
        Ok(archive) if archive.len() <= MAX_BACKUP_STAT_ENTRIES => Some(
            archive
                .file_names()
                .filter(|entry| !entry.ends_with('/'))
                .count(),
        ),
        Ok(_) => return None,
        Err(zip::result::ZipError::Io(_)) => return None,
        Err(_) => None,
    };
    Some((size, count))
}

fn valid_history_entry(value: &Value) -> Option<Value> {
    let operation = value.get("operation")?.as_str()?;
    if !matches!(operation, "backup" | "restore" | "start" | "exit") {
        return None;
    }
    let trigger = value.get("trigger")?.as_str()?;
    if !matches!(
        trigger,
        "manual_backup" | "manual_restore" | "auto_start" | "auto_exit"
    ) {
        return None;
    }
    let status = value.get("status")?.as_str()?;
    if !matches!(status, "backed_up" | "restored" | "skipped" | "failed") {
        return None;
    }
    let timestamp = value.get("timestamp")?.as_str()?;
    let mut entry = Map::new();
    entry.insert("operation".to_owned(), Value::String(operation.to_owned()));
    entry.insert("trigger".to_owned(), Value::String(trigger.to_owned()));
    entry.insert("status".to_owned(), Value::String(status.to_owned()));
    for key in ["reason", "message"] {
        entry.insert(
            key.to_owned(),
            value
                .get(key)
                .filter(|value| value.is_null() || value.is_string())
                .cloned()
                .unwrap_or(Value::Null),
        );
    }
    entry.insert("timestamp".to_owned(), Value::String(timestamp.to_owned()));
    Some(Value::Object(entry))
}

fn parse_timestamp(value: &str) -> Option<i128> {
    if let Ok(timestamp) = OffsetDateTime::parse(value, &Rfc3339) {
        return Some(timestamp.unix_timestamp_nanos());
    }
    let normalized = if value.contains(' ') && !value.contains('T') {
        value.replacen(' ', "T", 1)
    } else {
        format!("{value}T00:00:00Z")
    };
    OffsetDateTime::parse(&normalized, &Rfc3339)
        .ok()
        .map(|timestamp| timestamp.unix_timestamp_nanos())
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

#[cfg(test)]
mod tests {
    use super::{
        Game, LudusaviClient, LudusaviOperations, ProcessManager, Registry, backup_disk_stats,
        find_executable, fuzzy_match_allowed, game_error, game_objects, group_exists, lock,
        normalize_game_name, normalize_installed_app_ids, parse_ludusavi_json, sanitize_game_name,
        valid_history_entry,
    };
    use crate::persistence::{StateLock, read_object};
    use serde_json::json;
    use std::{
        fs,
        io::Write,
        os::unix::fs::{PermissionsExt, symlink},
        path::{Path, PathBuf},
        sync::{Arc, Barrier, atomic::AtomicBool},
        time::Duration,
    };
    use zip::{CompressionMethod, ZipWriter, write::FileOptions};
    #[test]
    fn game_status_maps_error_backup_and_configuration() {
        for (value, expected) in [
            (json!({"name":"Game","configured":false}), "error"),
            (json!({"name":"Game","configured":true}), "configured"),
            (
                json!({"name":"Game","needs_first_backup":true}),
                "needs_first_backup",
            ),
            (json!({"name":"Game","has_backup":true}), "has_backup"),
            (
                json!({"name":"Game","has_backup":true,"error":"failure"}),
                "error",
            ),
        ] {
            assert_eq!(Game::from_cache(&value).unwrap().status(), expected);
        }
    }
    #[test]
    fn game_name_sanitization_trims_and_collapses_whitespace() {
        for (input, expected) in [
            ("", ""),
            (" \t\n", ""),
            ("  Hades  ", "Hades"),
            ("Hades\t(Test)", "Hades (Test)"),
            ("  Hades \n (Test)  ", "Hades (Test)"),
            ("Hades: The Game!", "Hades: The Game!"),
            ("  HADES  ", "HADES"),
        ] {
            assert_eq!(sanitize_game_name(input), expected, "{input:?}");
        }
    }

    #[test]
    fn matcher_normalization_and_fuzzy_guard_tables() {
        for (input, expected) in [
            ("Hades II (Supergiant)", "hades ii supergiant"),
            ("Portal-2...!", "portal-2..."),
        ] {
            assert_eq!(normalize_game_name(input), expected);
        }
        for (input, target, configured, expected) in [
            ("metroid", "super metroid", true, true),
            ("met", "super metroid", true, false),
            ("abcd-extra", "abcd", true, true),
            ("abcd_extra", "abcd", true, false),
            ("abcd", "abcd", false, false),
        ] {
            assert_eq!(fuzzy_match_allowed(input, target, configured), expected);
        }
        let cache = serde_json::from_value(json!({
            "games": [
                {"name":"Hades: The Game!","configured":true,"steam_id":"300"},
                {"name":"Portal 2","configured":true,"has_backup":true},
                {"name":"Portal Stories: Mel","configured":true,"has_backup":true}
            ],
            "aliases":{"Old Hades Name":"Hades: The Game!"},
            "ids":{"300":"Hades: The Game!"}
        }))
        .unwrap();
        let registry = Registry::load(&cache);
        for (query, app_id, expected) in [
            ("hades the game", None, Some("Hades: The Game!")),
            ("Old Hades Name", None, Some("Hades: The Game!")),
            ("Unrelated", Some("300"), Some("Hades: The Game!")),
            ("Hades", None, Some("Hades: The Game!")),
            ("Portal", None, None),
        ] {
            assert_eq!(
                registry
                    .matching_game(query, app_id)
                    .as_ref()
                    .map(|game| game.name.as_str()),
                expected,
            );
        }
    }

    #[test]
    fn installed_app_id_normalization_sorts_and_deduplicates() {
        for (input, expected) in [
            (None, None),
            (Some(""), Some("")),
            (Some("  "), Some("")),
            (Some("300,413150"), Some("300,413150")),
            (Some("413150,300,413150"), Some("300,413150")),
            (Some("0002,01,2"), Some("1,2")),
            (Some("x,1"), None),
            (Some("1,"), None),
        ] {
            assert_eq!(
                normalize_installed_app_ids(input).unwrap().as_deref(),
                expected,
                "{input:?}"
            );
        }
    }

    #[test]
    fn ludusavi_output_parsing_table_rejects_non_mapping_entries() {
        for (input, expected) in [
            (
                json!({"games":{"Hades":{"files":{}},"Ignored":"not a mapping"}}),
                1,
            ),
            (json!({"games":null}), 0),
        ] {
            assert_eq!(game_objects(&input).unwrap().len(), expected);
        }
        for invalid_root in [json!(null), json!([])] {
            assert!(game_objects(&invalid_root).is_err());
        }
        for (output, expected) in [
            (
                r#"{"games":{"Hades":{"files":{}},"Ignored":"not a mapping"}}"#,
                1,
            ),
            (r#"{"games":null}"#, 0),
        ] {
            assert_eq!(
                game_objects(&parse_ludusavi_json(output).unwrap())
                    .unwrap()
                    .len(),
                expected
            );
        }
        assert!(parse_ludusavi_json("not-json").is_err());
        assert_eq!(
            game_error(&json!({"files":{"save":{"failed":true,"error":{"message":"denied"}}}})),
            Some("{'message': 'denied'}".to_owned()),
        );
        assert_eq!(
            game_error(&json!({"files":{"save":{"failed":true,"error":"denied"}}})),
            Some("denied".to_owned()),
        );
        assert_eq!(
            game_error(&json!({"registry":{"key":{"failed":true}}})),
            Some("Ludusavi reported a failed item".to_owned())
        );
        assert_eq!(
            game_error(&json!({"files":{"save":{"failed":false}}})),
            None
        );
    }

    #[test]
    fn history_entry_validation_table_rejects_invalid_fields() {
        let valid = json!({"operation":"backup","trigger":"manual_backup","status":"backed_up","timestamp":"2026-01-01T00:00:00Z","reason":4,"message":"ok"});
        assert_eq!(valid_history_entry(&valid).unwrap()["reason"], json!(null));
        for invalid in [
            json!(null),
            json!({"operation":"unknown","trigger":"manual_backup","status":"backed_up","timestamp":"x"}),
            json!({"operation":"backup","trigger":"unknown","status":"backed_up","timestamp":"x"}),
            json!({"operation":"backup","trigger":"manual_backup","status":"unknown","timestamp":"x"}),
            json!({"operation":"backup","trigger":"manual_backup","status":"backed_up","timestamp":1}),
        ] {
            assert!(valid_history_entry(&invalid).is_none(), "{invalid}");
        }
    }

    #[test]
    fn cache_invalidation_decisions_cover_all_markers() {
        let cache = serde_json::from_value(json!({
            "games":[{"name":"Hades","configured":true,"has_backup":true}],
            "installed_app_ids":"300,413150",
            "ludusavi_config_mtime_ns":12345
        }))
        .unwrap();
        let registry = Registry::load(&cache);
        assert!(registry.is_current(Some("300,413150"), Some(12345), false));
        assert!(!registry.is_current(Some("300"), Some(12345), false));
        assert!(!registry.is_current(None, Some(12346), false));
        assert!(!registry.is_current(None, Some(12345), true));
        assert!(!Registry::default().is_current(None, Some(12345), false));
    }
    #[test]
    fn timeout_kills_and_confirms_the_entire_process_group() {
        let directory = tempfile::tempdir().unwrap();
        let pid_file = directory.path().join("process-group");
        let args = [
            "-c".to_owned(),
            "trap '' TERM; sleep 30 & echo $$ > \"$1\"; wait".to_owned(),
            "sh".to_owned(),
            pid_file.display().to_string(),
        ];
        let processes = ProcessManager::default();
        let error = processes
            .run_at(Path::new("/bin/sh"), &args, Duration::from_millis(80), true)
            .unwrap_err();
        assert!(error.contains("timeout"), "{error}");
        let process_group = std::fs::read_to_string(pid_file)
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        assert!(!group_exists(process_group));
        assert!(processes.groups_exited());
    }
    #[test]
    fn output_reader_creation_failure_terminates_the_owned_process_group() {
        for failure_index in [1, 2] {
            let args = [
                "-c".to_owned(),
                "trap '' TERM; sleep 30 & wait".to_owned(),
                "sh".to_owned(),
            ];
            let processes = ProcessManager::default();
            processes
                .fail_reader_at
                .store(failure_index, std::sync::atomic::Ordering::Release);
            let mut completion = super::ProcessGroupCompletion::confirmed();
            let error = processes
                .run_at_cancellable(
                    Path::new("/bin/sh"),
                    &args,
                    Duration::from_secs(2),
                    true,
                    None,
                    &mut completion,
                )
                .unwrap_err();
            completion.wait(None);
            let process_group = completion.pid.unwrap();
            assert!(completion.confirmed);
            assert!(!group_exists(process_group));
            assert!(processes.groups_exited());
            assert!(
                error.contains("reader"),
                "failure at reader {failure_index} returned {error}"
            );
        }
    }
    #[test]
    fn successful_leader_waits_for_writer_descendant_before_returning() {
        let directory = tempfile::tempdir().unwrap();
        let marker = directory.path().join("writer-finished");
        let args = [
            "-c".to_owned(),
            "printf '{}\\n'; (sleep 0.1; printf child-finished > \"$1\") &".to_owned(),
            "sh".to_owned(),
            marker.display().to_string(),
        ];
        let processes = ProcessManager::default();
        let output = processes
            .run_at(Path::new("/bin/sh"), &args, Duration::from_secs(1), true)
            .unwrap();
        assert_eq!(output, "{}\n");
        assert!(
            marker.exists(),
            "writer descendant was terminated before finishing"
        );
        assert_eq!(std::fs::read_to_string(marker).unwrap(), "child-finished");
        assert!(processes.groups_exited());
    }
    fn write_zip(path: &Path, entries: &[&str]) -> u64 {
        let file = fs::File::create(path).unwrap();
        let mut archive = ZipWriter::new(file);
        for entry in entries {
            let options = FileOptions::default().compression_method(CompressionMethod::Stored);
            if entry.ends_with('/') {
                archive.add_directory(*entry, options).unwrap();
            } else {
                archive.start_file(*entry, options).unwrap();
                archive.write_all(b"x").unwrap();
            }
        }
        archive.finish().unwrap();
        fs::metadata(path).unwrap().len()
    }

    #[test]
    fn cache_snapshot_waits_for_the_state_lock() {
        let directory = tempfile::tempdir().unwrap();
        let cache_path = directory.path().join("cache.json");
        let state_lock = Arc::new(StateLock::new(&cache_path).unwrap());
        let operations = Arc::new(LudusaviOperations::new(
            cache_path.clone(),
            Arc::clone(&state_lock),
            &serde_json::Map::new(),
            json!({"snapshot":"old"}),
        ));
        let entered = Arc::new(Barrier::new(2));
        let release = Arc::new(Barrier::new(2));
        state_lock.set_test_after_acquire(Arc::new({
            let entered = Arc::clone(&entered);
            let release = Arc::clone(&release);
            move || {
                entered.wait();
                release.wait();
            }
        }));

        let save = {
            let operations = Arc::clone(&operations);
            std::thread::spawn(move || operations.save_cache().unwrap())
        };
        entered.wait();
        *lock(&operations.history) = json!({"snapshot":"new"});
        release.wait();
        save.join().unwrap();

        let cache = read_object(&cache_path).unwrap().unwrap();
        assert_eq!(cache.get("game_history"), Some(&json!({"snapshot":"new"})));
    }

    #[test]
    fn cancelled_backup_is_skipped_and_recorded_as_cancelled() {
        let directory = tempfile::tempdir().unwrap();
        let cache_path = directory.path().join("cache.json");
        let operations = LudusaviOperations::new(
            cache_path,
            Arc::new(StateLock::new(&directory.path().join("cache.json")).unwrap()),
            &serde_json::Map::new(),
            json!({}),
        );
        lock(&operations.registry).games.insert(
            "Hades".to_owned(),
            Game {
                name: "Hades".to_owned(),
                configured: true,
                has_backup: true,
                needs_first_backup: false,
                steam_id: None,
                error: None,
            },
        );
        *lock(&operations.client) = Some(Arc::new(LudusaviClient {
            processes: Arc::clone(&operations.processes),
            flatpak: PathBuf::new(),
            config_path: std::sync::Mutex::new(None),
            version: std::sync::Mutex::new(None),
            deployment: None,
            execution_failed: AtomicBool::new(false),
        }));
        operations.cancel_processes();

        assert_eq!(
            operations.force_backup("Hades").unwrap(),
            json!({"status":"skipped","reason":"cancelled","game":"Hades"})
        );
        let status = operations.get_operation_status();
        assert_eq!(status["last_result"], "cancelled");
        assert_eq!(status["last_error"], json!(null));
        let history = operations.get_game_history();
        assert_eq!(history["Hades"]["last_skip"]["status"], "skipped");
        assert_eq!(history["Hades"]["last_skip"]["reason"], "cancelled");
        assert_eq!(history["Hades"]["last_failure"], json!(null));
    }

    #[test]
    fn executable_lookup_skips_non_executable_path_entries() {
        let directory = tempfile::tempdir().unwrap();
        let blocked = directory.path().join("blocked");
        let allowed = directory.path().join("allowed");
        fs::create_dir(&blocked).unwrap();
        fs::create_dir(&allowed).unwrap();
        let blocked_file = blocked.join("flatpak");
        let allowed_file = allowed.join("flatpak");
        fs::write(&blocked_file, "").unwrap();
        fs::write(&allowed_file, "").unwrap();
        fs::set_permissions(&blocked_file, fs::Permissions::from_mode(0o644)).unwrap();
        fs::set_permissions(&allowed_file, fs::Permissions::from_mode(0o755)).unwrap();
        let path = std::env::join_paths([blocked, allowed]).unwrap();

        assert_eq!(
            find_executable("flatpak", &path).as_deref(),
            Some(allowed_file.as_path())
        );
    }

    #[test]
    fn backup_disk_stats_supports_snapshot_layouts() {
        let directory = tempfile::tempdir().unwrap();
        let archive_path = directory.path().join("snap1.zip");
        let archive_size = write_zip(&archive_path, &["f1.txt", "f2.txt", "folder/"]);
        assert_eq!(
            backup_disk_stats(directory.path().to_str().unwrap(), "snap1.zip"),
            Some((archive_size, Some(2)))
        );
        assert_eq!(
            backup_disk_stats(directory.path().to_str().unwrap(), "snap1"),
            Some((archive_size, Some(2)))
        );

        fs::remove_file(&archive_path).unwrap();
        fs::write(directory.path().join("f1.txt"), "a").unwrap();
        fs::write(directory.path().join("f2.txt"), "bc").unwrap();
        fs::write(directory.path().join("mapping.yaml"), "ignore").unwrap();
        fs::create_dir(directory.path().join("backup-123")).unwrap();
        assert_eq!(
            backup_disk_stats(directory.path().to_str().unwrap(), "."),
            Some((3, Some(2)))
        );
        assert_eq!(
            backup_disk_stats(directory.path().to_str().unwrap(), "missing"),
            None
        );
    }

    #[test]
    fn backup_disk_stats_observes_entry_budget_for_directories_and_archives() {
        let directory = tempfile::tempdir().unwrap();
        let snapshot = directory.path().join("snapshot");
        fs::create_dir(&snapshot).unwrap();
        for index in 0..=1000 {
            fs::write(snapshot.join(format!("file-{index}")), "").unwrap();
        }
        assert_eq!(
            backup_disk_stats(directory.path().to_str().unwrap(), "snapshot"),
            None
        );
        let names = (0..=1000)
            .map(|index| format!("file-{index}"))
            .collect::<Vec<_>>();
        let entries = names.iter().map(String::as_str).collect::<Vec<_>>();
        write_zip(&directory.path().join("large.zip"), &entries);
        assert_eq!(
            backup_disk_stats(directory.path().to_str().unwrap(), "large.zip"),
            None
        );
    }

    #[test]
    fn config_logs_keep_the_discovered_symlink_path() {
        let directory = tempfile::tempdir().unwrap();
        let original = directory.path().join("original");
        let resolved = directory.path().join("resolved");
        fs::create_dir_all(&original).unwrap();
        fs::create_dir_all(&resolved).unwrap();
        let original_config = original.join("config.yaml");
        let resolved_config = resolved.join("config.yaml");
        fs::write(&resolved_config, "config").unwrap();
        symlink(&resolved_config, &original_config).unwrap();
        fs::write(original.join("ludusavi_rCURRENT.log"), "original path").unwrap();
        fs::write(resolved.join("ludusavi_rCURRENT.log"), "resolved path").unwrap();
        fs::write(original.join("cache.yaml"), "original cache").unwrap();
        fs::write(resolved.join("cache.yaml"), "resolved cache").unwrap();
        let fake = directory.path().join("flatpak");
        fs::write(
            &fake,
            format!(
                "#!/bin/sh\nprintf '%s\\n' '{}'\n",
                original_config.display()
            ),
        )
        .unwrap();
        fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
        let client = LudusaviClient {
            processes: Arc::new(ProcessManager::default()),
            flatpak: fake,
            config_path: std::sync::Mutex::new(None),
            version: std::sync::Mutex::new(None),
            deployment: None,
            execution_failed: AtomicBool::new(false),
        };

        assert_eq!(client.logs().unwrap(), "original path");
        let marker = client.config_marker().unwrap();
        std::thread::sleep(Duration::from_millis(20));
        fs::write(resolved.join("cache.yaml"), "updated resolved cache").unwrap();
        assert_ne!(client.config_marker().unwrap(), marker);
    }

    #[test]
    fn normalization_uses_full_unicode_case_folding() {
        assert_eq!(normalize_game_name("Straße"), "strasse");
    }
}
