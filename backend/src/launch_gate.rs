use std::{
    fs,
    io::{self, Read},
    os::unix::{fs::MetadataExt, process::CommandExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

const SYSTEMCTL_TIMEOUT: Duration = Duration::from_secs(3);
const FREEZER_TIMEOUT: Duration = Duration::from_secs(1);
const FREEZER_POLL: Duration = Duration::from_millis(20);
const SIGSTOP_TIMEOUT: Duration = Duration::from_millis(100);
const SIGSTOP_POLL: Duration = Duration::from_micros(500);
const MAX_PID: i32 = 2_147_483_647;
const MAX_REASON_LENGTH: usize = 180;
const STEAM_LAUNCHER_UNIT: &str = "steam-launcher.service";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SteamAppScope {
    pub unit: String,
    pub cgroup_path: String,
    pub device: u64,
    pub inode: u64,
    pub root_pid: i32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScopeTransitionResult {
    pub success: bool,
    pub reason: String,
    pub disappeared: bool,
}

impl ScopeTransitionResult {
    fn ok() -> Self {
        Self {
            success: true,
            reason: String::new(),
            disappeared: false,
        }
    }

    fn failed(reason: impl Into<String>) -> Self {
        Self {
            success: false,
            reason: reason.into(),
            disappeared: false,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaunchProcessIdentity {
    pub pid: i32,
    pub owner_uid: u32,
    pub start_ticks: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScopeAcquisitionResult {
    pub success: bool,
    pub scope: Option<SteamAppScope>,
    pub stop_only: bool,
    pub reason: String,
    pub identity: Option<LaunchProcessIdentity>,
}

#[cfg(test)]
type ThawHook = std::sync::Arc<dyn Fn(&SteamAppScope) -> ScopeTransitionResult + Send + Sync>;

#[derive(Clone)]
pub struct SystemdScopeController {
    proc_root: PathBuf,
    cgroup_root: PathBuf,
    uid: u32,
    #[cfg(test)]
    thaw_hook: std::sync::Arc<std::sync::Mutex<Option<ThawHook>>>,
}

impl Default for SystemdScopeController {
    fn default() -> Self {
        Self::new("/proc", "/sys/fs/cgroup", unsafe { libc::geteuid() })
    }
}

impl SystemdScopeController {
    pub fn new(proc_root: impl Into<PathBuf>, cgroup_root: impl Into<PathBuf>, uid: u32) -> Self {
        Self {
            proc_root: proc_root.into(),
            cgroup_root: cgroup_root.into(),
            uid,
            #[cfg(test)]
            thaw_hook: std::sync::Arc::new(std::sync::Mutex::new(None)),
        }
    }
    #[cfg(test)]
    pub(crate) fn set_thaw_hook(&self, hook: ThawHook) {
        *self
            .thaw_hook
            .lock()
            .unwrap_or_else(|error| error.into_inner()) = Some(hook);
    }

    pub fn discover(&self, pid: i32) -> Result<SteamAppScope, String> {
        let pid = coerce_pid(pid)?;
        let proc_dir = self.proc_root.join(pid.to_string());
        let metadata = fs::metadata(&proc_dir)
            .map_err(|_| "Unable to read launch PID cgroup membership".to_owned())?;
        if metadata.uid() != self.uid {
            return Err("Launch PID owner does not match the plugin user".to_owned());
        }
        let content = fs::read_to_string(proc_dir.join("cgroup"))
            .map_err(|_| "Unable to read launch PID cgroup membership".to_owned())?;
        let path = unified_cgroup_path(&content)?;
        let parts = validate_scope_parts(&path, self.uid)?;
        let scope_dir = self
            .resolved_scope_dir(&parts)
            .map_err(|_| "Steam app scope is unavailable".to_owned())?;
        for name in ["cgroup.freeze", "cgroup.events"] {
            let value = fs::read_to_string(scope_dir.join(name))
                .map_err(|_| "Steam app scope has no readable freezer state".to_owned())?;
            if name == "cgroup.freeze" && !matches!(value.trim(), "0" | "1") {
                return Err("Steam app scope has no readable freezer state".to_owned());
            }
            if name == "cgroup.events" && parse_frozen(&value).is_none() {
                return Err("Steam app scope has no readable freezer state".to_owned());
            }
        }
        let identity = fs::metadata(&scope_dir)
            .map_err(|_| "Unable to identify Steam app scope".to_owned())?;
        Ok(SteamAppScope {
            unit: parts[4].clone(),
            cgroup_path: path,
            device: identity.dev(),
            inode: identity.ino(),
            root_pid: pid,
        })
    }

    pub fn freeze(&self, scope: &SteamAppScope) -> ScopeTransitionResult {
        let (state, reason) = self.scope_state(scope);
        if state != ScopeState::Live {
            return ScopeTransitionResult::failed(reason);
        }
        let command = self.run_unit_command("freeze", &scope.unit);
        if !command.success {
            self.best_effort_thaw(scope);
            return command;
        }
        let verified = self.wait_for_frozen(scope, true);
        if !verified.success {
            self.best_effort_thaw(scope);
        }
        verified
    }

    pub fn thaw(&self, scope: &SteamAppScope) -> ScopeTransitionResult {
        self.thaw_with_deadline(scope, None)
    }

    pub(crate) fn thaw_until(
        &self,
        scope: &SteamAppScope,
        deadline: Instant,
    ) -> ScopeTransitionResult {
        self.thaw_with_deadline(scope, Some(deadline))
    }

    fn thaw_with_deadline(
        &self,
        scope: &SteamAppScope,
        deadline: Option<Instant>,
    ) -> ScopeTransitionResult {
        #[cfg(test)]
        if let Some(hook) = self
            .thaw_hook
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .clone()
        {
            return hook(scope);
        }
        let (state, reason) = self.scope_state(scope);
        if state == ScopeState::Missing {
            return ScopeTransitionResult {
                success: true,
                reason: String::new(),
                disappeared: true,
            };
        }
        if state != ScopeState::Live {
            return ScopeTransitionResult::failed(reason);
        }
        let command = self.run_unit_command_until("thaw", &scope.unit, deadline);
        if !command.success {
            return if self.scope_state(scope).0 == ScopeState::Missing {
                ScopeTransitionResult {
                    success: true,
                    reason: String::new(),
                    disappeared: true,
                }
            } else {
                command
            };
        }
        self.wait_for_frozen_with_deadline(scope, false, deadline)
    }

    pub fn freeze_requested(&self, scope: &SteamAppScope) -> bool {
        if self.scope_state(scope).0 != ScopeState::Live {
            return false;
        }
        self.read_requested(scope) == Some(1)
    }

    pub fn wait_for_frozen(&self, scope: &SteamAppScope, expected: bool) -> ScopeTransitionResult {
        self.wait_for_frozen_with_deadline(scope, expected, None)
    }

    fn wait_for_frozen_with_deadline(
        &self,
        scope: &SteamAppScope,
        expected: bool,
        shutdown_deadline: Option<Instant>,
    ) -> ScopeTransitionResult {
        let expected = i32::from(expected);
        let now = Instant::now();
        let deadline = shutdown_deadline.map_or(now + FREEZER_TIMEOUT, |external| {
            external.min(now + FREEZER_TIMEOUT)
        });
        loop {
            let (state, reason) = self.scope_state(scope);
            if state == ScopeState::Missing && expected == 0 {
                return ScopeTransitionResult {
                    success: true,
                    reason: String::new(),
                    disappeared: true,
                };
            }
            if state != ScopeState::Live {
                return ScopeTransitionResult::failed(reason);
            }
            let (Some(requested), Some(completed)) =
                (self.read_requested(scope), self.read_completed(scope))
            else {
                return ScopeTransitionResult::failed(
                    "Malformed or unreadable cgroup freezer state",
                );
            };
            if requested == expected && completed == expected {
                return ScopeTransitionResult::ok();
            }
            let now = Instant::now();
            if now >= deadline {
                return ScopeTransitionResult::failed(if expected == 1 {
                    "Cgroup freeze verification timed out"
                } else {
                    "Cgroup thaw verification timed out"
                });
            }
            thread::sleep(FREEZER_POLL.min(deadline.saturating_duration_since(now)));
        }
    }

    fn resolved_scope_dir(&self, parts: &[String]) -> io::Result<PathBuf> {
        let root = fs::canonicalize(&self.cgroup_root).map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "Steam cgroup root is unavailable",
                )
            } else {
                error
            }
        })?;
        let expected = parts
            .iter()
            .fold(root.clone(), |path, part| path.join(part));
        let resolved = fs::canonicalize(&expected)?;
        if resolved != expected || !resolved.starts_with(&root) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Steam app scope escapes the cgroup root",
            ));
        }
        Ok(resolved)
    }

    fn scope_dir(&self, scope: &SteamAppScope) -> io::Result<PathBuf> {
        let parts = validate_scope_parts(&scope.cgroup_path, self.uid)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
        if parts[4] != scope.unit {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Scope unit does not match its cgroup path",
            ));
        }
        self.resolved_scope_dir(&parts)
    }

    fn scope_state(&self, scope: &SteamAppScope) -> (ScopeState, String) {
        let path = match self.scope_dir(scope) {
            Ok(path) => path,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return (
                    ScopeState::Missing,
                    "Steam app scope disappeared".to_owned(),
                );
            }
            Err(_) => {
                return (
                    ScopeState::Invalid,
                    "Steam app scope path is invalid".to_owned(),
                );
            }
        };
        let identity = match fs::metadata(&path) {
            Ok(identity) => identity,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return (
                    ScopeState::Missing,
                    "Steam app scope disappeared".to_owned(),
                );
            }
            Err(_) => {
                return (
                    ScopeState::Invalid,
                    "Steam app scope path is invalid".to_owned(),
                );
            }
        };
        if (identity.dev(), identity.ino()) != (scope.device, scope.inode) {
            return (
                ScopeState::Stale,
                "Steam app scope identity changed".to_owned(),
            );
        }
        (ScopeState::Live, String::new())
    }

    fn read_requested(&self, scope: &SteamAppScope) -> Option<i32> {
        let value = fs::read_to_string(self.scope_dir(scope).ok()?.join("cgroup.freeze")).ok()?;
        match value.trim() {
            "0" => Some(0),
            "1" => Some(1),
            _ => None,
        }
    }

    fn read_completed(&self, scope: &SteamAppScope) -> Option<i32> {
        parse_frozen(&fs::read_to_string(self.scope_dir(scope).ok()?.join("cgroup.events")).ok()?)
    }

    fn run_unit_command(&self, action: &str, unit: &str) -> ScopeTransitionResult {
        self.run_unit_command_until(action, unit, None)
    }

    fn run_unit_command_until(
        &self,
        action: &str,
        unit: &str,
        shutdown_deadline: Option<Instant>,
    ) -> ScopeTransitionResult {
        if !matches!(action, "freeze" | "thaw") || !valid_unit(unit) {
            return ScopeTransitionResult::failed("Refusing invalid scope transition");
        }
        let started = Instant::now();
        if shutdown_deadline.is_some_and(|deadline| started >= deadline) {
            return ScopeTransitionResult::failed("Shutdown deadline expired");
        }
        let deadline = shutdown_deadline.map_or(started + SYSTEMCTL_TIMEOUT, |external| {
            external.min(started + SYSTEMCTL_TIMEOUT)
        });
        let mut command = Command::new("systemctl");
        command
            .args(["--user", action, unit])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .process_group(0);
        let runtime = format!("/run/user/{}", self.uid);
        let bus = format!("unix:path=/run/user/{}/bus", self.uid);
        if std::env::var_os("XDG_RUNTIME_DIR").is_none() {
            command.env("XDG_RUNTIME_DIR", runtime);
        }
        if std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_none() {
            command.env("DBUS_SESSION_BUS_ADDRESS", bus);
        }
        command.env("LD_LIBRARY_PATH", "");
        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                return ScopeTransitionResult::failed(format!(
                    "systemctl {action} failed: {}",
                    bounded_reason(&error.to_string())
                ));
            }
        };
        let stderr = child.stderr.take().expect("piped systemctl stderr");
        let stderr_reader = match thread::Builder::new()
            .name("sdh-ludusavi-systemctl-stderr".to_owned())
            .spawn(move || read_pipe(stderr))
        {
            Ok(reader) => reader,
            Err(error) => {
                terminate_command_group(&mut child);
                return ScopeTransitionResult::failed(format!(
                    "systemctl {action} failed to start output reader: {}",
                    bounded_reason(&error.to_string())
                ));
            }
        };
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break Some(status),
                Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(10)),
                Ok(None) => {
                    terminate_command_group(&mut child);
                    break None;
                }
                Err(_) => {
                    terminate_command_group(&mut child);
                    break None;
                }
            }
        };
        let stderr = stderr_reader
            .join()
            .ok()
            .and_then(Result::ok)
            .unwrap_or_default();
        let Some(status) = status else {
            let detail = bounded_reason(&String::from_utf8_lossy(&stderr));
            return ScopeTransitionResult::failed(if detail.is_empty() {
                format!("systemctl {action} timed out")
            } else {
                format!("systemctl {action} timed out: {detail}")
            });
        };
        if !status.success() {
            let detail = bounded_reason(&String::from_utf8_lossy(&stderr));
            return ScopeTransitionResult::failed(if detail.is_empty() {
                format!(
                    "systemctl {action} failed: exit {}",
                    status.code().unwrap_or(-1)
                )
            } else {
                format!("systemctl {action} failed: {detail}")
            });
        }
        ScopeTransitionResult::ok()
    }

    fn best_effort_thaw(&self, scope: &SteamAppScope) {
        if self.scope_state(scope).0 == ScopeState::Live
            && self.run_unit_command("thaw", &scope.unit).success
        {
            let _ = self.wait_for_frozen(scope, false);
        }
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum ScopeState {
    Live,
    Missing,
    Invalid,
    Stale,
}

pub struct LaunchScopeAcquirer {
    controller: SystemdScopeController,
    proc_root: PathBuf,
    uid: u32,
    #[cfg(test)]
    panic_after_stop: Option<std::sync::Arc<(std::sync::Barrier, std::sync::Barrier)>>,
}
struct BootstrapStopGuard<'a> {
    controller: &'a SystemdScopeController,
    proc_root: &'a Path,
    identity: LaunchProcessIdentity,
    stopped: bool,
    acquired_scope: Option<SteamAppScope>,
    handed_off: bool,
}

impl BootstrapStopGuard<'_> {
    fn handoff(&mut self) {
        self.stopped = false;
        self.acquired_scope = None;
        self.handed_off = true;
    }
}

impl Drop for BootstrapStopGuard<'_> {
    fn drop(&mut self) {
        if self.handed_off {
            return;
        }
        if self.stopped && same_process_identity(self.proc_root, &self.identity) {
            let _ = send_signal(self.identity.pid, libc::SIGCONT);
        }
        if let Some(scope) = &self.acquired_scope {
            self.controller.best_effort_thaw(scope);
        }
    }
}

impl Default for LaunchScopeAcquirer {
    fn default() -> Self {
        let controller = SystemdScopeController::default();
        Self::new(controller, "/proc", unsafe { libc::geteuid() })
    }
}

impl LaunchScopeAcquirer {
    pub fn new(
        controller: SystemdScopeController,
        proc_root: impl Into<PathBuf>,
        uid: u32,
    ) -> Self {
        Self {
            controller,
            proc_root: proc_root.into(),
            uid,
            #[cfg(test)]
            panic_after_stop: None,
        }
    }

    pub fn acquire(
        &self,
        pid: i32,
        existing_scope: Option<&SteamAppScope>,
    ) -> ScopeAcquisitionResult {
        let identity = match read_process_identity(&self.proc_root, pid) {
            Some(identity) if identity.owner_uid == self.uid => identity,
            Some(_) => {
                return acquisition_failure("Launch PID owner does not match the plugin user");
            }
            None => return acquisition_failure("Launch PID exited before scope acquisition"),
        };
        if let Err(error) = send_signal(pid, libc::SIGSTOP) {
            return acquisition_failure(&format!("Unable to stop launch PID: {error}"));
        }
        let mut cleanup = BootstrapStopGuard {
            controller: &self.controller,
            proc_root: &self.proc_root,
            identity: identity.clone(),
            stopped: true,
            acquired_scope: None,
            handed_off: false,
        };
        #[cfg(test)]
        if let Some(barriers) = &self.panic_after_stop {
            barriers.0.wait();
            barriers.1.wait();
            panic!("fixture acquisition unwind after SIGSTOP");
        }
        let result: Result<(), String> = match self.controller.discover(pid) {
            Err(message) if message == "Exact Steam app scope is not ready" => {
                let state = wait_until_stopped(&self.proc_root, pid, SIGSTOP_TIMEOUT, SIGSTOP_POLL);
                if state != Some('T') {
                    Err(format!(
                        "Launch PID did not stop within 100ms (state={})",
                        state.map_or_else(|| "unreadable".to_owned(), |state| state.to_string())
                    ))
                } else if !same_process_identity(&self.proc_root, &identity) {
                    Err("Launch PID identity changed during scope acquisition".to_owned())
                } else if has_children(&self.proc_root, pid) {
                    Err(
                        "Launch PID already has children; refusing an unverified pre-scope gate"
                            .to_owned(),
                    )
                } else {
                    cleanup.handoff();
                    return ScopeAcquisitionResult {
                        success: true,
                        scope: None,
                        stop_only: true,
                        reason: String::new(),
                        identity: Some(identity),
                    };
                }
            }
            Err(message) => Err(message),
            Ok(scope) => {
                if !same_process_identity(&self.proc_root, &identity) {
                    Err("Launch PID identity changed during scope acquisition".to_owned())
                } else {
                    let verified = if existing_scope == Some(&scope) {
                        self.verify_frozen(&scope, false)
                    } else {
                        self.controller.freeze(&scope)
                    };
                    if !verified.success {
                        Err(verified.reason)
                    } else {
                        cleanup.acquired_scope =
                            (existing_scope != Some(&scope)).then_some(scope.clone());
                        if !same_process_identity(&self.proc_root, &identity)
                            || self.controller.discover(pid).ok().as_ref() != Some(&scope)
                        {
                            Err("Launch PID scope changed during scope acquisition".to_owned())
                        } else if let Err(error) = send_signal(pid, libc::SIGCONT) {
                            Err(format!("Unable to release bootstrap PID: {error}"))
                        } else {
                            cleanup.stopped = false;
                            let handed_off = self.verify_frozen(&scope, true);
                            if handed_off.success {
                                cleanup.handoff();
                                return ScopeAcquisitionResult {
                                    success: true,
                                    scope: Some(scope),
                                    stop_only: false,
                                    reason: String::new(),
                                    identity: None,
                                };
                            }
                            Err(handed_off.reason)
                        }
                    }
                }
            }
        };
        acquisition_failure(&result.unwrap_err())
    }

    fn verify_frozen(&self, scope: &SteamAppScope, handoff: bool) -> ScopeTransitionResult {
        if !self.controller.freeze_requested(scope) {
            return ScopeTransitionResult::failed(if handoff {
                "Scope freeze was not preserved after bootstrap handoff"
            } else {
                "Scope freeze was not preserved"
            });
        }
        let verified = self.controller.wait_for_frozen(scope, true);
        if !verified.success && handoff {
            return ScopeTransitionResult::failed(format!(
                "Scope freeze verification failed after bootstrap handoff: {}",
                verified.reason
            ));
        }
        verified
    }
}

fn acquisition_failure(reason: &str) -> ScopeAcquisitionResult {
    ScopeAcquisitionResult {
        success: false,
        scope: None,
        stop_only: false,
        reason: bounded_reason(reason),
        identity: None,
    }
}

fn coerce_pid(pid: i32) -> Result<i32, String> {
    if !(2..=MAX_PID).contains(&pid) {
        Err("PID is outside the safe process range".to_owned())
    } else {
        Ok(pid)
    }
}

pub(crate) fn parse_start_ticks(stat: &str, expected_pid: i32) -> Option<u64> {
    let open = stat.find('(')?;
    let close = stat.rfind(')')?;
    if open == 0 || close <= open || stat[..open].trim().parse::<i32>().ok()? != expected_pid {
        return None;
    }
    stat[close + 1..].split_whitespace().nth(19)?.parse().ok()
}

fn read_process_identity(proc_root: &Path, pid: i32) -> Option<LaunchProcessIdentity> {
    let proc_dir = proc_root.join(pid.to_string());
    let owner_uid = fs::metadata(&proc_dir).ok()?.uid();
    let stat = fs::read_to_string(proc_dir.join("stat")).ok()?;
    let start_ticks = parse_start_ticks(&stat, pid)?;
    Some(LaunchProcessIdentity {
        pid,
        owner_uid,
        start_ticks,
    })
}

fn same_process_identity(proc_root: &Path, expected: &LaunchProcessIdentity) -> bool {
    read_process_identity(proc_root, expected.pid).as_ref() == Some(expected)
}

fn send_signal(pid: i32, signal: i32) -> io::Result<()> {
    if !(2..=MAX_PID).contains(&pid) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "unsafe PID"));
    }
    if unsafe { libc::kill(pid, signal) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

fn wait_until_stopped(
    proc_root: &Path,
    pid: i32,
    timeout: Duration,
    poll: Duration,
) -> Option<char> {
    let deadline = Instant::now() + timeout;
    loop {
        let state = thread_group_state(proc_root, pid);
        if state == Some('T') || Instant::now() >= deadline {
            return state;
        }
        thread::sleep(poll.min(deadline.saturating_duration_since(Instant::now())));
    }
}

fn thread_group_state(proc_root: &Path, pid: i32) -> Option<char> {
    let task = proc_root.join(pid.to_string()).join("task");
    let entries = fs::read_dir(task)
        .ok()?
        .collect::<Result<Vec<_>, _>>()
        .ok()?;
    if entries.is_empty() {
        return None;
    }
    let mut all_stopped = true;
    for entry in entries {
        let stat = fs::read_to_string(entry.path().join("stat")).ok()?;
        let state = process_state(&stat)?;
        if state != 'T' {
            all_stopped = false;
        }
        if state != 'T' {
            return Some(state);
        }
    }
    all_stopped.then_some('T')
}
pub(crate) fn thread_group_stopped(proc_root: &Path, pid: i32) -> bool {
    thread_group_state(proc_root, pid) == Some('T')
}

fn process_state(stat: &str) -> Option<char> {
    stat[stat.rfind(')')? + 1..]
        .split_whitespace()
        .next()?
        .chars()
        .next()
}

fn has_children(proc_root: &Path, pid: i32) -> bool {
    let task = proc_root.join(pid.to_string()).join("task");
    let Ok(entries) = fs::read_dir(task) else {
        return true;
    };
    let mut found = false;
    for entry in entries {
        let Ok(entry) = entry else {
            return true;
        };
        found = true;
        match fs::read_to_string(entry.path().join("children")) {
            Ok(children) if children.trim().is_empty() => {}
            _ => return true,
        }
    }
    !found
}

fn unified_cgroup_path(content: &str) -> Result<String, String> {
    let paths = content
        .lines()
        .filter_map(|line| line.strip_prefix("0::"))
        .collect::<Vec<_>>();
    if paths.len() != 1 || !paths[0].starts_with('/') {
        return Err("Launch PID has no unique unified cgroup entry".to_owned());
    }
    Ok(paths[0].to_owned())
}

fn validate_scope_parts(path: &str, uid: u32) -> Result<Vec<String>, String> {
    let parts = path
        .strip_prefix('/')
        .ok_or_else(|| "Launch PID is not in an exact Steam app scope".to_owned())?
        .split('/')
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let prefix = [
        "user.slice".to_owned(),
        format!("user-{uid}.slice"),
        format!("user@{uid}.service"),
        "app.slice".to_owned(),
    ];
    if path == format!("/{}", prefix.join("/"))
        || path == format!("/{}/{}", prefix.join("/"), STEAM_LAUNCHER_UNIT)
    {
        return Err("Exact Steam app scope is not ready".to_owned());
    }
    if parts.len() != 5
        || parts[..4] != prefix
        || parts
            .iter()
            .any(|part| part.is_empty() || part == "." || part == "..")
        || !valid_unit(&parts[4])
    {
        return Err("Launch PID is not in an exact Steam app scope".to_owned());
    }
    Ok(parts)
}

fn valid_unit(unit: &str) -> bool {
    let Some(rest) = unit.strip_prefix("app-steam-app") else {
        return false;
    };
    let Some((app, pid)) = rest
        .strip_suffix(".scope")
        .and_then(|value| value.split_once('-'))
    else {
        return false;
    };
    !app.is_empty()
        && !pid.is_empty()
        && app.bytes().all(|byte| byte.is_ascii_digit())
        && pid.bytes().all(|byte| byte.is_ascii_digit())
}

fn parse_frozen(events: &str) -> Option<i32> {
    let mut frozen = events.lines().filter_map(|line| {
        let mut fields = line.split_whitespace();
        (fields.next()? == "frozen")
            .then(|| fields.next())??
            .parse::<i32>()
            .ok()
    });
    let value = frozen.next()?;
    (matches!(value, 0 | 1) && frozen.next().is_none()).then_some(value)
}

fn terminate_command_group(child: &mut std::process::Child) {
    if let Ok(pid) = i32::try_from(child.id())
        && pid > 1
    {
        unsafe {
            libc::kill(-pid, libc::SIGKILL);
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}
fn read_pipe(mut pipe: impl Read) -> io::Result<Vec<u8>> {
    let mut output = Vec::new();
    pipe.read_to_end(&mut output)?;
    Ok(output)
}

fn bounded_reason(message: &str) -> String {
    message
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(MAX_REASON_LENGTH)
        .collect()
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        os::unix::process::CommandExt,
        path::Path,
        process::{Command, Stdio},
        sync::{Arc, Barrier},
        thread,
        time::{Duration, Instant},
    };

    use tempfile::tempdir_in;

    use super::{
        LaunchScopeAcquirer, SteamAppScope, SystemdScopeController, read_process_identity,
        same_process_identity, thread_group_stopped,
    };

    #[test]
    fn vanished_scope_is_an_idempotent_thaw() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let cgroup_root = temporary.path().join("cgroup");
        fs::create_dir(&cgroup_root).unwrap();
        let uid = unsafe { libc::geteuid() };
        let unit = "app-steam-app123-456.scope";
        let cgroup_path =
            format!("/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}");
        let scope_dir = cgroup_root.join(cgroup_path.trim_start_matches('/'));
        fs::create_dir_all(&scope_dir).unwrap();
        let scope = SteamAppScope {
            unit: unit.to_owned(),
            cgroup_path,
            device: 0,
            inode: 0,
            root_pid: 456,
        };
        fs::remove_dir_all(scope_dir).unwrap();

        let result = SystemdScopeController::new(temporary.path().join("proc"), &cgroup_root, uid)
            .thaw(&scope);

        assert!(result.success, "{}", result.reason);
        assert!(result.disappeared);
    }
    #[test]
    fn launch_pid_identity_rejects_reused_pid_with_new_start_ticks() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let proc_root = temporary.path();
        let pid = 57;
        let proc_dir = proc_root.join(pid.to_string());
        fs::create_dir(&proc_dir).unwrap();
        let fields = std::iter::repeat_n("1", 18).collect::<Vec<_>>().join(" ");
        fs::write(
            proc_dir.join("stat"),
            format!("{pid} (fixture process) S {fields} 991"),
        )
        .unwrap();

        let identity = read_process_identity(proc_root, pid).unwrap();
        fs::write(
            proc_dir.join("stat"),
            format!("{pid} (fixture process) S {fields} 992"),
        )
        .unwrap();

        assert!(!same_process_identity(proc_root, &identity));
    }
    #[test]
    fn bootstrap_stop_is_released_when_scope_acquisition_unwinds() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let proc_root = temporary.path().join("proc");
        let cgroup_root = temporary.path().join("cgroup");
        fs::create_dir_all(&proc_root).unwrap();
        fs::create_dir_all(&cgroup_root).unwrap();
        let uid = unsafe { libc::geteuid() };
        let mut child = Command::new("/bin/sleep")
            .arg("30")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .process_group(0)
            .spawn()
            .unwrap();
        let pid = i32::try_from(child.id()).unwrap();
        let proc_dir = proc_root.join(pid.to_string());
        fs::create_dir(&proc_dir).unwrap();
        let fields = std::iter::repeat_n("1", 18).collect::<Vec<_>>().join(" ");
        fs::write(
            proc_dir.join("stat"),
            format!("{pid} (fixture process) S {fields} 991"),
        )
        .unwrap();
        let barriers = Arc::new((Barrier::new(2), Barrier::new(2)));
        let mut acquirer = LaunchScopeAcquirer::new(
            SystemdScopeController::new(&proc_root, &cgroup_root, uid),
            &proc_root,
            uid,
        );
        acquirer.panic_after_stop = Some(Arc::clone(&barriers));
        let worker = thread::spawn(move || {
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| acquirer.acquire(pid, None)))
                .is_err()
        });
        barriers.0.wait();
        let stop_deadline = Instant::now() + Duration::from_secs(1);
        while !thread_group_stopped(Path::new("/proc"), pid) && Instant::now() < stop_deadline {
            thread::sleep(Duration::from_millis(2));
        }
        let stopped_during_acquisition = thread_group_stopped(Path::new("/proc"), pid);
        barriers.1.wait();
        let panicked = worker.join().unwrap();
        let resume_deadline = Instant::now() + Duration::from_secs(1);
        while thread_group_stopped(Path::new("/proc"), pid) && Instant::now() < resume_deadline {
            thread::sleep(Duration::from_millis(2));
        }
        let resumed_after_unwind = !thread_group_stopped(Path::new("/proc"), pid);
        if !resumed_after_unwind {
            unsafe {
                libc::kill(pid, libc::SIGCONT);
            }
        }
        child.kill().unwrap();
        child.wait().unwrap();
        assert!(
            panicked,
            "fixture did not unwind after stopping the bootstrap PID"
        );
        assert!(
            stopped_during_acquisition,
            "fixture never observed the bootstrap PID stopped"
        );
        assert!(
            resumed_after_unwind,
            "bootstrap PID remained stopped after acquisition unwound"
        );
    }
}
