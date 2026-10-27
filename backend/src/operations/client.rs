use super::*;
pub(super) struct LudusaviClient {
    pub(super) processes: Arc<ProcessManager>,
    pub(super) flatpak: PathBuf,
    pub(super) deployment: Option<PathBuf>,
    pub(super) execution_failed: AtomicBool,
    pub(super) config_path: Mutex<Option<PathBuf>>,
    pub(super) version: Mutex<Option<String>>,
}

impl LudusaviClient {
    pub(super) fn new(processes: Arc<ProcessManager>) -> Result<Self, String> {
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

    pub(super) fn json(&self, args: &[String], timeout: Duration) -> Result<Value, String> {
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

    pub(super) fn version(&self) -> Result<String, String> {
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

    pub(super) fn backup_preview(&self, game: Option<&str>) -> Result<Value, String> {
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

    pub(super) fn backups(&self, game: Option<&str>) -> Result<Value, String> {
        let mut args = vec!["backups".to_owned()];
        if let Some(game) = game {
            args.push(game.to_owned());
        }
        self.json(&args, BACKUPS_TIMEOUT)
    }

    pub(super) fn backup(&self, game: &str, preview: bool) -> Result<Value, String> {
        let mut args = vec!["backup".to_owned()];
        if preview {
            args.push("--preview".to_owned());
        }
        args.extend(["--force".to_owned(), game.to_owned()]);
        self.json(&args, OPERATION_TIMEOUT)
    }

    pub(super) fn restore(&self, game: &str, preview: bool) -> Result<Value, String> {
        let mut args = vec!["restore".to_owned()];
        if preview {
            args.push("--preview".to_owned());
        }
        args.extend(["--force".to_owned(), game.to_owned()]);
        self.json(&args, OPERATION_TIMEOUT)
    }
    pub(super) fn backup_cancellable(
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

    pub(super) fn restore_cancellable(
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

    pub(super) fn restore_backup(&self, game: &str, backup_id: &str) -> Result<Value, String> {
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

    pub(super) fn aliases(&self) -> Result<BTreeMap<String, String>, String> {
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

    pub(super) fn config_marker(&self) -> Result<i64, String> {
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

    pub(super) fn list_backups(&self, game: &str) -> Result<Value, String> {
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

    pub(super) fn logs(&self) -> Result<String, String> {
        let path = self.config_path()?.with_file_name("ludusavi_rCURRENT.log");
        match fs::read_to_string(path) {
            Ok(contents) => Ok(contents),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(String::new()),
            Err(error) => Err(error.to_string()),
        }
    }
}
pub(super) fn deployment_location(processes: &ProcessManager, flatpak: &Path) -> Option<PathBuf> {
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

pub(super) fn find_flatpak() -> Option<PathBuf> {
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

pub(super) fn game_objects(value: &Value) -> Result<BTreeMap<String, Value>, String> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::Write,
        os::unix::fs::{PermissionsExt, symlink},
    };
    use zip::{CompressionMethod, ZipWriter, write::FileOptions};
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
}
