mod activity;
mod api;
mod config;

use activity::{
    FolderRuntime, LocalActivity, PeerCompletion, RemoteProgress, apply_folder_status,
    folder_detection_grace_ms, parse_folder_runtime, parse_peer_completion, process_event,
    publish_sample,
};
use api::{
    FolderSelection, SyncthingApi, get_connection_snapshot, get_folder_status, get_my_device_id,
    resolve_folder,
};
use config::{expand_path, resolve_api_credentials};

use std::{
    collections::{BTreeSet, HashMap, HashSet},
    env, fs,
    net::IpAddr,
    path::{Component, Path, PathBuf},
    sync::{
        Arc, Condvar, Mutex, MutexGuard, Weak,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use quick_xml::{Reader, events::Event};
use reqwest::{
    Client, Url,
    header::{ACCEPT, HeaderValue},
    redirect::Policy,
};
use serde_json::{Map, Value, json};

use crate::http::block_on;

const DEFAULT_API_URL: &str = "http://127.0.0.1:8384";
const EVENT_TYPES: &str = "StateChanged,FolderSummary,FolderScanProgress,DownloadProgress,RemoteDownloadProgress,FolderCompletion,ItemStarted,ItemFinished,LocalChangeDetected,LocalIndexUpdated,FolderPaused,FolderResumed,ConfigSaved";
const ACTIVE_WINDOW: Duration = Duration::from_secs(15);
const SETTLE_WINDOW: Duration = Duration::from_secs(3);
const EVENT_TIMEOUT: Duration = Duration::from_secs(1);
const POST_GAME_CEILING: Duration = Duration::from_secs(900);
const POST_GAME_TTL: Duration = Duration::from_secs(960);
const PRE_GAME_TTL: Duration = Duration::from_secs(180);
const OUTBOUND_HOLD: Duration = Duration::from_millis(2500);
const OUTBOUND_CONFIRMATIONS: u8 = 3;
const OUTBOUND_STALL: Duration = Duration::from_secs(90);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(15);
const COMMON_FLATPAK_IDS: [&str; 5] = [
    "me.kozec.syncthingtk",
    "com.github.zocker_160.SyncThingy",
    "io.github.martchus.syncthingtray",
    "org.syncthing.Syncthing",
    "com.syncthing.Syncthing",
];

fn integer_field(data: &Value, key: &str) -> Option<u64> {
    data.get(key).and_then(Value::as_u64).or_else(|| {
        data.get(key)
            .and_then(Value::as_i64)
            .and_then(|value| u64::try_from(value).ok())
    })
}

#[derive(Clone)]
struct WatchShared {
    game_name: Option<String>,
    app_id: Option<String>,
    latest: Arc<Mutex<Value>>,
    stop: Arc<AtomicBool>,
    thread: Arc<Mutex<Option<JoinHandle<()>>>>,
}

impl WatchShared {
    #[expect(
        clippy::too_many_arguments,
        reason = "watch creation receives its owned runtime state"
    )]
    fn start(
        watch_id: String,
        phase: String,
        game_name: Option<&str>,
        app_id: Option<&str>,
        folder: FolderSelection,
        api: SyncthingApi,
        connected: HashSet<String>,
        ttl: Duration,
        owner: Weak<Mutex<ManagerState>>,
    ) -> Result<Self, String> {
        let latest = Arc::new(Mutex::new(Value::Null));
        let stop = Arc::new(AtomicBool::new(false));
        let worker_latest = Arc::clone(&latest);
        let worker_stop = Arc::clone(&stop);
        let thread = thread::Builder::new()
            .name(format!("syncthing-watch-{watch_id}"))
            .spawn(move || {
                run_watch(
                    watch_id,
                    phase,
                    folder,
                    api,
                    connected,
                    worker_latest,
                    worker_stop,
                    ttl,
                    owner,
                );
            })
            .map_err(|_| "Could not start Syncthing activity watch".to_owned())?;
        Ok(Self {
            game_name: game_name.map(str::to_owned),
            app_id: app_id.map(str::to_owned),
            latest,
            stop,
            thread: Arc::new(Mutex::new(Some(thread))),
        })
    }

    fn poll(&self, watch_id: &str) -> Value {
        let sample = lock(&self.latest).clone();
        if sample.is_null() {
            json!({"status":"activity", "watch_id":watch_id, "sample":{}})
        } else {
            sample
        }
    }

    fn stop_until(&self, deadline: Instant) -> bool {
        self.stop.store(true, Ordering::Release);
        let mut thread = lock(&self.thread);
        let Some(join) = thread.take() else {
            return true;
        };
        while !join.is_finished() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        if join.is_finished() {
            join.join().is_ok()
        } else {
            *thread = Some(join);
            false
        }
    }
}

#[derive(Default)]
struct ManagerState {
    stopping: bool,
    starts: usize,
    watches: HashMap<String, WatchShared>,
}

#[derive(Default)]
pub struct SyncthingWatchManager {
    state: Arc<Mutex<ManagerState>>,
    changed: Condvar,
}

struct StartGuard<'a>(&'a SyncthingWatchManager);
impl Drop for StartGuard<'_> {
    fn drop(&mut self) {
        let mut state = lock(&self.0.state);
        state.starts = state.starts.saturating_sub(1);
        self.0.changed.notify_all();
    }
}

impl SyncthingWatchManager {
    pub fn start_watch(
        &self,
        phase: &str,
        game_name: Option<&str>,
        app_id: Option<&str>,
        backup_path: Option<&str>,
    ) -> Value {
        {
            let mut state = lock(&self.state);
            if state.stopping {
                return json!({"status":"skipped","reason":"unloading","message":"Plugin unload is in progress."});
            }
            state.starts += 1;
        }
        let _start = StartGuard(self);
        let Some(backup_path) =
            backup_path.filter(|path| !path.trim().is_empty() && *path != "unknown")
        else {
            return json!({"status":"skipped","reason":"backup_path_unavailable","message":"Ludusavi backupPath is not configured."});
        };
        let (url, key) = match resolve_api_credentials() {
            Ok(credentials) => credentials,
            Err(error) if error == "No Syncthing configuration found." => {
                return json!({"status":"skipped","reason":"not_configured","message":error});
            }
            Err(_) => {
                return json!({"status":"skipped","reason":"api_unavailable","message":"Syncthing API credentials are unavailable."});
            }
        };
        let api = match SyncthingApi::new(&url, &key) {
            Ok(api) => api,
            Err(error) => {
                return json!({"status":"skipped","reason":"api_unavailable","message":error});
            }
        };
        let local_id = match get_my_device_id(&api) {
            Ok(id) => id,
            Err(_) => {
                log::warn!("Syncthing system status probe failed");
                return json!({"status":"skipped","reason":"api_unavailable","message":"Syncthing system status query failed."});
            }
        };
        let folder = match resolve_folder(&api, backup_path, &local_id) {
            Ok(folder) => folder,
            Err(error) if error.starts_with("No configured Syncthing folder contains path") => {
                return json!({"status":"skipped","reason":"folder_not_found","message":error});
            }
            Err(_) => {
                return json!({"status":"skipped","reason":"api_unavailable","message":"Syncthing folders query failed."});
            }
        };
        if folder.device_ids.is_empty() {
            return json!({"status":"skipped","reason":"folder_not_shared","message":"The Syncthing folder has no configured remote devices."});
        }
        let connected = match get_connection_snapshot(&api) {
            Ok(connected) => connected,
            Err(_) => {
                log::warn!("Syncthing connections probe failed");
                return json!({"status":"skipped","reason":"api_unavailable","message":"Syncthing connections query failed."});
            }
        };
        let connected_count = folder
            .device_ids
            .iter()
            .filter(|id| connected.contains(*id))
            .count();
        if connected_count == 0 {
            return json!({"status":"skipped","reason":"no_connected_peers","message":format!("None of the {} configured devices for the backup folder are connected.", folder.device_ids.len())});
        }
        let watch_id = format!(
            "{}-{}",
            std::process::id(),
            NEXT_WATCH_ID.fetch_add(1, Ordering::Relaxed)
        );
        let old = {
            let mut state = lock(&self.state);
            if state.stopping {
                return json!({"status":"skipped","reason":"unloading","message":"Plugin unload is in progress."});
            }
            let watch = match WatchShared::start(
                watch_id.clone(),
                phase.to_owned(),
                game_name,
                app_id,
                folder.clone(),
                api,
                connected,
                if phase == "post_game" {
                    POST_GAME_TTL
                } else {
                    PRE_GAME_TTL
                },
                Arc::downgrade(&self.state),
            ) {
                Ok(watch) => watch,
                Err(error) => {
                    return json!({"status":"skipped","reason":"watch_start_failed","message":error});
                }
            };
            let old_ids = state
                .watches
                .iter()
                .filter(|(_, old)| {
                    old.game_name.as_deref() == game_name && old.app_id.as_deref() == app_id
                })
                .map(|(id, _)| id.clone())
                .collect::<Vec<_>>();
            let mut old = Vec::new();
            for id in old_ids {
                if let Some(watch) = state.watches.remove(&id) {
                    old.push(watch);
                }
            }
            state.watches.insert(watch_id.clone(), watch);
            old
        };
        for watch in old {
            watch.stop_until(Instant::now() + Duration::from_secs(2));
        }
        json!({"status":"watching","watch_id":watch_id,"folder_id":folder.id,"label":folder.label,"path":folder.path.to_string_lossy(),"detection_grace_ms":folder_detection_grace_ms(&folder)})
    }

    pub fn get_activity(&self, watch_id: &str) -> Value {
        let state = lock(&self.state);
        state.watches.get(watch_id).map_or_else(
            || json!({"status":"stopped","watch_id":watch_id}),
            |watch| watch.poll(watch_id),
        )
    }

    pub fn stop_watch(&self, watch_id: &str) -> Value {
        let watch = lock(&self.state).watches.remove(watch_id);
        if let Some(watch) = watch {
            watch.stop_until(Instant::now() + Duration::from_secs(2));
        }
        json!({"status":"stopped","watch_id":watch_id})
    }

    pub fn stop_all_until(&self, deadline: Instant) -> bool {
        let (watches, starts_pending) = {
            let mut state = lock(&self.state);
            state.stopping = true;
            while state.starts > 0 && Instant::now() < deadline {
                let wait = deadline.saturating_duration_since(Instant::now());
                let (next, _) = self
                    .changed
                    .wait_timeout(state, wait)
                    .unwrap_or_else(|error| error.into_inner());
                state = next;
            }
            let starts_pending = state.starts > 0;
            let watches = std::mem::take(&mut state.watches)
                .into_values()
                .collect::<Vec<_>>();
            (watches, starts_pending)
        };
        let mut stopped = true;
        for watch in watches {
            stopped = watch.stop_until(deadline) && stopped;
        }
        stopped && !starts_pending
    }
}

static NEXT_WATCH_ID: AtomicU64 = AtomicU64::new(1);

#[expect(
    clippy::too_many_arguments,
    reason = "watch task receives its owned runtime state"
)]
fn run_watch(
    watch_id: String,
    phase: String,
    folder: FolderSelection,
    api: SyncthingApi,
    mut connected: HashSet<String>,
    latest: Arc<Mutex<Value>>,
    stop: Arc<AtomicBool>,
    ttl: Duration,
    owner: Weak<Mutex<ManagerState>>,
) {
    let started = Instant::now();
    let post_game = phase == "post_game";
    let mut state = "unknown".to_owned();
    let mut runtime = FolderRuntime::default();
    let mut cursor = 0_u64;
    let mut local = LocalActivity::default();
    let mut remote: HashMap<String, RemoteProgress> = HashMap::new();
    let mut peers: HashMap<String, PeerCompletion> = HashMap::new();
    let mut outbound_streak = 0_u8;
    let mut last_outbound_need: Option<u64> = None;
    let mut last_need_decrease: Option<Instant> = None;

    let initialize = (|| -> Result<(), String> {
        let status = get_folder_status(&api, &folder.id)?;
        state = status
            .get("state")
            .and_then(Value::as_str)
            .filter(|state| !state.is_empty() && *state != "unknown")
            .ok_or_else(|| "Invalid initial Syncthing folder state".to_owned())?
            .to_owned();
        runtime = parse_folder_runtime(&status);
        let events = api.get_json(
            "/rest/events",
            &[
                ("since", "0".to_owned()),
                ("limit", "1000".to_owned()),
                ("timeout", "1".to_owned()),
                ("events", EVENT_TYPES.to_owned()),
            ],
            Duration::from_secs(5),
        )?;
        let events = events
            .as_array()
            .ok_or_else(|| "Unexpected Syncthing events response".to_owned())?;
        cursor = events
            .iter()
            .filter_map(|event| integer_field(event, "id"))
            .max()
            .unwrap_or(0);
        if post_game {
            let now = Instant::now();
            for device in folder
                .device_ids
                .iter()
                .filter(|device| connected.contains(*device))
            {
                let response = api
                    .get_json(
                        "/rest/db/completion",
                        &[("folder", folder.id.clone()), ("device", device.clone())],
                        Duration::from_secs(10),
                    )
                    .map_err(|_| "Syncthing peer completion initialization failed.".to_owned())?;
                let completion = parse_peer_completion(&response, &folder, device, now)
                    .ok_or_else(|| "Syncthing peer completion initialization failed.".to_owned())?;
                peers.insert(device.clone(), completion);
            }
            if let Ok(status) = get_folder_status(&api, &folder.id) {
                apply_folder_status(
                    &status,
                    &mut state,
                    &mut runtime,
                    &mut local,
                    true,
                    Instant::now(),
                );
            }
        }
        Ok(())
    })();
    if let Err(error) = initialize {
        log::warn!(
            "Failed to initialize Syncthing watch: {}",
            sanitize_watch_error(&error)
        );
        *lock(&latest) = json!({"status":"failed","reason":"watch_initialization_failed","message":sanitize_watch_error(&error)});
        return;
    }

    let now = Instant::now();
    publish_sample(
        &latest,
        &watch_id,
        &state,
        &runtime,
        &local,
        &remote,
        &peers,
        &connected,
        post_game,
        &mut outbound_streak,
        now,
    );
    while !stop.load(Ordering::Acquire) {
        let now = Instant::now();
        if now.duration_since(started) >= ttl {
            *lock(&latest) =
                json!({"status":"stopped","watch_id":watch_id,"reason":"watch_ttl_expired"});
            if let Some(owner) = owner.upgrade() {
                lock(&owner).watches.remove(&watch_id);
            }
            break;
        }
        if let Ok(snapshot) = get_connection_snapshot(&api) {
            connected = snapshot;
        }
        if !folder.device_ids.is_empty()
            && !folder.device_ids.iter().any(|id| connected.contains(id))
        {
            *lock(&latest) = json!({"status":"failed","reason":"no_connected_peers","message":"All Syncthing devices configured for the backup folder are disconnected."});
            break;
        }
        if let Ok(status) = get_folder_status(&api, &folder.id) {
            apply_folder_status(
                &status,
                &mut state,
                &mut runtime,
                &mut local,
                post_game,
                now,
            );
        }
        let params = [
            ("since", cursor.to_string()),
            ("timeout", "1".to_owned()),
            ("events", EVENT_TYPES.to_owned()),
        ];
        if let Ok(events) = api.get_json(
            "/rest/events",
            &params,
            EVENT_TIMEOUT + Duration::from_secs(10),
        ) && let Some(events) = events.as_array()
        {
            if events
                .iter()
                .filter_map(|event| integer_field(event, "id"))
                .any(|id| id < cursor)
            {
                cursor = events
                    .iter()
                    .filter_map(|event| integer_field(event, "id"))
                    .max()
                    .unwrap_or(cursor);
            }
            let mut config_changed = false;
            for event in events {
                if let Some(id) = integer_field(event, "id") {
                    cursor = cursor.max(id);
                }
                config_changed |= event.get("type").and_then(Value::as_str) == Some("ConfigSaved");
                process_event(
                    event,
                    &folder,
                    &mut state,
                    &mut runtime,
                    &mut remote,
                    &mut peers,
                    &mut local,
                    post_game,
                );
            }
            if config_changed {
                match get_folder_status(&api, &folder.id) {
                    Ok(status) => {
                        state = status
                            .get("state")
                            .and_then(Value::as_str)
                            .filter(|state| !state.is_empty())
                            .unwrap_or("unknown")
                            .to_owned();
                        runtime = parse_folder_runtime(&status);
                    }
                    Err(_) => {
                        state = "unknown".to_owned();
                        runtime = FolderRuntime::default();
                    }
                }
            }
        }
        let now = Instant::now();
        remote.retain(|_, progress| {
            now.saturating_duration_since(progress.observed) <= ACTIVE_WINDOW
        });
        local
            .active_items
            .retain(|_, seen| now.saturating_duration_since(*seen) <= ACTIVE_WINDOW);
        if local
            .last_scan_progress
            .is_some_and(|seen| now.saturating_duration_since(seen) > ACTIVE_WINDOW)
        {
            local.last_scan_progress = None;
        }
        if local.active_download_files > 0
            && local
                .last_download_progress
                .is_some_and(|seen| now.saturating_duration_since(seen) > ACTIVE_WINDOW)
        {
            local.active_download_files = 0;
        }
        if post_game {
            let fresh = folder
                .device_ids
                .iter()
                .filter(|device| connected.contains(*device))
                .any(|device| {
                    peers.get(device).is_some_and(|peer| {
                        peer.need_bytes == 0
                            && peer.need_items == 0
                            && local
                                .outbound_index_observed
                                .is_some_and(|mutation| peer.observed >= mutation)
                    })
                });
            outbound_streak = if local.outbound_index_observed.is_some() && fresh {
                outbound_streak.saturating_add(1)
            } else {
                0
            };
            let incomplete = folder
                .device_ids
                .iter()
                .filter(|device| connected.contains(*device))
                .filter_map(|device| peers.get(device))
                .filter(|peer| peer.need_bytes > 0 || peer.need_items > 0)
                .collect::<Vec<_>>();
            if incomplete.is_empty() {
                last_outbound_need = None;
                last_need_decrease = None;
            } else {
                let need = incomplete.iter().fold(0_u64, |total, peer| {
                    total
                        .saturating_add(peer.need_bytes)
                        .saturating_add(peer.need_items)
                });
                if last_outbound_need.is_none_or(|previous| need < previous) {
                    last_need_decrease = Some(now);
                }
                last_outbound_need = Some(need);
                let stalled = last_need_decrease
                    .is_some_and(|last| now.saturating_duration_since(last) >= OUTBOUND_STALL);
                if stalled || now.duration_since(started) >= POST_GAME_CEILING {
                    *lock(&latest) = json!({"status":"failed","reason":"post_game_upload_incomplete","message":"Syncthing upload did not complete before monitoring ended."});
                    break;
                }
            }
        }
        publish_sample(
            &latest,
            &watch_id,
            &state,
            &runtime,
            &local,
            &remote,
            &peers,
            &connected,
            post_game,
            &mut outbound_streak,
            now,
        );
        let remaining = if now.duration_since(started) >= ttl {
            Duration::ZERO
        } else {
            Duration::from_secs(1)
        };
        if !remaining.is_zero() {
            let until = Instant::now() + remaining;
            while !stop.load(Ordering::Acquire) && Instant::now() < until {
                thread::sleep(Duration::from_millis(20));
            }
        }
    }
}

fn sanitize_watch_error(error: &str) -> &str {
    if error.contains("peer completion") {
        "Syncthing peer completion initialization failed."
    } else {
        "Syncthing watch initialization failed."
    }
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ttl_expiry_removes_owned_watch_without_a_stop_call() {
        use std::io::{BufRead, BufReader, Write};
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        thread::spawn(move || {
            for _ in 0..2 {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .unwrap();
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                loop {
                    let mut line = String::new();
                    reader.read_line(&mut line).unwrap();
                    if line == "\r\n" || line.is_empty() {
                        break;
                    }
                }
                let body = if request.starts_with("GET /rest/db/status") {
                    r#"{"state":"idle","sequence":1}"#
                } else {
                    "[]"
                };
                write!(
                    stream,
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                )
                .unwrap();
            }
        });
        let api = SyncthingApi::new(&format!("http://{address}"), "fixture-key").unwrap();
        let folder = FolderSelection {
            id: "folder".to_owned(),
            label: "Folder".to_owned(),
            path: PathBuf::from("/tmp"),
            device_ids: vec!["peer".to_owned()],
            watcher_enabled: None,
            watcher_delay: None,
            rescan_interval: None,
        };
        let manager = SyncthingWatchManager::default();
        let id = "expired-watch".to_owned();
        {
            let mut state = lock(&manager.state);
            let watch = WatchShared::start(
                id.clone(),
                "pre_game".to_owned(),
                None,
                None,
                folder,
                api,
                HashSet::from(["peer".to_owned()]),
                Duration::ZERO,
                Arc::downgrade(&manager.state),
            )
            .unwrap();
            state.watches.insert(id.clone(), watch);
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        while lock(&manager.state).watches.contains_key(&id) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        let retained = lock(&manager.state).watches.contains_key(&id);
        assert!(
            !retained,
            "expired watch remained owned: {}",
            manager.get_activity(&id)
        );
    }
}
