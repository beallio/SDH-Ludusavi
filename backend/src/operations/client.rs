use super::*;
pub(crate) struct LudusaviPaths {
    pub(crate) bundled: PathBuf,
    pub(crate) native_config: PathBuf,
    pub(crate) flatpak_config: PathBuf,
}

impl LudusaviPaths {
    pub(crate) fn new(
        plugin_dir: &Path,
        home: &Path,
        xdg_config: Option<&std::ffi::OsStr>,
    ) -> Self {
        let config = xdg_config
            .map(Path::new)
            .filter(|path| path.is_absolute())
            .map(Path::to_path_buf)
            .unwrap_or_else(|| home.join(".config"));
        Self {
            bundled: plugin_dir.join("bin/ludusavi"),
            native_config: config.join("ludusavi"),
            flatpak_config: home.join(".var/app/com.github.mtkennerly.ludusavi/config/ludusavi"),
        }
    }
}

pub(super) enum Runner {
    Bundled {
        exe: PathBuf,
        canonical: PathBuf,
    },
    Flatpak {
        flatpak: PathBuf,
        deployment: Option<PathBuf>,
    },
}

impl Runner {
    fn program(&self) -> &Path {
        match self {
            Self::Bundled { exe, .. } => exe,
            Self::Flatpak { flatpak, .. } => flatpak,
        }
    }

    fn arguments(&self, config: &Path, args: &[String]) -> Vec<std::ffi::OsString> {
        let mut arguments = Vec::with_capacity(args.len() + 4);
        if matches!(self, Self::Flatpak { .. }) {
            arguments.extend(["run".into(), FLATPAK_ID.into()]);
        }
        arguments.push("--config".into());
        arguments.push(config.as_os_str().to_owned());
        arguments.extend(args.iter().map(std::ffi::OsString::from));
        arguments
    }
}

pub(super) struct LudusaviClient {
    pub(super) processes: Arc<ProcessManager>,
    pub(super) runner: Runner,
    pub(super) native_config: PathBuf,
    pub(super) execution_failed: AtomicBool,
    pub(super) config_path: Mutex<Option<PathBuf>>,
    pub(super) version: Mutex<Option<String>>,
}

impl LudusaviClient {
    pub(super) fn new(
        processes: Arc<ProcessManager>,
        paths: &LudusaviPaths,
        flatpak: Option<PathBuf>,
    ) -> Result<Self, String> {
        let probe = |runner: &Runner| {
            processes.run_at(
                runner.program(),
                &runner.arguments(&paths.native_config, &["--version".to_owned()]),
                DISCOVERY_TIMEOUT,
                false,
            )
        };
        let bundled = if executable(&paths.bundled) {
            match paths.bundled.canonicalize() {
                Ok(canonical) => {
                    let runner = Runner::Bundled {
                        exe: paths.bundled.clone(),
                        canonical,
                    };
                    match probe(&runner) {
                        Ok(version) => Some((runner, version)),
                        Err(error) => {
                            log::warn!("Bundled Ludusavi could not run: {error}");
                            None
                        }
                    }
                }
                Err(error) => {
                    log::warn!("Bundled Ludusavi path could not be resolved: {error}");
                    None
                }
            }
        } else {
            if fs::symlink_metadata(&paths.bundled).is_ok() {
                log::warn!(
                    "Bundled Ludusavi is not a regular executable file: {}",
                    paths.bundled.display()
                );
            }
            None
        };
        let (runner, version) = bundled.or_else(|| {
            let flatpak = flatpak?;
            let deployment = deployment_location(&processes, &flatpak);
            let runner = Runner::Flatpak { flatpak, deployment };
            probe(&runner).ok().map(|version| (runner, version))
        }).ok_or_else(|| "Ludusavi is not available: the bundled copy could not run and the Ludusavi Flatpak was not found".to_owned())?;
        let client = Self {
            processes,
            runner,
            native_config: paths.native_config.clone(),
            execution_failed: AtomicBool::new(false),
            config_path: Mutex::new(None),
            version: Mutex::new(Some(version.trim().to_owned())),
        };
        if let Err(error) = super::migration::migrate(paths, |config| {
            let args = ["config".to_owned(), "show".to_owned(), "--api".to_owned()];
            client
                .processes
                .run_at(
                    client.runner.program(),
                    &client.runner.arguments(config, &args),
                    BACKUPS_TIMEOUT,
                    false,
                )
                .and_then(|output| parse_ludusavi_json(&output))
        }) {
            log::warn!("Could not migrate Ludusavi configuration: {error}");
        }
        Ok(client)
    }

    pub(super) fn reusable(&self) -> bool {
        if self.execution_failed.load(Ordering::Acquire) {
            return false;
        }
        match &self.runner {
            Runner::Bundled { exe, canonical } => {
                executable(exe) && exe.canonicalize().is_ok_and(|path| path == *canonical)
            }
            Runner::Flatpak {
                flatpak,
                deployment,
            } => {
                deployment.is_some()
                    && find_flatpak().as_ref() == Some(flatpak)
                    && *deployment == deployment_location(&self.processes, flatpak)
            }
        }
    }

    pub(super) fn launcher_command(&self) -> Value {
        let command = match &self.runner {
            Runner::Bundled { exe, .. } => exe.to_string_lossy().into_owned(),
            Runner::Flatpak { .. } => "flatpak".to_owned(),
        };
        let mut args: Vec<_> = self
            .runner
            .arguments(&self.native_config, &[])
            .into_iter()
            .map(|arg| arg.to_string_lossy().into_owned())
            .collect();
        if matches!(self.runner, Runner::Bundled { .. }) {
            // The Ludusavi Flatpak sets this too. Without it, winit derives a scale of about 1.7 from
            // gamescope's screen size, the window outgrows the screen and edge controls are unreachable.
            args.splice(
                0..0,
                [
                    "WINIT_X11_SCALE_FACTOR=1".to_owned(),
                    "%command%".to_owned(),
                ],
            );
        }
        json!({"commandPath": command, "args": args, "compatTool": ""})
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
        let mut arguments = self.runner.arguments(&self.native_config, args);
        if !args.iter().any(|arg| arg == "--api") {
            arguments.push("--api".into());
        }
        self.processes
            .run_at_cancellable(
                self.runner.program(),
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
        let arguments = self.runner.arguments(&self.native_config, args);
        self.processes
            .run_at(self.runner.program(), &arguments, timeout, true)
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
            &["info".into(), "--show-location".into(), FLATPAK_ID.into()],
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
        .find(|candidate| executable(candidate))
}

fn executable(path: &Path) -> bool {
    path.is_file()
        && std::ffi::CString::new(path.as_os_str().as_bytes())
            .is_ok_and(|path| unsafe { libc::access(path.as_ptr(), libc::X_OK) == 0 })
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
    fn flatpak_commands_include_the_native_config_prefix() {
        let directory = tempfile::tempdir().unwrap();
        let fake = directory.path().join("flatpak");
        fs::write(&fake, "#!/bin/sh\nprintf '%s\\n' \"$@\"\n").unwrap();
        fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
        let client = LudusaviClient {
            processes: Arc::new(ProcessManager::default()),
            runner: Runner::Flatpak {
                flatpak: fake,
                deployment: None,
            },
            native_config: PathBuf::from("/contract-native/ludusavi"),
            execution_failed: AtomicBool::new(false),
            config_path: Mutex::new(None),
            version: Mutex::new(None),
        };

        let output = client
            .text(&["--version".to_owned()], BACKUPS_TIMEOUT)
            .unwrap();
        assert_eq!(
            output.lines().collect::<Vec<_>>(),
            [
                "run",
                FLATPAK_ID,
                "--config",
                "/contract-native/ludusavi",
                "--version"
            ]
        );
    }

    struct Fixture {
        directory: tempfile::TempDir,
        paths: LudusaviPaths,
        flatpak: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let directory = tempfile::tempdir().unwrap();
            let root = directory.path();
            let paths = LudusaviPaths {
                bundled: root.join("plugin/bin/ludusavi"),
                native_config: root.join("native/ludusavi"),
                flatpak_config: root.join("flatpak-config/ludusavi"),
            };
            let flatpak = root.join("flatpak");
            fs::create_dir_all(paths.bundled.parent().unwrap()).unwrap();
            let fixture = Self {
                directory,
                paths,
                flatpak,
            };
            fixture.write_fake(&fixture.flatpak);
            fixture
        }

        fn write_fake(&self, path: &Path) {
            let root = self.directory.path();
            fs::write(
                path,
                format!(
                    "#!/bin/sh\nprintf '%s\\n' BEGIN \"$@\" END >> '{}'\n\
                     if [ \"$1\" = run ]; then shift 2; fi\n\
                     [ \"$1\" = --config ] || exit 91\n\
                     config=\"$2\"; shift 2\n\
                     case \"$1 $2\" in\n\
                       '--version ') echo 'ludusavi 0.31.0';;\n\
                       'config show')\n\
                         # Like real Ludusavi, write default files into the folder being read.\n\
                         [ -e \"$config/config.yaml\" ] || : > \"$config/config.yaml\"\n\
                         [ -e \"$config/cache.yaml\" ] || : > \"$config/cache.yaml\"\n\
                         grep -q lookup-fails \"$config/config.yaml\" && exit 1\n\
                         url=$(sed -n 's/^url: //p' \"$config/config.yaml\")\n\
                         if [ -z \"$url\" ]; then echo '{{\"manifest\":{{}}}}'; \
                         else printf '{{\"manifest\":{{\"url\":\"%s\"}}}}\\n' \"$url\"; fi;;\n\
                       *) echo '{{}}';;\n\
                     esac\n",
                    root.join("calls").display(),
                ),
            )
            .unwrap();
            fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
        }

        fn client(&self, flatpak: Option<PathBuf>) -> Result<LudusaviClient, String> {
            LudusaviClient::new(Arc::new(ProcessManager::default()), &self.paths, flatpak)
        }

        fn calls(&self) -> String {
            fs::read_to_string(self.directory.path().join("calls")).unwrap_or_default()
        }

        fn source(&self, name: &str, bytes: &str) {
            fs::create_dir_all(&self.paths.flatpak_config).unwrap();
            fs::write(self.paths.flatpak_config.join(name), bytes).unwrap();
        }
    }

    #[test]
    fn discovery_prefers_a_working_bundle_and_falls_back_for_unusable_bundles() {
        for mode in ["working", "missing", "non-executable", "fails"] {
            let fixture = Fixture::new();
            if mode != "missing" {
                fixture.write_fake(&fixture.paths.bundled);
            }
            if mode == "non-executable" {
                fs::set_permissions(&fixture.paths.bundled, fs::Permissions::from_mode(0o644))
                    .unwrap();
            } else if mode == "fails" {
                fs::write(&fixture.paths.bundled, "#!/bin/sh\nexit 7\n").unwrap();
            }
            let client = fixture.client(Some(fixture.flatpak.clone())).unwrap();
            let expected = if mode == "working" {
                json!({
                    "commandPath": fixture.paths.bundled,
                    // Same override the Ludusavi Flatpak sets; see launcher_command.
                    "args": [
                        "WINIT_X11_SCALE_FACTOR=1",
                        "%command%",
                        "--config",
                        fixture.paths.native_config
                    ],
                    "compatTool": "",
                })
            } else {
                json!({
                    "commandPath": "flatpak",
                    "args": ["run", FLATPAK_ID, "--config", fixture.paths.native_config],
                    "compatTool": "",
                })
            };
            assert_eq!(client.launcher_command(), expected, "{mode}");
            let calls = fixture.calls();
            let native_prefix = format!(
                "--config\n{}\n--version\n",
                fixture.paths.native_config.display()
            );
            assert!(calls.contains(&native_prefix), "{mode}: {calls}");
            assert_eq!(calls.contains("BEGIN\nrun\n"), mode != "working", "{mode}");
        }
    }

    #[test]
    fn bundled_reuse_requires_a_healthy_regular_executable() {
        let fixture = Fixture::new();
        fixture.write_fake(&fixture.paths.bundled);
        let client = fixture.client(Some(fixture.flatpak.clone())).unwrap();
        assert!(client.reusable());
        fs::set_permissions(&fixture.paths.bundled, fs::Permissions::from_mode(0o644)).unwrap();
        assert!(!client.reusable());
        fs::set_permissions(&fixture.paths.bundled, fs::Permissions::from_mode(0o755)).unwrap();
        assert!(client.reusable());
        client.execution_failed.store(true, Ordering::Release);
        assert!(!client.reusable());
        client.execution_failed.store(false, Ordering::Release);
        fs::remove_file(&fixture.paths.bundled).unwrap();
        assert!(!client.reusable());
    }

    #[test]
    fn unavailable_runners_report_the_shared_error() {
        let fixture = Fixture::new();
        let expected = "Ludusavi is not available: the bundled copy could not run and the Ludusavi Flatpak was not found";
        assert_eq!(fixture.client(None).err().unwrap(), expected);
        fs::write(&fixture.flatpak, "#!/bin/sh\nexit 1\n").unwrap();
        assert_eq!(
            fixture.client(Some(fixture.flatpak.clone())).err().unwrap(),
            expected
        );
    }

    #[test]
    fn both_runners_prefix_json_and_text_commands_with_native_config() {
        for bundled in [true, false] {
            let fixture = Fixture::new();
            if bundled {
                fixture.write_fake(&fixture.paths.bundled);
            }
            let client = fixture.client(Some(fixture.flatpak.clone())).unwrap();
            client.json(&["backups".into()], BACKUPS_TIMEOUT).unwrap();
            client
                .text(&["config".into(), "path".into()], BACKUPS_TIMEOUT)
                .unwrap();
            let prefix = if bundled {
                "BEGIN\n".to_owned()
            } else {
                format!("BEGIN\nrun\n{FLATPAK_ID}\n")
            };
            let config = fixture.paths.native_config.display();
            let calls = fixture.calls();
            assert!(calls.contains(&format!(
                "{prefix}--config\n{config}\nbackups\n--api\nEND\n"
            )));
            assert!(calls.contains(&format!("{prefix}--config\n{config}\nconfig\npath\nEND\n")));
        }
    }

    #[test]
    fn migration_preserves_existing_and_dangling_config() {
        for mode in [
            "missing",
            "existing",
            "dangling",
            "missing-source",
            "symlink-source",
        ] {
            let fixture = Fixture::new();
            if mode == "symlink-source" {
                fixture.source("real.yaml", "source config");
                symlink(
                    "real.yaml",
                    fixture.paths.flatpak_config.join("config.yaml"),
                )
                .unwrap();
            } else if mode != "missing-source" {
                fixture.source("config.yaml", "source config");
            }
            let config = fixture.paths.native_config.join("config.yaml");
            if mode == "existing" || mode == "dangling" {
                fs::create_dir_all(&fixture.paths.native_config).unwrap();
                if mode == "existing" {
                    fs::write(&config, "existing config").unwrap();
                } else {
                    symlink("missing-target", &config).unwrap();
                }
            }
            fixture.client(Some(fixture.flatpak.clone())).unwrap();
            match mode {
                "missing" | "symlink-source" => {
                    assert_eq!(fs::read_to_string(config).unwrap(), "source config")
                }
                "existing" => assert_eq!(fs::read_to_string(config).unwrap(), "existing config"),
                "dangling" => assert!(
                    fs::symlink_metadata(config)
                        .unwrap()
                        .file_type()
                        .is_symlink()
                ),
                _ => assert!(!config.exists()),
            }
        }
    }

    #[test]
    fn migration_manifest_and_cache_are_copied_only_when_safe() {
        for mode in [
            "equal",
            "mismatch",
            "source-lookup-fails",
            "native-lookup-fails",
            "missing-url",
            "source-missing-manifest",
            "source-missing-cache",
            "native-manifest",
            "native-cache",
            "native-dangling",
        ] {
            let fixture = Fixture::new();
            let source_config = if mode == "source-lookup-fails" {
                "url: same\nlookup-fails\n"
            } else {
                "url: same\n"
            };
            fixture.source("config.yaml", source_config);
            if mode != "source-missing-manifest" {
                fixture.source("manifest.yaml", "source manifest");
            }
            if mode != "source-missing-cache" {
                fixture.source("cache.yaml", "source cache");
            }
            let native_config = match mode {
                "mismatch" => Some("url: different\n"),
                "native-lookup-fails" => Some("url: same\nlookup-fails\n"),
                "missing-url" => Some("no address\n"),
                _ => None,
            };
            if let Some(contents) = native_config {
                fs::create_dir_all(&fixture.paths.native_config).unwrap();
                fs::write(fixture.paths.native_config.join("config.yaml"), contents).unwrap();
            }
            if let "native-manifest" | "native-cache" | "native-dangling" = mode {
                fs::create_dir_all(&fixture.paths.native_config).unwrap();
                let name = if mode == "native-cache" {
                    "cache.yaml"
                } else {
                    "manifest.yaml"
                };
                let path = fixture.paths.native_config.join(name);
                if mode == "native-dangling" {
                    symlink("missing-target", path).unwrap();
                } else {
                    fs::write(path, "existing").unwrap();
                }
            }
            let client = fixture.client(Some(fixture.flatpak.clone())).unwrap();
            assert!(!client.execution_failed.load(Ordering::Acquire), "{mode}");
            for name in ["manifest.yaml", "cache.yaml"] {
                let path = fixture.paths.native_config.join(name);
                let existing = (mode == "native-manifest" && name == "manifest.yaml")
                    || (mode == "native-cache" && name == "cache.yaml");
                if mode == "equal" {
                    assert_eq!(
                        fs::read_to_string(path).unwrap(),
                        format!("source {}", name.trim_end_matches(".yaml"))
                    );
                } else if existing {
                    assert_eq!(fs::read_to_string(path).unwrap(), "existing");
                } else if mode == "native-dangling" && name == "manifest.yaml" {
                    assert!(fs::symlink_metadata(path).unwrap().file_type().is_symlink());
                } else {
                    assert!(!path.exists(), "{mode}: {name}");
                }
            }
            // The address lookups must not leave files in either real folder.
            let names = |directory: &Path| {
                let mut names = fs::read_dir(directory)
                    .map(|entries| {
                        entries
                            .map(|entry| entry.unwrap().file_name().into_string().unwrap())
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                names.sort();
                names
            };
            let mut source_names = vec!["config.yaml"];
            if mode != "source-missing-manifest" {
                source_names.push("manifest.yaml");
            }
            if mode != "source-missing-cache" {
                source_names.push("cache.yaml");
            }
            source_names.sort();
            assert_eq!(names(&fixture.paths.flatpak_config), source_names, "{mode}");
            assert!(
                names(&fixture.paths.native_config)
                    .iter()
                    .all(|name| !name.starts_with(".sdh-ludusavi-")),
                "{mode}"
            );
        }
    }

    #[test]
    fn migration_does_not_copy_either_file_if_lookup_creates_one() {
        for created in ["cache.yaml", "manifest.yaml"] {
            let fixture = Fixture::new();
            fixture.source("manifest.yaml", "source manifest");
            fixture.source("cache.yaml", "source cache");
            fs::create_dir_all(&fixture.paths.native_config).unwrap();
            let result = super::super::migration::migrate(&fixture.paths, |_| {
                // Another writer creates one of the files while the addresses are being read.
                fs::write(
                    fixture.paths.native_config.join(created),
                    "created by lookup",
                )
                .unwrap();
                Ok(json!({"manifest":{"url":"same"}}))
            });
            assert!(result.is_ok(), "{created}: {result:?}");
            assert_eq!(
                fs::read_to_string(fixture.paths.native_config.join(created)).unwrap(),
                "created by lookup"
            );
            let other = if created == "cache.yaml" {
                "manifest.yaml"
            } else {
                "cache.yaml"
            };
            assert!(!fixture.paths.native_config.join(other).exists());
        }
    }

    #[test]
    fn migration_skips_same_directory_and_errors_are_nonfatal() {
        let mut fixture = Fixture::new();
        fixture.source("config.yaml", "same config");
        fixture.source("manifest.yaml", "same manifest");
        fixture.source("cache.yaml", "same cache");
        let alias = fixture.directory.path().join("alias");
        symlink(&fixture.paths.flatpak_config, &alias).unwrap();
        fixture.paths.native_config = alias;
        fixture.client(Some(fixture.flatpak.clone())).unwrap();
        assert_eq!(
            fs::read_to_string(fixture.paths.native_config.join("config.yaml")).unwrap(),
            "same config"
        );
        assert!(!fixture.calls().contains("config\nshow"));

        let fixture = Fixture::new();
        fixture.source("config.yaml", "source");
        fs::write(
            fixture.paths.native_config.parent().unwrap(),
            "not a directory",
        )
        .unwrap();
        let client = fixture.client(Some(fixture.flatpak.clone())).unwrap();
        assert_eq!(client.version().unwrap(), "ludusavi 0.31.0");
    }

    #[test]
    fn native_config_uses_only_absolute_xdg_paths() {
        let plugin = Path::new("/plugin");
        let home = Path::new("/home/user");
        for (xdg, expected) in [
            (None, "/home/user/.config/ludusavi"),
            (Some(""), "/home/user/.config/ludusavi"),
            (Some("relative"), "/home/user/.config/ludusavi"),
            (Some("/custom/config"), "/custom/config/ludusavi"),
        ] {
            let paths = LudusaviPaths::new(plugin, home, xdg.map(std::ffi::OsStr::new));
            assert_eq!(paths.native_config, Path::new(expected));
            assert_eq!(paths.bundled, Path::new("/plugin/bin/ludusavi"));
            assert_eq!(
                paths.flatpak_config,
                Path::new("/home/user/.var/app/com.github.mtkennerly.ludusavi/config/ludusavi")
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
            runner: Runner::Flatpak {
                flatpak: fake,
                deployment: None,
            },
            native_config: original.clone(),
            config_path: std::sync::Mutex::new(None),
            version: std::sync::Mutex::new(None),
            execution_failed: AtomicBool::new(false),
        };

        assert_eq!(client.logs().unwrap(), "original path");
        let marker = client.config_marker().unwrap();
        std::thread::sleep(Duration::from_millis(20));
        fs::write(resolved.join("cache.yaml"), "updated resolved cache").unwrap();
        assert_ne!(client.config_marker().unwrap(), marker);
    }
}
