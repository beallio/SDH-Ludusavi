use super::*;
pub(super) fn folder_detection_grace_ms(folder: &FolderSelection) -> u64 {
    let base = if folder.watcher_enabled == Some(false) {
        folder.rescan_interval.unwrap_or(3600)
    } else {
        folder.watcher_delay.unwrap_or(10)
    };
    base.saturating_add(20).clamp(30, 120) * 1000
}

#[derive(Clone, Default)]
pub(super) struct FolderRuntime {
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

pub(super) fn parse_folder_runtime(data: &Value) -> FolderRuntime {
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
pub(super) struct PeerCompletion {
    pub(super) observed: Instant,
    pub(super) need_bytes: u64,
    pub(super) need_items: u64,
    need_deletes: u64,
}

pub(super) fn parse_peer_completion(
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
#[derive(Default)]
pub(super) struct LocalActivity {
    last_local_change: Option<Instant>,
    last_local_index: Option<Instant>,
    last_sequence_change: Option<Instant>,
    pub(super) last_scan_progress: Option<Instant>,
    pub(super) last_download_progress: Option<Instant>,
    last_item_finished: Option<Instant>,
    pub(super) outbound_index_observed: Option<Instant>,
    outbound_hold_deadline: Option<Instant>,
    pub(super) active_download_files: usize,
    pub(super) active_items: HashMap<String, Instant>,
}

pub(super) struct RemoteProgress {
    file_count: usize,
    pub(super) observed: Instant,
}
pub(super) fn apply_folder_status(
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
pub(super) fn process_event(
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
pub(super) fn publish_sample(
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

#[cfg(test)]
mod tests {
    use super::*;
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
