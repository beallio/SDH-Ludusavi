use std::{
    cmp::Ordering,
    collections::BTreeMap,
    sync::{Arc, Mutex, MutexGuard},
    time::{Duration, Instant},
};

use crate::{
    http::block_on,
    persistence::{StateLock, existing_mode, read_object, write_json_atomic},
};
use reqwest::{
    Client,
    header::{ACCEPT, HeaderMap, HeaderValue, USER_AGENT},
};
use serde_json::{Map, Value, json};
use time::{Duration as TimeDuration, OffsetDateTime, format_description::well_known::Rfc3339};

const OWNER: &str = "beallio";
const REPOSITORY: &str = "SDH-Ludusavi";
const MAX_MANIFEST_FETCH_ATTEMPTS: usize = 5;
const PENDING_INSTALL_MISMATCH_GRACE: TimeDuration = TimeDuration::minutes(15);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Clone, Debug)]
struct JsonResponse {
    status: u16,
    headers: BTreeMap<String, String>,
    body: Value,
}

trait ReleaseClient: Send + Sync {
    fn list_releases(&self) -> JsonResponse;
    fn get_release(&self, tag: &str) -> JsonResponse;
    fn get_manifest(&self, url: &str) -> JsonResponse;
}

struct GitHubReleaseClient {
    client: Client,
    user_agent: HeaderValue,
}

impl GitHubReleaseClient {
    fn new(version: &str) -> Result<Self, String> {
        let mut headers = HeaderMap::new();
        headers.insert(
            ACCEPT,
            HeaderValue::from_static("application/vnd.github+json"),
        );
        headers.insert(
            "x-github-api-version",
            HeaderValue::from_static("2026-03-10"),
        );
        let user_agent = HeaderValue::from_str(&format!("SDH-Ludusavi/{version}"))
            .map_err(|error| error.to_string())?;
        let client = Client::builder()
            .default_headers(headers)
            .timeout(REQUEST_TIMEOUT)
            .build()
            .map_err(|error| error.to_string())?;
        Ok(Self { client, user_agent })
    }
    fn fetch(&self, url: &str) -> JsonResponse {
        let response = match block_on(
            self.client
                .get(url)
                .header(USER_AGENT, &self.user_agent)
                .send(),
        )
        .and_then(|response| response.map_err(|error| error.to_string()))
        {
            Ok(response) => response,
            Err(error) => {
                return JsonResponse {
                    status: 500,
                    headers: BTreeMap::new(),
                    body: json!({"error": error}),
                };
            }
        };
        let status = response.status().as_u16();
        let headers = response
            .headers()
            .iter()
            .filter_map(|(name, value)| {
                value
                    .to_str()
                    .ok()
                    .map(|value| (name.as_str().to_ascii_lowercase(), value.to_owned()))
            })
            .collect();
        let bytes = match block_on(response.bytes())
            .and_then(|bytes| bytes.map_err(|error| error.to_string()))
        {
            Ok(bytes) => bytes,
            Err(error) => {
                return JsonResponse {
                    status: 500,
                    headers,
                    body: json!({"error": error}),
                };
            }
        };
        let body = if bytes.is_empty() {
            Value::Null
        } else {
            match serde_json::from_slice(&bytes) {
                Ok(body) => body,
                Err(error) if (200..300).contains(&status) => {
                    return JsonResponse {
                        status: 500,
                        headers,
                        body: json!({"error": error.to_string()}),
                    };
                }
                Err(_) => json!({}),
            }
        };
        JsonResponse {
            status,
            headers,
            body,
        }
    }
}

impl ReleaseClient for GitHubReleaseClient {
    fn list_releases(&self) -> JsonResponse {
        self.fetch(&format!(
            "https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases"
        ))
    }

    fn get_release(&self, tag: &str) -> JsonResponse {
        self.fetch(&format!(
            "https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/tags/{tag}"
        ))
    }

    fn get_manifest(&self, url: &str) -> JsonResponse {
        self.fetch(url)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PluginVersion {
    major: u64,
    minor: u64,
    patch: u64,
    development: bool,
}

impl PluginVersion {
    fn base(self) -> (u64, u64, u64) {
        (self.major, self.minor, self.patch)
    }

    fn cmp(self, other: Self) -> Ordering {
        self.base()
            .cmp(&other.base())
            .then_with(|| (!self.development).cmp(&(!other.development)))
    }
}

fn parse_plugin_version(value: &str) -> Option<PluginVersion> {
    let (without_build, build) = match value.split_once('+') {
        Some((version, metadata)) if !metadata.is_empty() && !metadata.contains('+') => {
            if !metadata.bytes().all(version_character) {
                return None;
            }
            (version, Some(metadata))
        }
        Some(_) => return None,
        None => (value, None),
    };
    let _ = build;
    let (base, development_suffix) = match without_build.split_once("-dev.") {
        Some((base, suffix)) if !suffix.is_empty() && suffix.bytes().all(version_character) => {
            (base, Some(suffix))
        }
        Some(_) => return None,
        None => (without_build, None),
    };
    let mut components = base.split('.');
    let major = components.next()?.parse().ok()?;
    let minor = components.next()?.parse().ok()?;
    let patch = components.next()?.parse().ok()?;
    if components.next().is_some()
        || !base
            .bytes()
            .all(|byte| byte.is_ascii_digit() || byte == b'.')
    {
        return None;
    }
    Some(PluginVersion {
        major,
        minor,
        patch,
        development: development_suffix.is_some(),
    })
}

fn version_character(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-')
}

#[derive(Clone)]
struct Candidate {
    version: String,
    tag: String,
    channel: String,
    artifact_url: String,
    sha256: String,
    release_url: String,
    published_at: String,
    action: String,
}

impl Candidate {
    fn to_value(&self) -> Value {
        json!({
            "version": self.version,
            "tag": self.tag,
            "channel": self.channel,
            "artifact_url": self.artifact_url,
            "sha256": self.sha256,
            "release_url": self.release_url,
            "published_at": self.published_at,
            "action": self.action,
        })
    }
}

struct PrevalidatedRelease {
    record: Value,
    tag: String,
    version: PluginVersion,
    published_at: String,
    prerelease: bool,
    manifest_url: String,
    zip_name: String,
    artifact_url: String,
}

fn py_string(value: Option<&Value>) -> String {
    match value {
        None => String::new(),
        Some(Value::String(value)) => value.clone(),
        Some(Value::Null) => "None".to_owned(),
        Some(Value::Bool(true)) => "True".to_owned(),
        Some(Value::Bool(false)) => "False".to_owned(),
        Some(value) => value.to_string(),
    }
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|value| value != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn prevalidate_release_candidate(release: &Value) -> Option<PrevalidatedRelease> {
    let record = release.as_object()?;
    if record.get("draft").is_some_and(truthy) {
        return None;
    }
    let tag = py_string(record.get("tag_name"));
    let version_text = tag.strip_prefix('v')?;
    let version = parse_plugin_version(version_text)?;
    let expected_manifest = format!("SDH-Ludusavi-{tag}.manifest.json");
    let assets = record.get("assets")?.as_array()?;
    let mut manifests = Vec::new();
    let mut zips = Vec::new();
    for asset in assets {
        let Some(asset) = asset.as_object() else {
            continue;
        };
        let name = py_string(asset.get("name"));
        if name == expected_manifest {
            manifests.push(asset);
        } else if name.ends_with(".zip") {
            zips.push(asset);
        }
    }
    if manifests.len() != 1 || zips.len() != 1 {
        return None;
    }
    Some(PrevalidatedRelease {
        record: release.clone(),
        tag,
        version,
        published_at: py_string(record.get("published_at")),
        prerelease: record.get("prerelease").is_some_and(truthy),
        manifest_url: py_string(manifests[0].get("browser_download_url")),
        zip_name: py_string(zips[0].get("name")),
        artifact_url: py_string(zips[0].get("browser_download_url")),
    })
}

struct ReleaseManifest {
    plugin_name: String,
    package_name: String,
    version: String,
    tag: String,
    channel: String,
    asset_name: String,
    sha256: String,
}

fn parse_manifest(value: &Value) -> Option<ReleaseManifest> {
    let record = value.as_object()?;
    if record.get("schemaVersion").and_then(Value::as_u64) != Some(1) {
        return None;
    }
    let channel = record.get("channel")?.as_str()?;
    if !matches!(channel, "stable" | "dev") {
        return None;
    }
    let sha256 = record.get("sha256")?.as_str()?;
    if sha256.len() != 64 || !sha256.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }
    Some(ReleaseManifest {
        plugin_name: record.get("pluginName")?.as_str()?.to_owned(),
        package_name: record.get("packageName")?.as_str()?.to_owned(),
        version: record.get("version")?.as_str()?.to_owned(),
        tag: record.get("tag")?.as_str()?.to_owned(),
        channel: channel.to_owned(),
        asset_name: record.get("assetName")?.as_str()?.to_owned(),
        sha256: sha256.to_owned(),
    })
}

fn validate_prevalidated_candidate(
    pre: &PrevalidatedRelease,
    client: &dyn ReleaseClient,
) -> Option<Candidate> {
    let response = client.get_manifest(&pre.manifest_url);
    if response.status != 200 {
        return None;
    }
    let manifest = parse_manifest(&response.body)?;
    if manifest.plugin_name != "SDH-Ludusavi"
        || manifest.package_name != "sdh-ludusavi"
        || manifest.tag != pre.tag
        || format!("v{}", manifest.version) != pre.tag
        || (manifest.channel == "stable" && pre.prerelease)
        || (manifest.channel == "dev" && !pre.prerelease)
        || pre.zip_name != manifest.asset_name
    {
        return None;
    }
    let record = pre.record.as_object()?;
    Some(Candidate {
        version: manifest.version,
        tag: manifest.tag,
        channel: if manifest.channel == "stable" {
            "stable"
        } else {
            "development"
        }
        .to_owned(),
        artifact_url: pre.artifact_url.clone(),
        sha256: manifest.sha256,
        release_url: py_string(record.get("html_url")),
        published_at: pre.published_at.clone(),
        action: "update".to_owned(),
    })
}

fn compare_release(left: &PrevalidatedRelease, right: &PrevalidatedRelease) -> Ordering {
    right
        .version
        .base()
        .cmp(&left.version.base())
        .then_with(|| left.version.development.cmp(&right.version.development))
        .then_with(|| right.published_at.cmp(&left.published_at))
}

fn select_candidate(
    mut candidates: Vec<Candidate>,
    installed_text: &str,
    preferred_channel: &str,
) -> Option<Candidate> {
    let installed = parse_plugin_version(installed_text)?;
    candidates.retain(|candidate| {
        (preferred_channel != "stable" || candidate.channel == "stable")
            && parse_plugin_version(&candidate.version).is_some()
    });
    candidates.sort_by(|left, right| {
        let left_version = parse_plugin_version(&left.version).expect("filtered version");
        let right_version = parse_plugin_version(&right.version).expect("filtered version");
        right_version
            .base()
            .cmp(&left_version.base())
            .then_with(|| left_version.development.cmp(&right_version.development))
            .then_with(|| right.published_at.cmp(&left.published_at))
    });
    let mut best = candidates.into_iter().next()?;
    let best_version = parse_plugin_version(&best.version)?;
    let best_base = best_version.base();
    let installed_base = installed.base();
    let mut upgrade = false;
    let mut action = "update";

    if preferred_channel == "stable" && installed.development {
        upgrade = true;
        if best_base == installed_base {
            action = "move_to_stable";
        } else if best_base < installed_base {
            action = "downgrade_to_stable";
        }
    } else {
        match best_version.cmp(installed) {
            Ordering::Greater => {
                upgrade = true;
                if !best_version.development && installed.development && best_base == installed_base
                {
                    action = "move_to_stable";
                }
            }
            Ordering::Equal => {
                if best_version.development && installed.development {
                    if best.version != installed_text {
                        upgrade = true;
                    }
                } else if !best_version.development && installed.development {
                    upgrade = true;
                    action = "move_to_stable";
                }
            }
            Ordering::Less => (),
        }
    }
    if upgrade {
        best.action = action.to_owned();
        Some(best)
    } else {
        None
    }
}

fn format_time(value: OffsetDateTime) -> String {
    value
        .format(&Rfc3339)
        .unwrap_or_else(|_| "1970-01-01T00:00:00Z".to_owned())
}

fn parse_time(value: &str) -> Option<OffsetDateTime> {
    OffsetDateTime::parse(value, &Rfc3339).ok().or_else(|| {
        (!value.ends_with('Z') && !value.contains('+') && !value.rsplit_once('T')?.1.contains('-'))
            .then(|| OffsetDateTime::parse(&format!("{value}Z"), &Rfc3339).ok())
            .flatten()
    })
}

fn retry_after(headers: &BTreeMap<String, String>, now: OffsetDateTime) -> String {
    if headers.contains_key("retry-after") {
        if let Some(value) = headers
            .get("retry-after")
            .and_then(|value| value.parse::<i64>().ok())
            .and_then(|seconds| now.checked_add(TimeDuration::seconds(seconds)))
        {
            return format_time(value);
        }
    } else if let Some(timestamp) = headers
        .get("x-ratelimit-reset")
        .and_then(|value| value.parse::<i64>().ok())
        && let Ok(value) = OffsetDateTime::from_unix_timestamp(timestamp)
    {
        return format_time(value);
    }
    format_time(now + TimeDuration::minutes(1))
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

pub struct PluginUpdater {
    client: Arc<dyn ReleaseClient>,
    state_lock: Arc<StateLock>,
    cache_path: std::path::PathBuf,
    cache: Mutex<Map<String, Value>>,
    rate_limited_until: Mutex<Option<OffsetDateTime>>,
    installed_version: String,
}

impl PluginUpdater {
    pub fn new(
        state_lock: Arc<StateLock>,
        cache_path: std::path::PathBuf,
        root_cache: &Map<String, Value>,
        installed_version: String,
    ) -> Result<Self, String> {
        let client = Arc::new(GitHubReleaseClient::new(&installed_version)?);
        Ok(Self::with_client(
            state_lock,
            cache_path,
            root_cache,
            installed_version,
            client,
        ))
    }

    fn with_client(
        state_lock: Arc<StateLock>,
        cache_path: std::path::PathBuf,
        root_cache: &Map<String, Value>,
        installed_version: String,
        client: Arc<dyn ReleaseClient>,
    ) -> Self {
        let mut cache = root_cache
            .get("update_check_cache")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        if cache
            .get("pending_update_install")
            .is_some_and(|pending| !pending.is_object() || pending.get("version").is_none())
        {
            cache.remove("pending_update_install");
        }
        for key in ["last_checked_at", "installed_release_published_at"] {
            if cache.get(key).is_some_and(|value| !value.is_string()) {
                cache.remove(key);
            }
        }
        if cache
            .get("last_result")
            .is_some_and(|value| !value.is_object())
        {
            cache.remove("last_result");
        }
        Self {
            client,
            state_lock,
            cache_path,
            cache: Mutex::new(cache),
            rate_limited_until: Mutex::new(None),
            installed_version,
        }
    }

    fn save(&self) -> Result<(), String> {
        let update_cache = Value::Object(lock(&self.cache).clone());
        self.state_lock
            .with_lock(|| {
                let mut root = read_object(&self.cache_path)?.unwrap_or_default();
                root.insert("update_check_cache".to_owned(), update_cache);
                let mode = existing_mode(&self.cache_path, 0o600)?;
                write_json_atomic(&self.cache_path, &root, mode, b"  ")
            })
            .map_err(|error| error.to_string())
    }

    pub fn context(&self, settings: &Map<String, Value>) -> Value {
        let now = OffsetDateTime::now_utc();
        let rate_limited_until = {
            let mut value = lock(&self.rate_limited_until);
            if value.is_some_and(|until| now >= until) {
                *value = None;
            }
            value.map(format_time)
        };
        let cache = lock(&self.cache);
        let pending = cache.get("pending_update_install").cloned();
        let effective_version = pending
            .as_ref()
            .and_then(|pending| effective_pending_version(pending, now))
            .unwrap_or_else(|| self.installed_version.clone());
        json!({
            "update_channel": setting_channel(settings),
            "automatic_update_checks": settings.get("automatic_update_checks").and_then(Value::as_bool).unwrap_or(true),
            "installed_version": self.installed_version,
            "effective_installed_version": effective_version,
            "last_checked_at": cache.get("last_checked_at"),
            "last_checked_channel": cache.get("last_checked_channel"),
            "last_available_tag": cache.get("last_available_tag"),
            "last_notified_tag": cache.get("last_notified_tag"),
            "installed_release_tag": cache.get("installed_release_tag"),
            "installed_release_published_at": cache.get("installed_release_published_at"),
            "pending_update_install": pending,
            "rate_limited_until": rate_limited_until,
        })
    }

    pub fn check_for_update(
        &self,
        settings: &Map<String, Value>,
        current_version: &str,
        force: bool,
    ) -> Result<Value, String> {
        let started = Instant::now();
        let channel = setting_channel(settings);
        let now = OffsetDateTime::now_utc();
        {
            let cache = lock(&self.cache);
            if !force
                && cache
                    .get("pending_update_install")
                    .and_then(|pending| effective_pending_version(pending, now))
                    .as_deref()
                    == Some(current_version)
            {
                return Ok(json!({"status":"current", "checked_at":format_time(now)}));
            }
        }
        if let Some(until) = *lock(&self.rate_limited_until)
            && now < until
        {
            return Ok(
                json!({"status":"failed", "checked_at":format_time(now), "message":"Update check skipped due to rate-limit cooldown", "retry_after":format_time(until)}),
            );
        }
        if !force {
            let cache = lock(&self.cache);
            if let (Some(last_checked), Some(last_channel), Some(last_version)) = (
                cache
                    .get("last_checked_at")
                    .and_then(Value::as_str)
                    .and_then(parse_time),
                cache.get("last_checked_channel").and_then(Value::as_str),
                cache.get("last_checked_version").and_then(Value::as_str),
            ) && now - last_checked < TimeDuration::hours(24)
                && last_channel == channel
                && last_version == current_version
                && let Some(result) = cache.get("last_result").and_then(Value::as_object)
            {
                let mut result = result.clone();
                result.remove("checked_version");
                return Ok(Value::Object(result));
            }
        }

        let response = self.client.list_releases();
        let checked_at = format_time(OffsetDateTime::now_utc());
        if matches!(response.status, 403 | 429) {
            let retry = retry_after(&response.headers, OffsetDateTime::now_utc());
            *lock(&self.rate_limited_until) = parse_time(&retry);
            let message = response
                .body
                .get("message")
                .map(|value| py_string(Some(value)))
                .unwrap_or_else(|| "Rate limit exceeded".to_owned());
            return Ok(
                json!({"status":"failed", "checked_at":checked_at, "message":message, "retry_after":retry}),
            );
        }
        let Some(releases) = response.body.as_array().filter(|_| response.status == 200) else {
            let message = response
                .body
                .get("message")
                .or_else(|| response.body.get("error"))
                .map(|value| py_string(Some(value)))
                .unwrap_or_else(|| "Failed to check for updates".to_owned());
            return Ok(json!({"status":"failed", "checked_at":checked_at, "message":message}));
        };
        let mut prevalidated = releases
            .iter()
            .filter_map(prevalidate_release_candidate)
            .filter(|release| channel != "stable" || !release.prerelease)
            .collect::<Vec<_>>();
        prevalidated.sort_by(compare_release);
        let mut validated = Vec::new();
        for release in prevalidated.iter().take(MAX_MANIFEST_FETCH_ATTEMPTS) {
            if let Some(candidate) = validate_prevalidated_candidate(release, self.client.as_ref())
            {
                validated.push(candidate);
                break;
            }
        }
        let candidate = select_candidate(validated, current_version, channel);
        let result = if let Some(candidate) = &candidate {
            json!({"status":"available", "checked_at":checked_at, "checked_version":current_version, "candidate":candidate.to_value()})
        } else {
            json!({"status":"current", "checked_at":checked_at, "checked_version":current_version, "channel":channel})
        };
        {
            let mut cache = lock(&self.cache);
            cache.insert("last_checked_at".to_owned(), json!(checked_at));
            cache.insert("last_checked_channel".to_owned(), json!(channel));
            cache.insert("last_checked_version".to_owned(), json!(current_version));
            cache.insert("last_result".to_owned(), result.clone());
            if let Some(candidate) = candidate {
                cache.insert("last_available_tag".to_owned(), json!(candidate.tag));
            }
        }
        self.save()?;
        let mut public_result = result;
        public_result
            .as_object_mut()
            .unwrap()
            .remove("checked_version");
        log::info!(
            "Plugin update check completed in {}ms",
            started.elapsed().as_millis()
        );
        Ok(public_result)
    }

    pub fn revalidate(&self, candidate: &Value) -> Result<Value, String> {
        let started = Instant::now();
        let now = OffsetDateTime::now_utc();
        if let Some(until) = *lock(&self.rate_limited_until) {
            if now < until {
                return Ok(
                    json!({"status":"failed", "checked_at":format_time(now), "message":"Rate limit cooldown active", "retry_after":format_time(until)}),
                );
            }
            *lock(&self.rate_limited_until) = None;
            self.save()?;
        }
        let Some(tag) = candidate.get("tag").and_then(Value::as_str) else {
            return Ok(
                json!({"status":"failed", "checked_at":format_time(now), "message":"Candidate missing tag"}),
            );
        };
        let response = self.client.get_release(tag);
        let checked_at = format_time(OffsetDateTime::now_utc());
        if matches!(response.status, 403 | 429) {
            let retry = retry_after(&response.headers, OffsetDateTime::now_utc());
            *lock(&self.rate_limited_until) = parse_time(&retry);
            self.save()?;
            let message = response
                .body
                .get("message")
                .map(|value| py_string(Some(value)))
                .unwrap_or_else(|| "Rate limit exceeded".to_owned());
            return Ok(
                json!({"status":"failed", "checked_at":checked_at, "message":message, "retry_after":retry}),
            );
        }
        if response.status != 200 || !response.body.is_object() {
            return Ok(
                json!({"status":"failed", "checked_at":checked_at, "message":format!("Failed to fetch release for tag {tag}: {}", response.status)}),
            );
        }
        let Some(validated) = prevalidate_release_candidate(&response.body)
            .and_then(|release| validate_prevalidated_candidate(&release, self.client.as_ref()))
        else {
            return Ok(
                json!({"status":"failed", "checked_at":checked_at, "message":"Release validation failed during revalidation"}),
            );
        };
        if validated.sha256
            != candidate
                .get("sha256")
                .and_then(Value::as_str)
                .unwrap_or("")
        {
            return Ok(
                json!({"status":"failed", "checked_at":checked_at, "message":"SHA-256 mismatch during revalidation"}),
            );
        }
        if validated.artifact_url
            != candidate
                .get("artifact_url")
                .and_then(Value::as_str)
                .unwrap_or("")
        {
            return Ok(
                json!({"status":"failed", "checked_at":checked_at, "message":"Artifact URL mismatch during revalidation"}),
            );
        }
        if validated.version
            != candidate
                .get("version")
                .and_then(Value::as_str)
                .unwrap_or("")
        {
            return Ok(
                json!({"status":"failed", "checked_at":checked_at, "message":"Version mismatch during revalidation"}),
            );
        }
        let mut result = validated.to_value();
        result["action"] = candidate
            .get("action")
            .cloned()
            .unwrap_or_else(|| json!("update"));
        log::info!(
            "Plugin update revalidation completed in {}ms",
            started.elapsed().as_millis()
        );
        Ok(result)
    }

    pub fn record_install_requested(
        &self,
        candidate: &Value,
        settings: &Map<String, Value>,
    ) -> Result<Value, String> {
        let mut cache = lock(&self.cache);
        cache.insert(
            "pending_update_install".to_owned(),
            json!({
                "version": candidate.get("version"),
                "tag": candidate.get("tag"),
                "channel": candidate.get("channel"),
                "published_at": candidate.get("published_at"),
                "requested_at": format_time(OffsetDateTime::now_utc()),
                "update_trace_id": candidate.get("updateTraceId"),
            }),
        );
        clear_stale_cache(&mut cache);
        drop(cache);
        self.save()?;
        Ok(self.context(settings))
    }

    pub fn confirm_install_handoff(
        &self,
        version: &str,
        settings: &Map<String, Value>,
    ) -> Result<Value, String> {
        let mut cache = lock(&self.cache);
        if let Some(pending) = cache
            .get_mut("pending_update_install")
            .and_then(Value::as_object_mut)
            .filter(|pending| pending.get("version").and_then(Value::as_str) == Some(version))
        {
            pending.insert(
                "handoff_confirmed_at".to_owned(),
                json!(format_time(OffsetDateTime::now_utc())),
            );
            clear_stale_cache(&mut cache);
            drop(cache);
            self.save()?;
        }
        Ok(self.context(settings))
    }

    pub fn mark_notified(&self, tag: &str, settings: &Map<String, Value>) -> Result<Value, String> {
        lock(&self.cache).insert("last_notified_tag".to_owned(), json!(tag));
        self.save()?;
        Ok(self.context(settings))
    }

    pub fn clear_pending_install(
        &self,
        version: Option<&str>,
        settings: &Map<String, Value>,
    ) -> Result<Value, String> {
        let mut cache = lock(&self.cache);
        let pending_version = cache
            .get("pending_update_install")
            .and_then(|pending| pending.get("version"))
            .and_then(Value::as_str);
        if cache.get("pending_update_install").is_some()
            && (version.is_none() || pending_version == version)
        {
            cache.remove("pending_update_install");
            clear_stale_cache(&mut cache);
            drop(cache);
            self.save()?;
        }
        Ok(self.context(settings))
    }

    pub fn reconcile_pending_install(&self, current_version: &str) -> Result<(), String> {
        let mut cache = lock(&self.cache);
        let Some(pending) = cache.get("pending_update_install").cloned() else {
            return Ok(());
        };
        let pending_version = pending.get("version").and_then(Value::as_str).unwrap_or("");
        if pending_install_matches_loaded_version(pending_version, current_version) {
            cache.insert(
                "installed_release_tag".to_owned(),
                pending.get("tag").cloned().unwrap_or(Value::Null),
            );
            cache.insert(
                "installed_release_published_at".to_owned(),
                pending.get("published_at").cloned().unwrap_or(Value::Null),
            );
            cache.remove("pending_update_install");
            clear_stale_cache(&mut cache);
            drop(cache);
            self.save()?;
        } else if !is_fresh_pending_install(&pending, OffsetDateTime::now_utc()) {
            cache.remove("pending_update_install");
            clear_stale_cache(&mut cache);
            drop(cache);
            self.save()?;
        }
        Ok(())
    }

    pub fn has_pending_install(&self) -> bool {
        lock(&self.cache)
            .get("pending_update_install")
            .is_some_and(|pending| {
                effective_pending_version(pending, OffsetDateTime::now_utc()).is_some()
            })
    }
}

fn setting_channel(settings: &Map<String, Value>) -> &'static str {
    match settings.get("update_channel").and_then(Value::as_str) {
        Some("development") => "development",
        _ => "stable",
    }
}

fn clear_stale_cache(cache: &mut Map<String, Value>) {
    for key in [
        "last_result",
        "last_available_tag",
        "last_notified_tag",
        "last_checked_version",
    ] {
        cache.remove(key);
    }
}

fn is_fresh_pending_install(pending: &Value, now: OffsetDateTime) -> bool {
    let Some(object) = pending.as_object() else {
        return false;
    };
    let timestamp = if object
        .get("handoff_confirmed_at")
        .and_then(Value::as_str)
        .is_some_and(|value| !value.is_empty())
    {
        object.get("handoff_confirmed_at").and_then(Value::as_str)
    } else {
        object.get("requested_at").and_then(Value::as_str)
    };
    let Some(requested) = timestamp.and_then(parse_time) else {
        return false;
    };
    now - requested <= PENDING_INSTALL_MISMATCH_GRACE
}

fn effective_pending_version(pending: &Value, now: OffsetDateTime) -> Option<String> {
    is_fresh_pending_install(pending, now)
        .then(|| {
            pending
                .get("version")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .map(str::to_owned)
        })
        .flatten()
}

fn pending_install_matches_loaded_version(pending: &str, current: &str) -> bool {
    if pending == current {
        return true;
    }
    match (parse_plugin_version(pending), parse_plugin_version(current)) {
        (Some(pending), Some(current)) => {
            !current.development && !pending.development && pending == current
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use std::{
        collections::BTreeMap,
        fs,
        sync::{Arc, Mutex},
    };

    use serde_json::{Value, json};
    use tempfile::tempdir_in;
    use time::{OffsetDateTime, format_description::well_known::Rfc3339};

    use crate::persistence::StateLock;

    use super::{
        JsonResponse, PluginUpdater, ReleaseClient, parse_plugin_version,
        pending_install_matches_loaded_version, retry_after,
    };

    struct FixtureClient {
        releases: Value,
        manifests: Value,
        tag_release: Value,
        revalidation_manifest: Value,
        attempts: Mutex<Vec<String>>,
    }

    impl ReleaseClient for FixtureClient {
        fn list_releases(&self) -> JsonResponse {
            JsonResponse {
                status: 200,
                headers: BTreeMap::new(),
                body: self.releases.clone(),
            }
        }
        fn get_release(&self, _tag: &str) -> JsonResponse {
            JsonResponse {
                status: 200,
                headers: BTreeMap::new(),
                body: self.tag_release.clone(),
            }
        }
        fn get_manifest(&self, url: &str) -> JsonResponse {
            self.attempts.lock().unwrap().push(url.to_owned());
            let body = self
                .manifests
                .get(url)
                .cloned()
                .unwrap_or_else(|| self.revalidation_manifest.clone());
            JsonResponse {
                status: 200,
                headers: BTreeMap::new(),
                body,
            }
        }
    }

    fn fixture() -> Value {
        serde_json::from_str(include_str!(
            "../../tests/contract/fixtures/github/recorded.json"
        ))
        .unwrap()
    }

    fn updater(
        data: &Value,
        case: &Value,
    ) -> (tempfile::TempDir, PluginUpdater, Arc<FixtureClient>) {
        let directory = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let runtime = directory.path().join("runtime");
        fs::create_dir_all(&runtime).unwrap();
        let cache_path = runtime.join("cache.json");
        let lock = Arc::new(StateLock::new(&cache_path).unwrap());
        let client = Arc::new(FixtureClient {
            releases: case.get("releases").cloned().unwrap_or(Value::Null),
            manifests: case.get("manifests").cloned().unwrap_or(Value::Null),
            tag_release: data
                .pointer("/revalidation/release")
                .cloned()
                .unwrap_or(Value::Null),
            revalidation_manifest: data
                .pointer("/revalidation/manifest")
                .cloned()
                .unwrap_or(Value::Null),
            attempts: Mutex::new(Vec::new()),
        });
        let updater = PluginUpdater::with_client(
            lock,
            cache_path,
            &serde_json::Map::new(),
            "0.5.0".to_owned(),
            client.clone(),
        );
        (directory, updater, client)
    }

    #[test]
    fn recorded_github_release_results_match_python_fixtures() {
        let data = fixture();
        for case in data["checks"].as_array().unwrap() {
            let (_directory, updater, client) = updater(&data, case);
            let mut settings = serde_json::Map::new();
            settings.insert("update_channel".to_owned(), case["channel"].clone());
            let result = updater
                .check_for_update(&settings, case["installed_version"].as_str().unwrap(), true)
                .unwrap();
            assert_eq!(
                result["status"], case["expected"]["status"],
                "{}",
                case["name"]
            );
            if let Some(candidate) = case["expected"].get("candidate") {
                assert_eq!(result["candidate"], *candidate, "{}", case["name"]);
            }
            if let Some(expected) = case
                .get("expected_manifest_attempts")
                .and_then(Value::as_u64)
            {
                assert_eq!(
                    client.attempts.lock().unwrap().len(),
                    expected as usize,
                    "{}",
                    case["name"]
                );
            }
        }
    }

    #[test]
    fn recorded_revalidation_rejects_sha256_mismatch() {
        let data = fixture();
        let (_directory, updater, _) = updater(&data, &Value::Null);
        let expected = updater
            .revalidate(&data["revalidation"]["candidate"])
            .unwrap();
        assert_eq!(expected, data["revalidation"]["expected"]);
        let mut mismatch = data["revalidation"]["candidate"].clone();
        mismatch["sha256"] = json!("f".repeat(64));
        let rejected = updater.revalidate(&mismatch).unwrap();
        assert_eq!(rejected["message"], "SHA-256 mismatch during revalidation");
    }

    #[test]
    fn versions_and_retry_after_follow_python_tables() {
        for (version, valid) in [
            ("1.2.3", true),
            ("1.2.3-dev.g123+build", true),
            ("1.2", false),
            ("1.2.3-dev.", false),
            ("1.2.3+", false),
            ("1.2.3-dev.x/y", false),
        ] {
            assert_eq!(parse_plugin_version(version).is_some(), valid, "{version}");
        }
        assert!(pending_install_matches_loaded_version(
            "1.2.3+g123",
            "1.2.3"
        ));
        assert!(!pending_install_matches_loaded_version(
            "1.2.3-dev.g1",
            "1.2.3"
        ));
        let now = OffsetDateTime::parse("2025-01-01T12:00:00Z", &Rfc3339).unwrap();
        for (headers, expected) in [
            (BTreeMap::new(), "2025-01-01T12:01:00Z"),
            (
                BTreeMap::from([("retry-after".to_owned(), "120".to_owned())]),
                "2025-01-01T12:02:00Z",
            ),
            (
                BTreeMap::from([("x-ratelimit-reset".to_owned(), "1735733100".to_owned())]),
                "2025-01-01T12:05:00Z",
            ),
            (
                BTreeMap::from([
                    ("retry-after".to_owned(), "invalid".to_owned()),
                    ("x-ratelimit-reset".to_owned(), "1735733100".to_owned()),
                ]),
                "2025-01-01T12:01:00Z",
            ),
        ] {
            assert_eq!(retry_after(&headers, now), expected);
        }
    }
}
