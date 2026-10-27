mod client;
mod migration;
mod process;

pub(crate) use client::LudusaviPaths;
#[cfg(test)]
use client::Runner;
use client::{LudusaviClient, find_flatpak, game_objects};
pub(crate) use process::ProcessGroupCompletion;
use process::ProcessManager;

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
    history::valid_history_entry,
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
    paths: LudusaviPaths,
    registry: Mutex<Registry>,
    history: Mutex<Value>,
    client: Mutex<Option<Arc<LudusaviClient>>>,
    processes: Arc<ProcessManager>,
    operation_lock: Mutex<()>,
    status: Mutex<OperationStatus>,
}

impl LudusaviOperations {
    pub(crate) fn new(
        cache_path: PathBuf,
        state_lock: Arc<StateLock>,
        cache: &Map<String, Value>,
        history: Value,
        paths: LudusaviPaths,
    ) -> Self {
        Self {
            cache_path,
            paths,
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
            // One preview answers the common cases; each Ludusavi launch reloads its manifest.
            // Real Ludusavi returns an empty `games` map exactly when the game has no backup.
            let preview = client.restore(name, true);
            let preview_games = preview
                .as_ref()
                .ok()
                .and_then(|value| game_objects(value).ok());
            let recency = match preview_games {
                Some(games) if games.is_empty() => "no_backup",
                Some(games) if games.contains_key(name) => {
                    restore_recency(games.get(name).and_then(|game| game.get("change")))
                }
                // Failed or unexpected preview: the two-step decision, reusing that same preview
                // so a retry can neither change the answer nor add another timeout.
                _ => {
                    let backups = game_objects(&client.backups(Some(name))?)?;
                    if backups
                        .get(name)
                        .and_then(|game| game.get("backups"))
                        .and_then(Value::as_array)
                        .is_none_or(Vec::is_empty)
                    {
                        "no_backup"
                    } else {
                        restore_recency(preview.as_ref().ok().and_then(|value| {
                            value.pointer(&format!("/games/{}/change", escape_pointer(name)))
                        }))
                    }
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
        self.client()
            .map_or(Value::Null, |client| client.launcher_command())
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
                && existing.reusable()
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
        let created = Arc::new(LudusaviClient::new(
            Arc::clone(&self.processes),
            &self.paths,
            find_flatpak(),
        )?);
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

fn restore_recency(change: Option<&Value>) -> &'static str {
    match classify_restore_change(change.and_then(Value::as_str)) {
        RestorePreview::LocalCurrent => "local_current",
        RestorePreview::BackupNewer => "backup_newer",
        RestorePreview::BackupDiffers => "backup_differs",
        RestorePreview::Ambiguous => "ambiguous",
    }
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
pub(crate) mod test_support {
    use super::*;

    impl LudusaviOperations {
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
                runner: Runner::Flatpak {
                    flatpak: PathBuf::new(),
                    deployment: None,
                },
                native_config: self.paths.native_config.clone(),
                config_path: Mutex::new(None),
                execution_failed: AtomicBool::new(false),
                version: Mutex::new(None),
            }));
            self.cancel_processes();
        }
        #[cfg(test)]
        pub(crate) fn use_ludusavi_test_command(&self, flatpak: PathBuf) {
            *lock(&self.client) = Some(Arc::new(LudusaviClient {
                processes: Arc::clone(&self.processes),
                runner: Runner::Flatpak {
                    flatpak,
                    deployment: None,
                },
                native_config: self.paths.native_config.clone(),
                config_path: Mutex::new(None),
                execution_failed: AtomicBool::new(false),
                version: Mutex::new(None),
            }));
        }
        #[cfg(test)]
        pub(crate) fn hold_operation_lock_for_test(&self) -> std::sync::MutexGuard<'_, ()> {
            lock(&self.operation_lock)
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
            &["30".into()],
            Duration::from_secs(30),
            false,
            Some(cancellation),
            completion,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::{
        Game, LudusaviClient, LudusaviOperations, LudusaviPaths, Registry, fuzzy_match_allowed,
        lock, normalize_game_name, normalize_installed_app_ids, sanitize_game_name,
        valid_history_entry,
    };
    use crate::persistence::{StateLock, read_object};
    use serde_json::json;
    use std::{
        path::PathBuf,
        sync::{Arc, Barrier, atomic::AtomicBool},
    };
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
    fn cache_snapshot_waits_for_the_state_lock() {
        let directory = tempfile::tempdir().unwrap();
        let cache_path = directory.path().join("cache.json");
        let state_lock = Arc::new(StateLock::new(&cache_path).unwrap());
        let operations = Arc::new(LudusaviOperations::new(
            cache_path.clone(),
            Arc::clone(&state_lock),
            &serde_json::Map::new(),
            json!({"snapshot":"old"}),
            LudusaviPaths::new(directory.path(), directory.path(), None),
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
            LudusaviPaths::new(directory.path(), directory.path(), None),
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
            runner: super::Runner::Flatpak {
                flatpak: PathBuf::new(),
                deployment: None,
            },
            native_config: operations.paths.native_config.clone(),
            config_path: std::sync::Mutex::new(None),
            version: std::sync::Mutex::new(None),
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
    fn normalization_uses_full_unicode_case_folding() {
        assert_eq!(normalize_game_name("Straße"), "strasse");
    }
}
