use super::*;
#[derive(Clone)]
pub(super) struct SyncthingApi {
    base_url: Url,
    key: String,
    client: Client,
}

impl SyncthingApi {
    pub(super) fn new(base_url: &str, key: &str) -> Result<Self, String> {
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

    pub(super) fn get_json(
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

pub(super) fn is_loopback_url(url: &Url) -> bool {
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
pub(super) struct FolderSelection {
    pub(super) id: String,
    pub(super) label: String,
    pub(super) path: PathBuf,
    pub(super) device_ids: Vec<String>,
    pub(super) watcher_enabled: Option<bool>,
    pub(super) watcher_delay: Option<u64>,
    pub(super) rescan_interval: Option<u64>,
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

pub(super) fn resolve_folder(
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
fn get_json(
    api: &SyncthingApi,
    path: &str,
    params: &[(&str, String)],
    timeout: Duration,
) -> Result<Value, String> {
    api.get_json(path, params, timeout)
}

pub(super) fn get_connection_snapshot(api: &SyncthingApi) -> Result<HashSet<String>, String> {
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

pub(super) fn get_my_device_id(api: &SyncthingApi) -> Result<String, String> {
    let data = get_json(api, "/rest/system/status", &[], Duration::from_secs(10))?;
    data.get("myID")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| "Unexpected system status response: missing myID".to_owned())
}
pub(super) fn get_folder_status(api: &SyncthingApi, folder_id: &str) -> Result<Value, String> {
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
    fn nested_folder_match_uses_longest_containing_path() {
        let parent = normalize_path("/tmp");
        let nested = normalize_path("/tmp/sdh_ludusavi");
        let backup = normalize_path("/tmp/sdh_ludusavi/backups");
        assert!(backup.starts_with(&parent));
        assert!(backup.starts_with(&nested));
        assert!(nested.as_os_str().len() > parent.as_os_str().len());
    }
}
