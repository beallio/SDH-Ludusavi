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

#[derive(Clone)]
struct SyncthingApi {
    base_url: Url,
    key: String,
    client: Client,
}

impl SyncthingApi {
    fn new(base_url: &str, key: &str) -> Result<Self, String> {
        let base_url = Url::parse(base_url).map_err(|_| local_url_error(base_url))?;
        validate_api_url(&base_url)?;
        let mut client = Client::builder()
            .timeout(REQUEST_TIMEOUT)
            .redirect(Policy::custom(|attempt| {
                if is_loopback_url(attempt.url()) {
                    attempt.follow()
                } else {
                    attempt.stop()
                }
            }));
        if base_url.scheme() == "https" {
            client = client.danger_accept_invalid_certs(true);
        }
        let client = client
            .build()
            .map_err(|_| "Could not initialize local Syncthing API client".to_owned())?;
        Ok(Self {
            base_url,
            key: key.to_owned(),
            client,
        })
    }

    fn get_json(
        &self,
        path: &str,
        params: &[(&str, String)],
        timeout: Duration,
    ) -> Result<Value, String> {
        validate_api_url(&self.base_url)?;
        let mut url = self.base_url.clone();
        url.path_segments_mut()
            .map_err(|_| "Invalid local Syncthing API path".to_owned())?
            .pop_if_empty()
            .extend(path.trim_start_matches('/').split('/'));
        let request = self
            .client
            .get(url)
            .header("X-API-Key", &self.key)
            .header(ACCEPT, HeaderValue::from_static("application/json"))
            .query(params)
            .timeout(timeout);
        let (status, bytes) = block_on(async {
            let response = request
                .send()
                .await
                .map_err(|_| "Syncthing API request failed".to_owned())?;
            let status = response.status();
            if !status.is_success() {
                return Err(format!("Syncthing API HTTP {}", status.as_u16()));
            }
            let bytes = response
                .bytes()
                .await
                .map_err(|_| "Syncthing API response failed".to_owned())?;
            Ok((status, bytes))
        })??;
        let _ = status;
        if bytes.is_empty() {
            return Ok(Value::Null);
        }
        serde_json::from_slice(&bytes).map_err(|_| "Invalid JSON from Syncthing API".to_owned())
    }
}

fn is_loopback_url(url: &Url) -> bool {
    matches!(url.scheme(), "http" | "https") && is_loopback_host(url.host_str())
}

fn is_loopback_host(host: Option<&str>) -> bool {
    match host {
        Some(host) if host.eq_ignore_ascii_case("localhost") => true,
        Some(host) => host
            .strip_prefix('[')
            .and_then(|host| host.strip_suffix(']'))
            .unwrap_or(host)
            .parse::<IpAddr>()
            .is_ok_and(|address| address.is_loopback()),
        None => false,
    }
}

fn local_url_error(url: &str) -> String {
    let scheme = url.split_once("://").map_or("", |(scheme, _)| scheme);
    let host = Url::parse(url)
        .ok()
        .and_then(|url| url.host_str().map(str::to_owned))
        .unwrap_or_default();
    format!(
        "Only local Syncthing API URLs are supported. Got '{scheme}://{host}'. Configure Syncthing to listen on 127.0.0.1:8384 or 0.0.0.0:8384 instead of a LAN-specific address."
    )
}

fn validate_api_url(url: &Url) -> Result<(), String> {
    if is_loopback_url(url) {
        Ok(())
    } else {
        Err(local_url_error(url.as_str()))
    }
}

#[derive(Clone, Debug)]
struct SyncthingConfig {
    api_key: String,
    api_url: Option<String>,
}

fn api_url_from_gui_address(address: Option<&str>, tls: bool) -> Option<String> {
    let address = address?.trim();
    if address.is_empty() {
        return None;
    }
    if address.contains("://") {
        return Some(address.trim_end_matches('/').to_owned());
    }
    let address = if address.starts_with(':') {
        format!("127.0.0.1{address}")
    } else if let Some(port) = address.strip_prefix("0.0.0.0:") {
        format!("127.0.0.1:{port}")
    } else if address == "0.0.0.0" {
        "127.0.0.1:8384".to_owned()
    } else if let Some(port) = address.strip_prefix("[::]:") {
        format!("[::1]:{port}")
    } else if address == "[::]" {
        "[::1]:8384".to_owned()
    } else {
        address.to_owned()
    };
    Some(format!(
        "{}://{address}",
        if tls { "https" } else { "http" }
    ))
}

fn parse_syncthing_config(path: &Path) -> Option<SyncthingConfig> {
    let text = fs::read_to_string(path).ok()?;
    parse_xml_config(&text).or_else(|| parse_regex_config(&text))
}

fn parse_xml_config(text: &str) -> Option<SyncthingConfig> {
    let mut reader = Reader::from_str(text);
    let mut in_gui = false;
    let mut tls = false;
    let mut field = None;
    let mut key = String::new();
    let mut address = String::new();
    loop {
        match reader.read_event() {
            Ok(Event::Start(element)) => {
                let name = element.local_name();
                if name.as_ref() == b"gui" && !in_gui {
                    in_gui = true;
                    for attr in element.attributes().with_checks(false) {
                        let attr = attr.ok()?;
                        if attr.key.local_name().as_ref() == b"tls" {
                            let value = attr.decode_and_unescape_value(reader.decoder()).ok()?;
                            tls = xml_true(&value);
                        }
                    }
                } else if in_gui {
                    field = match name.as_ref() {
                        b"apikey" => Some(0),
                        b"address" => Some(1),
                        _ => None,
                    };
                }
            }
            Ok(Event::Text(value)) if in_gui => {
                let decoded = value.decode().ok()?;
                let decoded = quick_xml::escape::unescape(&decoded).ok()?;
                match field {
                    Some(0) => key.push_str(&decoded),
                    Some(1) => address.push_str(&decoded),
                    _ => (),
                }
            }
            Ok(Event::CData(value)) if in_gui => {
                let decoded = value.decode().ok()?;
                match field {
                    Some(0) => key.push_str(&decoded),
                    Some(1) => address.push_str(&decoded),
                    _ => (),
                }
            }
            Ok(Event::GeneralRef(value)) if in_gui => {
                let target = match field {
                    Some(0) => &mut key,
                    Some(1) => &mut address,
                    _ => continue,
                };
                if let Some(character) = value.resolve_char_ref().ok()? {
                    target.push(character);
                } else {
                    target.push_str(quick_xml::escape::resolve_xml_entity(
                        &value.decode().ok()?,
                    )?);
                }
            }
            Ok(Event::End(element)) if in_gui => match element.local_name().as_ref() {
                b"apikey" | b"address" => field = None,
                b"gui" => break,
                _ => (),
            },
            Ok(Event::Eof) => break,
            Err(_) => return None,
            _ => (),
        }
    }
    let api_key = key.trim();
    if api_key.is_empty() {
        return None;
    }
    Some(SyncthingConfig {
        api_key: api_key.to_owned(),
        api_url: api_url_from_gui_address(
            (!address.trim().is_empty()).then_some(address.trim()),
            tls,
        ),
    })
}

fn parse_regex_config(text: &str) -> Option<SyncthingConfig> {
    let start = tag_start(text, "gui")?;
    let open_end = text[start..].find('>')? + start;
    let close = text[open_end + 1..].find("</gui>")? + open_end + 1;
    let attributes = &text[start + 4..open_end];
    let body = &text[open_end + 1..close];
    let tls = attributes
        .split_whitespace()
        .find_map(|part| {
            let (name, value) = part.split_once('=')?;
            if name != "tls" {
                return None;
            }
            Some(xml_true(value.trim_matches(['\'', '"'])))
        })
        .unwrap_or(false);
    let api_key = extract_tag(body, "apikey")?;
    let api_key = api_key.trim();
    if api_key.is_empty() {
        return None;
    }
    let address = extract_tag(body, "address");
    Some(SyncthingConfig {
        api_key: api_key.to_owned(),
        api_url: api_url_from_gui_address(address.as_deref(), tls),
    })
}

fn tag_start(text: &str, tag: &str) -> Option<usize> {
    let needle = format!("<{tag}");
    let mut offset = 0;
    while let Some(index) = text[offset..].find(&needle) {
        let start = offset + index;
        let boundary = text.as_bytes().get(start + needle.len()).copied()?;
        if boundary.is_ascii_whitespace() || boundary == b'>' {
            return Some(start);
        }
        offset = start + needle.len();
    }
    None
}

fn extract_tag(text: &str, tag: &str) -> Option<String> {
    let start = tag_start(text, tag)?;
    let open_end = text[start..].find('>')? + start;
    let close = text[open_end + 1..].find(&format!("</{tag}>"))? + open_end + 1;
    Some(text[open_end + 1..close].to_owned())
}

fn xml_true(value: &str) -> bool {
    matches!(
        value
            .trim()
            .trim_matches(['\'', '"'])
            .to_ascii_lowercase()
            .as_str(),
        "true" | "1" | "yes" | "on"
    )
}

fn expand_path(path: &str) -> PathBuf {
    if let Some(rest) = path.strip_prefix("~/") {
        return env::var_os("HOME").map_or_else(
            || PathBuf::from(path),
            |home| PathBuf::from(home).join(rest),
        );
    }
    if path == "~" {
        return env::var_os("HOME").map_or_else(|| PathBuf::from(path), PathBuf::from);
    }
    PathBuf::from(path)
}

fn candidate_config_files() -> Vec<PathBuf> {
    let home = env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
    let mut candidates = Vec::new();
    for (name, append) in [
        ("SYNCTHING_CONFIG_FILE", None),
        ("STCONFDIR", Some("config.xml")),
        ("STHOMEDIR", Some("config.xml")),
    ] {
        if let Some(value) = env::var_os(name).filter(|value| !value.is_empty()) {
            let path = expand_path(&value.to_string_lossy());
            candidates.push(if let Some(file) = append {
                path.join(file)
            } else {
                path
            });
        }
    }
    for (variable, default, suffix) in [
        ("XDG_STATE_HOME", ".local/state", "syncthing/config.xml"),
        ("XDG_CONFIG_HOME", ".config", "syncthing/config.xml"),
        ("XDG_DATA_HOME", ".local/share", "syncthing/config.xml"),
    ] {
        if let Some(value) = env::var_os(variable).filter(|value| !value.is_empty()) {
            candidates.push(expand_path(&value.to_string_lossy()).join(suffix));
        }
        candidates.push(home.join(default).join(suffix));
    }
    let current_flatpak_id = env::var("FLATPAK_ID").unwrap_or_default();
    for id in std::iter::once(current_flatpak_id.trim())
        .filter(|id| !id.is_empty())
        .chain(COMMON_FLATPAK_IDS)
    {
        let base = home.join(".var/app").join(id);
        for subpath in [
            "config/syncthing/config.xml",
            "data/syncthing/config.xml",
            ".config/syncthing/config.xml",
            ".local/state/syncthing/config.xml",
            ".local/share/syncthing/config.xml",
        ] {
            candidates.push(base.join(subpath));
        }
    }
    let mut seen = HashSet::new();
    candidates.retain(|path| seen.insert(path.clone()));
    candidates
}

fn resolve_api_credentials() -> Result<(String, String), String> {
    let config = candidate_config_files()
        .iter()
        .find_map(|path| parse_syncthing_config(path));
    let key = env::var("SYNCTHING_API_KEY")
        .ok()
        .filter(|key| !key.is_empty())
        .or_else(|| config.as_ref().map(|config| config.api_key.clone()));
    if key.is_none() {
        let configured = env::var_os("SYNCTHING_API_URL").is_some()
            || candidate_config_files().iter().any(|path| path.is_file());
        return Err(if configured {
            "No Syncthing API key found."
        } else {
            "No Syncthing configuration found."
        }
        .to_owned());
    }
    let url = env::var("SYNCTHING_API_URL")
        .ok()
        .filter(|url| !url.is_empty())
        .or_else(|| config.and_then(|config| config.api_url))
        .unwrap_or_else(|| DEFAULT_API_URL.to_owned());
    Ok((
        url.trim_end_matches('/').to_owned(),
        key.unwrap().trim().to_owned(),
    ))
}

#[derive(Clone, Debug)]
struct FolderSelection {
    id: String,
    label: String,
    path: PathBuf,
    device_ids: Vec<String>,
    watcher_enabled: Option<bool>,
    watcher_delay: Option<u64>,
    rescan_interval: Option<u64>,
}

fn normalize_path(path: &str) -> PathBuf {
    let expanded = expand_path(path);
    let absolute = if expanded.is_absolute() {
        expanded
    } else {
        env::current_dir().unwrap_or_default().join(expanded)
    };
    fs::canonicalize(&absolute).unwrap_or_else(|_| lexical_normalize(&absolute))
}

fn lexical_normalize(path: &Path) -> PathBuf {
    let mut output = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => (),
            Component::ParentDir => {
                output.pop();
            }
            other => output.push(other.as_os_str()),
        }
    }
    output
}

fn resolve_folder(
    api: &SyncthingApi,
    selected_path: &str,
    local_device_id: &str,
) -> Result<FolderSelection, String> {
    let folders = api.get_json("/rest/config/folders", &[], Duration::from_secs(10))?;
    let folders = folders
        .as_array()
        .ok_or_else(|| "Unexpected Syncthing folders response".to_owned())?;
    let selected = normalize_path(selected_path);
    let mut best: Option<(usize, FolderSelection)> = None;
    for folder in folders {
        let Some(id) = folder
            .get("id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
        else {
            continue;
        };
        let Some(raw_path) = folder
            .get("path")
            .and_then(Value::as_str)
            .filter(|path| !path.is_empty())
        else {
            continue;
        };
        let path = normalize_path(raw_path);
        if !selected.starts_with(&path) {
            continue;
        }
        let mut devices = BTreeSet::new();
        if let Some(items) = folder.get("devices").and_then(Value::as_array) {
            for device in items {
                if let Some(device) = device
                    .as_object()
                    .and_then(|device| device.get("deviceID"))
                    .and_then(Value::as_str)
                    .filter(|id| !id.is_empty())
                    && device != local_device_id
                {
                    devices.insert(device.to_owned());
                }
            }
        }
        let label = folder
            .get("label")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|label| !label.is_empty())
            .unwrap_or(id)
            .to_owned();
        let selection = FolderSelection {
            id: id.to_owned(),
            label,
            path: path.clone(),
            device_ids: devices.into_iter().collect(),
            watcher_enabled: folder.get("fsWatcherEnabled").and_then(Value::as_bool),
            watcher_delay: integer_field(folder, "fsWatcherDelayS"),
            rescan_interval: integer_field(folder, "rescanIntervalS"),
        };
        let path_length = path.as_os_str().len();
        if best
            .as_ref()
            .is_none_or(|(length, _)| path_length > *length)
        {
            best = Some((path_length, selection));
        }
    }
    best.map(|(_, folder)| folder)
        .ok_or_else(|| format!("No configured Syncthing folder contains path {selected_path}"))
}

fn integer_field(data: &Value, key: &str) -> Option<u64> {
    data.get(key).and_then(Value::as_u64).or_else(|| {
        data.get(key)
            .and_then(Value::as_i64)
            .and_then(|value| u64::try_from(value).ok())
    })
}

fn folder_detection_grace_ms(folder: &FolderSelection) -> u64 {
    let base = if folder.watcher_enabled == Some(false) {
        folder.rescan_interval.unwrap_or(3600)
    } else {
        folder.watcher_delay.unwrap_or(10)
    };
    base.saturating_add(20).clamp(30, 120) * 1000
}

#[derive(Clone, Default)]
struct FolderRuntime {
    sequence: u64,
    need_bytes: u64,
    need_files: u64,
    need_directories: u64,
    need_symlinks: u64,
    need_total_items: u64,
    need_deletes: u64,
    pull_errors: u64,
    watch_error: String,
}

impl FolderRuntime {
    fn content_needed(&self) -> u64 {
        self.need_files
            .saturating_add(self.need_directories)
            .saturating_add(self.need_symlinks)
    }
}

fn parse_folder_runtime(data: &Value) -> FolderRuntime {
    let get = |key: &str| integer_field(data, key).unwrap_or(0);
    FolderRuntime {
        sequence: integer_field(data, "sequence")
            .or_else(|| integer_field(data, "version"))
            .unwrap_or(0),
        need_bytes: get("needBytes"),
        need_files: get("needFiles"),
        need_directories: get("needDirectories"),
        need_symlinks: get("needSymlinks"),
        need_total_items: get("needTotalItems"),
        need_deletes: get("needDeletes"),
        pull_errors: get("pullErrors"),
        watch_error: data
            .get("watchError")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
    }
}

#[derive(Clone)]
struct PeerCompletion {
    observed: Instant,
    need_bytes: u64,
    need_items: u64,
    need_deletes: u64,
}

fn parse_peer_completion(
    data: &Value,
    folder: &FolderSelection,
    device_id: &str,
    now: Instant,
) -> Option<PeerCompletion> {
    let completion = data.get("completion")?.as_f64()?;
    if !completion.is_finite()
        || !(0.0..=100.0).contains(&completion)
        || !folder.device_ids.iter().any(|id| id == device_id)
    {
        return None;
    }
    Some(PeerCompletion {
        observed: now,
        need_bytes: integer_field(data, "needBytes")?,
        need_items: integer_field(data, "needItems")?,
        need_deletes: integer_field(data, "needDeletes")?,
    })
}

fn get_json(
    api: &SyncthingApi,
    path: &str,
    params: &[(&str, String)],
    timeout: Duration,
) -> Result<Value, String> {
    api.get_json(path, params, timeout)
}

fn get_connection_snapshot(api: &SyncthingApi) -> Result<HashSet<String>, String> {
    let data = get_json(
        api,
        "/rest/system/connections",
        &[],
        Duration::from_secs(10),
    )?;
    let connections = data
        .as_object()
        .and_then(|data| data.get("connections"))
        .and_then(Value::as_object)
        .ok_or_else(|| {
            "Unexpected system connections response: missing connections map".to_owned()
        })?;
    Ok(connections
        .iter()
        .filter(|(_, info)| info.get("connected").and_then(Value::as_bool) == Some(true))
        .map(|(id, _)| id.clone())
        .collect())
}

fn get_my_device_id(api: &SyncthingApi) -> Result<String, String> {
    let data = get_json(api, "/rest/system/status", &[], Duration::from_secs(10))?;
    data.get("myID")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| "Unexpected system status response: missing myID".to_owned())
}

#[derive(Default)]
struct LocalActivity {
    last_local_change: Option<Instant>,
    last_local_index: Option<Instant>,
    last_sequence_change: Option<Instant>,
    last_scan_progress: Option<Instant>,
    last_download_progress: Option<Instant>,
    last_item_finished: Option<Instant>,
    outbound_index_observed: Option<Instant>,
    outbound_hold_deadline: Option<Instant>,
    active_download_files: usize,
    active_items: HashMap<String, Instant>,
}

struct RemoteProgress {
    file_count: usize,
    observed: Instant,
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

fn get_folder_status(api: &SyncthingApi, folder_id: &str) -> Result<Value, String> {
    let status = api.get_json(
        "/rest/db/status",
        &[("folder", folder_id.to_owned())],
        Duration::from_secs(10),
    )?;
    if status.is_object() {
        Ok(status)
    } else {
        Err("Unexpected Syncthing folder status response".to_owned())
    }
}

fn apply_folder_status(
    status: &Value,
    state: &mut String,
    runtime: &mut FolderRuntime,
    local: &mut LocalActivity,
    post_game: bool,
    now: Instant,
) {
    let next = parse_folder_runtime(status);
    if runtime.sequence != 0 && next.sequence != 0 && next.sequence != runtime.sequence {
        local.last_sequence_change = Some(now);
        local.last_local_index = Some(now);
    }
    if post_game && next.sequence > runtime.sequence {
        note_outbound_mutation(local, now);
    }
    if let Some(next_state) = status
        .get("state")
        .and_then(Value::as_str)
        .filter(|state| !state.is_empty())
    {
        *state = next_state.to_owned();
    }
    *runtime = next;
}

fn note_outbound_mutation(local: &mut LocalActivity, now: Instant) {
    local.outbound_index_observed = Some(now);
    local.outbound_hold_deadline = Some(now + OUTBOUND_HOLD);
}

#[expect(
    clippy::too_many_arguments,
    reason = "event processing updates independent watch state"
)]
fn process_event(
    event: &Value,
    folder: &FolderSelection,
    state: &mut String,
    runtime: &mut FolderRuntime,
    remote: &mut HashMap<String, RemoteProgress>,
    peers: &mut HashMap<String, PeerCompletion>,
    local: &mut LocalActivity,
    post_game: bool,
) {
    let Some(kind) = event.get("type").and_then(Value::as_str) else {
        return;
    };
    let Some(data) = event.get("data").and_then(Value::as_object) else {
        return;
    };
    let matches_folder = data.get("folder").and_then(Value::as_str) == Some(&folder.id);
    let now = Instant::now();
    match kind {
        "StateChanged" if matches_folder => {
            if let Some(next) = data.get("to").and_then(Value::as_str) {
                *state = next.to_owned();
            }
        }
        "FolderSummary" if matches_folder => {
            if let Some(summary) = data.get("summary").filter(|summary| summary.is_object()) {
                if let Some(next) = summary.get("state").and_then(Value::as_str) {
                    *state = next.to_owned();
                }
                *runtime = parse_folder_runtime(summary);
            }
        }
        "FolderScanProgress" if matches_folder => local.last_scan_progress = Some(now),
        "DownloadProgress" => {
            if let Some(downloads) = data.get(&folder.id).and_then(Value::as_object) {
                local.active_download_files = downloads.len();
                local.last_download_progress = Some(now);
                if !downloads.is_empty() {
                    local.last_local_index = Some(now);
                }
            } else if data.is_empty() {
                local.active_download_files = 0;
                local.last_download_progress = Some(now);
            }
        }
        "RemoteDownloadProgress" if matches_folder => {
            if let Some(device) = data.get("device").and_then(Value::as_str) {
                let count = data
                    .get("state")
                    .and_then(Value::as_object)
                    .map_or(0, Map::len);
                if count == 0 {
                    remote.remove(device);
                } else {
                    remote.insert(
                        device.to_owned(),
                        RemoteProgress {
                            file_count: count,
                            observed: now,
                        },
                    );
                }
            }
        }
        "FolderCompletion" if post_game && matches_folder => {
            if let Some(device) = data
                .get("device")
                .and_then(Value::as_str)
                .filter(|device| folder.device_ids.iter().any(|id| id == *device))
                && let Some(completion) = parse_peer_completion(&event["data"], folder, device, now)
            {
                if completion.need_bytes > 0 || completion.need_items > 0 {
                    local.outbound_hold_deadline = Some(
                        local
                            .outbound_hold_deadline
                            .unwrap_or(now)
                            .max(now + OUTBOUND_HOLD),
                    );
                }
                peers.insert(device.to_owned(), completion);
            }
        }
        "ItemStarted" if matches_folder => {
            if data.get("action").and_then(Value::as_str) != Some("delete") {
                local.active_items.insert(
                    data.get("item")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown")
                        .to_owned(),
                    now,
                );
            }
        }
        "ItemFinished" if matches_folder => {
            let item = data
                .get("item")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            local.active_items.remove(item);
            if data.get("action").and_then(Value::as_str) != Some("delete") {
                local.last_item_finished = Some(now);
            }
        }
        "LocalChangeDetected" if matches_folder => local.last_local_change = Some(now),
        "LocalIndexUpdated" if matches_folder => {
            local.last_local_index = Some(now);
            let sequence = integer_field(&event["data"], "sequence")
                .or_else(|| integer_field(&event["data"], "version"))
                .unwrap_or(runtime.sequence);
            if sequence != 0 && sequence != runtime.sequence {
                local.last_sequence_change = Some(now);
                if sequence > runtime.sequence && post_game {
                    note_outbound_mutation(local, now);
                }
            }
            if sequence > runtime.sequence {
                note_outbound_mutation(local, now);
            }
            runtime.sequence = if sequence == 0 {
                runtime.sequence
            } else {
                sequence
            };
        }
        "FolderPaused" if matches_folder => *state = "paused".to_owned(),
        "FolderResumed" if matches_folder => *state = "unknown".to_owned(),
        "ConfigSaved" => (),
        _ => (),
    }
}

fn recent(value: Option<Instant>, now: Instant, window: Duration) -> bool {
    value.is_some_and(|value| now.saturating_duration_since(value) <= window)
}

fn outbound_peer_confirmation_pending(
    mutation: Option<Instant>,
    connected: &HashSet<String>,
    completions: &HashMap<String, PeerCompletion>,
    streak: u8,
) -> bool {
    let Some(mutation) = mutation else {
        return false;
    };
    let fresh_complete_peer = connected.iter().any(|device| {
        completions.get(device).is_some_and(|completion| {
            completion.need_bytes == 0
                && completion.need_items == 0
                && completion.observed >= mutation
        })
    });
    !fresh_complete_peer || streak < OUTBOUND_CONFIRMATIONS
}

#[expect(
    clippy::too_many_arguments,
    reason = "sample derives from independent watch state"
)]
fn publish_sample(
    latest: &Mutex<Value>,
    watch_id: &str,
    folder_state: &str,
    runtime: &FolderRuntime,
    local: &LocalActivity,
    remote: &HashMap<String, RemoteProgress>,
    peers: &HashMap<String, PeerCompletion>,
    connected: &HashSet<String>,
    post_game: bool,
    outbound_streak: &mut u8,
    now: Instant,
) {
    let peer_pending = if post_game {
        outbound_peer_confirmation_pending(
            local.outbound_index_observed,
            connected,
            peers,
            *outbound_streak,
        )
    } else {
        false
    };
    let outbound_hold = post_game
        && local
            .outbound_hold_deadline
            .is_some_and(|deadline| now < deadline);
    let preparing = matches!(
        folder_state,
        "sync-waiting"
            | "sync-preparing"
            | "syncing-waiting"
            | "clean-waiting"
            | "clean-preparing"
            | "cleaning"
    );
    let scanning = matches!(folder_state, "scanning" | "scan-waiting" | "scan-preparing")
        || recent(local.last_scan_progress, now, ACTIVE_WINDOW);
    let receive_needed = runtime.need_bytes > 0 || runtime.content_needed() > 0;
    let downloading = folder_state == "syncing"
        || local.active_download_files > 0
        || !local.active_items.is_empty();
    let uploading = !remote.is_empty() || peer_pending || outbound_hold;
    let active_transfer = downloading || uploading;
    let local_change_recent = recent(local.last_local_change, now, ACTIVE_WINDOW);
    let local_index_recent = recent(local.last_local_index, now, ACTIVE_WINDOW);
    let sequence_change_recent = recent(local.last_sequence_change, now, ACTIVE_WINDOW);
    let item_finished_recent = recent(local.last_item_finished, now, Duration::from_secs(2));
    let update_in_progress = active_transfer
        || receive_needed
        || preparing
        || scanning
        || local_change_recent
        || local_index_recent
        || sequence_change_recent
        || !local.active_items.is_empty()
        || item_finished_recent;
    let content_present = !receive_needed
        && local.active_download_files == 0
        && remote.is_empty()
        && local.active_items.is_empty();
    let settled = (folder_state == "idle" || preparing)
        && content_present
        && !active_transfer
        && !recent(local.last_local_change, now, SETTLE_WINDOW)
        && !recent(local.last_scan_progress, now, SETTLE_WINDOW)
        && !item_finished_recent
        && runtime.pull_errors == 0
        && runtime.watch_error.is_empty();
    let status = if active_transfer {
        "ACTIVE_TRANSFER"
    } else if folder_state == "error" || runtime.pull_errors > 0 || !runtime.watch_error.is_empty()
    {
        "ERROR"
    } else if folder_state == "paused" {
        "PAUSED"
    } else if scanning {
        "SCANNING"
    } else if receive_needed {
        "UPDATE_NEEDED"
    } else if preparing {
        "PREPARING"
    } else if local_change_recent || local_index_recent || sequence_change_recent {
        "INDEXING_OR_SEQUENCE_UPDATE"
    } else {
        "IDLE"
    };
    let _private_diagnostics = (
        remote
            .values()
            .map(|progress| progress.file_count)
            .sum::<usize>(),
        peers.values().map(|peer| peer.need_deletes).sum::<u64>(),
        runtime.need_total_items,
        runtime.need_deletes,
    );
    *lock(latest) = json!({"status":"activity","watch_id":watch_id,"sample":{"status":status,"folder_state":folder_state,"update_in_progress":update_in_progress,"settled":settled,"downloading":downloading,"uploading":uploading,"timestamp_unix":SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs_f64()}});
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
    fn rest_requests_keep_configured_loopback_url_prefix() {
        use std::io::{BufRead, BufReader, Write};
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let (sender, receiver) = std::sync::mpsc::channel();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut request = String::new();
            BufReader::new(stream.try_clone().unwrap())
                .read_line(&mut request)
                .unwrap();
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
                .unwrap();
            let _ = sender.send(request);
        });
        let api = SyncthingApi::new(&format!("http://{address}/syncthing"), "fixture-key").unwrap();
        assert_eq!(
            api.get_json("/rest/system/status", &[], Duration::from_secs(2))
                .unwrap(),
            json!({})
        );
        let request = receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("API request not received");
        assert!(
            request.starts_with("GET /syncthing/rest/system/status "),
            "{request}"
        );
    }

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

    #[test]
    fn gui_addresses_and_loopback_validation() {
        for (address, tls, expected) in [
            (Some("127.0.0.1:8384"), false, Some("http://127.0.0.1:8384")),
            (Some("127.0.0.1:8384"), true, Some("https://127.0.0.1:8384")),
            (Some("0.0.0.0:8384"), false, Some("http://127.0.0.1:8384")),
            (Some(":8384"), false, Some("http://127.0.0.1:8384")),
            (Some("[::]:8384"), false, Some("http://[::1]:8384")),
            (Some(""), false, None),
        ] {
            assert_eq!(api_url_from_gui_address(address, tls).as_deref(), expected);
        }
        for host in [
            "http://127.1.2.3:8384",
            "https://[::1]:8384",
            "http://localhost:8384",
        ] {
            assert!(
                Url::parse(host).is_ok_and(|url| is_loopback_url(&url)),
                "{host}"
            );
        }
        for host in [
            "http://192.168.1.50:8384",
            "http://steamdeck.local:8384",
            "http://0.0.0.0:8384",
            "ftp://127.0.0.1:8384",
        ] {
            assert!(
                !Url::parse(host).is_ok_and(|url| is_loopback_url(&url)),
                "{host}"
            );
        }
    }

    #[test]
    fn xml_credentials_decode_character_and_predefined_references() {
        let input = r#"<configuration><gui><address>127.0.0.1:83&#56;&#x34;/a&amp;b</address><apikey> A&#99;&#x63;&amp;&lt;&gt;&apos;&quot; Z </apikey></gui></configuration>"#;
        let parsed = parse_xml_config(input).unwrap();
        assert_eq!(parsed.api_key, "Acc&<>'\" Z");
        assert_eq!(parsed.api_url.as_deref(), Some("http://127.0.0.1:8384/a&b"));
    }

    #[test]
    fn xml_and_regex_fallback_parse_tls_and_credentials() {
        for input in [
            r#"<configuration><gui tls="true"><address>127.0.0.1:8384</address><apikey>testkey</apikey></gui></configuration>"#,
            r#"<configuration><gui tls='true'><address>127.0.0.1:8384</address><apikey>testkey</apikey></gui></configuration>"#,
        ] {
            let parsed = parse_xml_config(input)
                .or_else(|| parse_regex_config(input))
                .unwrap();
            assert_eq!(parsed.api_key, "testkey");
            assert_eq!(parsed.api_url.as_deref(), Some("https://127.0.0.1:8384"));
        }
        assert!(
            parse_xml_config("invalid")
                .or_else(|| parse_regex_config("invalid"))
                .is_none()
        );
        let malformed = r#"<configuration><gui tls="true"><address>127.0.0.1:8384</address><apikey>testkey</apikey></gui>"#;
        assert_eq!(
            parse_regex_config(malformed).unwrap().api_url.as_deref(),
            Some("https://127.0.0.1:8384")
        );
    }

    #[test]
    fn nested_folder_match_uses_longest_containing_path() {
        let parent = normalize_path("/tmp");
        let nested = normalize_path("/tmp/sdh_ludusavi");
        let backup = normalize_path("/tmp/sdh_ludusavi/backups");
        assert!(backup.starts_with(&parent));
        assert!(backup.starts_with(&nested));
        assert!(nested.as_os_str().len() > parent.as_os_str().len());
    }

    #[test]
    fn post_game_requires_fresh_content_complete_connected_peer() {
        let now = Instant::now();
        let mut completions = HashMap::new();
        completions.insert(
            "peer-a".to_owned(),
            PeerCompletion {
                observed: now,
                need_bytes: 0,
                need_items: 0,
                need_deletes: 5,
            },
        );
        assert!(outbound_peer_confirmation_pending(
            Some(now),
            &HashSet::new(),
            &completions,
            3
        ));
        assert!(outbound_peer_confirmation_pending(
            Some(now),
            &HashSet::from(["peer-a".to_owned()]),
            &completions,
            2
        ));
        assert!(!outbound_peer_confirmation_pending(
            Some(now),
            &HashSet::from(["peer-a".to_owned()]),
            &completions,
            3
        ));
        completions.insert(
            "peer-b".to_owned(),
            PeerCompletion {
                observed: now,
                need_bytes: 100,
                need_items: 1,
                need_deletes: 0,
            },
        );
        assert!(!outbound_peer_confirmation_pending(
            Some(now),
            &HashSet::from(["peer-a".to_owned(), "peer-b".to_owned()]),
            &completions,
            3
        ));
        assert!(outbound_peer_confirmation_pending(
            Some(now + Duration::from_secs(1)),
            &HashSet::from(["peer-a".to_owned()]),
            &completions,
            3
        ));
    }

    #[test]
    fn completion_events_for_other_folders_cannot_confirm_a_watch() {
        let folder = FolderSelection {
            id: "watched".to_owned(),
            label: String::new(),
            path: PathBuf::new(),
            device_ids: vec!["peer".to_owned()],
            watcher_enabled: None,
            watcher_delay: None,
            rescan_interval: None,
        };
        let mut state = String::new();
        let mut runtime = FolderRuntime::default();
        let mut remote = HashMap::new();
        let mut peers = HashMap::new();
        let mut local = LocalActivity::default();
        process_event(
            &json!({"type":"FolderCompletion","data":{"folder":"other","device":"peer","completion":100,"needBytes":0,"needItems":0,"needDeletes":0}}),
            &folder,
            &mut state,
            &mut runtime,
            &mut remote,
            &mut peers,
            &mut local,
            true,
        );
        assert!(peers.is_empty(), "another folder confirmed this watch");
    }

    fn sample_for_test(
        state: &str,
        runtime: &FolderRuntime,
        local: &LocalActivity,
        remote: &HashMap<String, RemoteProgress>,
        peers: &HashMap<String, PeerCompletion>,
        post_game: bool,
        now: Instant,
    ) -> Value {
        let latest = Mutex::new(Value::Null);
        let mut streak = 3;
        publish_sample(
            &latest,
            "fixture",
            state,
            runtime,
            local,
            remote,
            peers,
            &HashSet::from(["peer".to_owned()]),
            post_game,
            &mut streak,
            now,
        );
        latest.into_inner().unwrap()["sample"].clone()
    }

    #[test]
    fn download_and_upload_progress_are_scoped_to_the_watched_folder() {
        let folder = FolderSelection {
            id: "watched".to_owned(),
            label: String::new(),
            path: PathBuf::new(),
            device_ids: vec!["peer".to_owned()],
            watcher_enabled: None,
            watcher_delay: None,
            rescan_interval: None,
        };
        let mut state = "idle".to_owned();
        let mut runtime = FolderRuntime::default();
        let mut remote = HashMap::new();
        let mut peers = HashMap::new();
        let mut local = LocalActivity {
            active_download_files: 2,
            ..LocalActivity::default()
        };
        for (event, count) in [
            (
                json!({"type":"DownloadProgress","data":{"other":{"other.dat":{}}}}),
                2,
            ),
            (
                json!({"type":"DownloadProgress","data":{"watched":{"save.dat":{}}}}),
                1,
            ),
            (
                json!({"type":"DownloadProgress","data":{"other":{"other.dat":{}}}}),
                1,
            ),
        ] {
            process_event(
                &event,
                &folder,
                &mut state,
                &mut runtime,
                &mut remote,
                &mut peers,
                &mut local,
                false,
            );
            assert_eq!(local.active_download_files, count);
        }
        let download = sample_for_test(
            &state,
            &runtime,
            &local,
            &remote,
            &peers,
            false,
            Instant::now(),
        );
        assert_eq!(download["downloading"], true);
        assert_eq!(download["uploading"], false);
        assert_eq!(download["status"], "ACTIVE_TRANSFER");
        for (folder_id, expected) in [("other", 0), ("watched", 1)] {
            process_event(
                &json!({"type":"RemoteDownloadProgress","data":{"folder":folder_id,"device":"peer","state":{"save.dat":{}}}}),
                &folder,
                &mut state,
                &mut runtime,
                &mut remote,
                &mut peers,
                &mut local,
                false,
            );
            assert_eq!(remote.len(), expected);
        }
        let both = sample_for_test(
            &state,
            &runtime,
            &local,
            &remote,
            &peers,
            false,
            Instant::now(),
        );
        assert_eq!(both["downloading"], true);
        assert_eq!(both["uploading"], true);
        process_event(
            &json!({"type":"DownloadProgress","data":{}}),
            &folder,
            &mut state,
            &mut runtime,
            &mut remote,
            &mut peers,
            &mut local,
            false,
        );
        process_event(
            &json!({"type":"RemoteDownloadProgress","data":{"folder":"watched","device":"peer","state":{}}}),
            &folder,
            &mut state,
            &mut runtime,
            &mut remote,
            &mut peers,
            &mut local,
            false,
        );
        let cleared = sample_for_test(
            &state,
            &runtime,
            &local,
            &remote,
            &peers,
            false,
            Instant::now(),
        );
        assert_eq!(cleared["downloading"], false);
        assert_eq!(cleared["uploading"], false);
        assert_ne!(cleared["status"], "ACTIVE_TRANSFER");
    }

    #[test]
    fn connection_totals_do_not_invent_pre_game_transfer_direction() {
        use std::io::{BufRead, BufReader, Write};
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = String::new();
            BufReader::new(stream.try_clone().unwrap())
                .read_line(&mut request)
                .unwrap();
            let body = r#"{"total":{"inBytesTotal":1000000,"outBytesTotal":1000000},"connections":{"peer":{"connected":true}}}"#;
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .unwrap();
        });
        let api = SyncthingApi::new(&format!("http://{address}"), "fixture-key").unwrap();
        assert_eq!(
            get_connection_snapshot(&api).unwrap(),
            HashSet::from(["peer".to_owned()])
        );
        server.join().unwrap();
        let now = Instant::now();
        let local = LocalActivity {
            last_local_index: Some(now),
            last_sequence_change: Some(now),
            ..LocalActivity::default()
        };
        let sample = sample_for_test(
            "sync-waiting",
            &FolderRuntime::default(),
            &local,
            &HashMap::new(),
            &HashMap::new(),
            false,
            now,
        );
        assert_eq!(sample["downloading"], false);
        assert_eq!(sample["uploading"], false);
        assert_ne!(sample["status"], "ACTIVE_TRANSFER");
    }

    #[test]
    fn settlement_uses_quiet_window_and_pre_game_ignores_peer_needs() {
        let now = Instant::now();
        let mut peers = HashMap::new();
        peers.insert(
            "peer".to_owned(),
            PeerCompletion {
                observed: now,
                need_bytes: 100,
                need_items: 1,
                need_deletes: 0,
            },
        );
        let local = LocalActivity {
            last_local_change: Some(now),
            last_scan_progress: Some(now),
            ..LocalActivity::default()
        };
        let runtime = FolderRuntime::default();
        let remote = HashMap::new();
        let recent = sample_for_test("idle", &runtime, &local, &remote, &peers, false, now);
        assert_eq!(recent["settled"], false);
        assert_eq!(recent["uploading"], false);
        let quiet = sample_for_test(
            "idle",
            &runtime,
            &local,
            &remote,
            &peers,
            false,
            now + Duration::from_secs(4),
        );
        assert_eq!(quiet["settled"], true);
        assert_eq!(quiet["update_in_progress"], true);
        assert_eq!(quiet["status"], "SCANNING");

        let post_game = LocalActivity {
            last_local_change: Some(now),
            last_scan_progress: Some(now),
            outbound_index_observed: Some(now),
            outbound_hold_deadline: Some(now + OUTBOUND_HOLD),
            ..LocalActivity::default()
        };
        let incomplete = sample_for_test(
            "idle",
            &runtime,
            &post_game,
            &remote,
            &peers,
            true,
            now + Duration::from_secs(4),
        );
        assert_eq!(incomplete["uploading"], true);
        assert_eq!(incomplete["settled"], false);
        peers.get_mut("peer").unwrap().need_bytes = 0;
        peers.get_mut("peer").unwrap().need_items = 0;
        for (seconds, uploading, settled) in [(2, true, false), (4, false, true)] {
            let sample = sample_for_test(
                "idle",
                &runtime,
                &post_game,
                &remote,
                &peers,
                true,
                now + Duration::from_secs(seconds),
            );
            assert_eq!(sample["uploading"], uploading);
            assert_eq!(sample["settled"], settled);
        }

        let index_only = LocalActivity {
            last_local_index: Some(now),
            last_sequence_change: Some(now),
            ..LocalActivity::default()
        };
        let deletes = FolderRuntime {
            need_deletes: 46,
            need_total_items: 46,
            ..FolderRuntime::default()
        };
        let preparing = sample_for_test(
            "sync-preparing",
            &deletes,
            &index_only,
            &remote,
            &peers,
            false,
            now,
        );
        assert_eq!(preparing["settled"], true);
        assert_eq!(preparing["update_in_progress"], true);
        assert_eq!(preparing["status"], "PREPARING");
        let content = FolderRuntime {
            need_files: 1,
            ..FolderRuntime::default()
        };
        assert_eq!(
            sample_for_test(
                "sync-preparing",
                &content,
                &index_only,
                &remote,
                &peers,
                false,
                now
            )["settled"],
            false
        );
        let error = FolderRuntime {
            watch_error: "watch failed".to_owned(),
            ..FolderRuntime::default()
        };
        assert_eq!(
            sample_for_test(
                "sync-preparing",
                &error,
                &index_only,
                &remote,
                &peers,
                false,
                now
            )["settled"],
            false
        );
        for state in ["syncing", "scanning", "error", "paused"] {
            assert_eq!(
                sample_for_test(
                    state,
                    &runtime,
                    &LocalActivity::default(),
                    &remote,
                    &peers,
                    false,
                    now
                )["settled"],
                false,
                "{state}"
            );
        }
    }

    #[test]
    fn folder_runtime_does_not_gate_on_deletes() {
        let runtime = parse_folder_runtime(
            &json!({"needFiles":2,"needDirectories":3,"needSymlinks":5,"needDeletes":46,"needTotalItems":56}),
        );
        assert_eq!(runtime.content_needed(), 10);
        assert_eq!(runtime.need_total_items, 56);
        assert_eq!(runtime.need_deletes, 46);
    }
}
