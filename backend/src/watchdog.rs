use std::{
    collections::BTreeMap,
    fs::File,
    io::{self, Read},
    path::Path,
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use std::os::unix::fs::MetadataExt;

use serde_json::{Value, json};

use crate::launch_gate::{
    LaunchProcessIdentity, LaunchScopeAcquirer, ScopeTransitionResult, SteamAppScope,
    SystemdScopeController, parse_start_ticks, thread_group_stopped,
};
use crate::operations::GuardedOperationResult;

const LEASE_TTL: Duration = Duration::from_secs(30);
const ABSOLUTE_RESUME: Duration = Duration::from_secs(240);
const WATCHDOG_INTERVAL: Duration = Duration::from_secs(1);
const GUARDED_COMPLETION_TIMEOUT: Duration = Duration::from_secs(2);
const SHUTDOWN_THAW_ATTEMPTS: usize = 3;
const SHUTDOWN_THAW_RETRY: Duration = Duration::from_millis(50);

#[derive(Clone)]
struct PauseLease {
    scope: Option<SteamAppScope>,
    recovery_scopes: Vec<SteamAppScope>,
    started: Instant,
    deadline: Instant,
    lease_id: String,
    identity: Option<LaunchProcessIdentity>,
    guarded_active: bool,
    cancellation: Option<Arc<AtomicBool>>,
    release_requested: bool,
    release_in_progress: bool,
}

#[derive(Default)]
struct State {
    leases: BTreeMap<i32, PauseLease>,
}

struct Inner {
    state: Mutex<State>,
    changed: Condvar,
    controller: SystemdScopeController,
    acquirer: LaunchScopeAcquirer,
    proc_root: std::path::PathBuf,
    stopping: AtomicBool,
    thread: Mutex<Option<JoinHandle<()>>>,
}

#[derive(Clone)]
pub struct ProcessWatchdog {
    inner: Arc<Inner>,
}

impl Default for ProcessWatchdog {
    fn default() -> Self {
        let controller = SystemdScopeController::default();
        let proc_root = Path::new("/proc").to_path_buf();
        let uid = unsafe { libc::geteuid() };
        let acquirer = LaunchScopeAcquirer::new(controller.clone(), proc_root.clone(), uid);
        Self {
            inner: Arc::new(Inner {
                state: Mutex::new(State::default()),
                changed: Condvar::new(),
                controller,
                acquirer,
                proc_root,
                stopping: AtomicBool::new(false),
                thread: Mutex::new(None),
            }),
        }
    }
}

impl ProcessWatchdog {
    pub fn pause(&self, pid: i32) -> Value {
        if let Err(message) = validate_pid(pid) {
            return json!({"status":"failed", "message":message});
        }
        if self.inner.stopping.load(Ordering::Acquire) {
            return gate_failure(pid, "Plugin shutdown is in progress");
        }
        let existing = lock(&self.inner.state).leases.get(&pid).cloned();
        if existing.as_ref().is_some_and(|lease| {
            lease.guarded_active || lease.release_requested || lease.release_in_progress
        }) {
            return gate_failure(
                pid,
                "Launch gate has a guarded operation or release in progress",
            );
        }
        let lease_id = match new_lease_id() {
            Ok(id) => id,
            Err(error) => {
                return gate_failure(pid, &format!("Unable to create launch lease: {error}"));
            }
        };
        if existing
            .as_ref()
            .is_some_and(|lease| !lease.recovery_scopes.is_empty())
        {
            return gate_failure(pid, "Scope recovery is still pending");
        }
        if let Err(error) = self.inner.ensure_watchdog() {
            return gate_failure(pid, &format!("Unable to start launch watchdog: {error}"));
        }
        let acquired = self.inner.acquirer.acquire(
            pid,
            existing.as_ref().and_then(|lease| lease.scope.as_ref()),
        );
        if !acquired.success || (acquired.scope.is_none() && !acquired.stop_only) {
            return gate_failure(pid, &acquired.reason);
        }
        let scope = acquired.scope;
        if let Some(previous) = existing.as_ref().filter(|lease| lease.scope != scope) {
            if let Some(previous_scope) = &previous.scope {
                let thawed = self.inner.controller.thaw(previous_scope);
                if !thawed.success {
                    let cleanup = match &scope {
                        Some(scope) => {
                            let result = self.inner.controller.thaw(scope);
                            result.success.then_some(()).ok_or(result.reason)
                        }
                        None => {
                            release_stop_only(&self.inner.proc_root, acquired.identity.as_ref())
                        }
                    };
                    let mut reason = format!("Unable to thaw previous scope: {}", thawed.reason);
                    if let Err(cleanup_reason) = cleanup {
                        reason.push_str(&format!(
                            "; unable to release acquired gate: {cleanup_reason}"
                        ));
                        if let Some(new_scope) = scope {
                            let mut state = lock(&self.inner.state);
                            if let Some(current) = state.leases.get_mut(&pid)
                                && current.lease_id == previous.lease_id
                            {
                                current.recovery_scopes.push(new_scope);
                            }
                        }
                    }
                    return gate_failure(pid, &reason);
                }
            }
            lock(&self.inner.state).leases.remove(&pid);
        }
        let now = Instant::now();
        let started = existing
            .as_ref()
            .filter(|lease| lease.scope == scope)
            .map_or(now, |lease| lease.started);
        lock(&self.inner.state).leases.insert(
            pid,
            PauseLease {
                scope,
                recovery_scopes: Vec::new(),
                started,
                deadline: now + LEASE_TTL,
                lease_id: lease_id.clone(),
                identity: acquired.identity,
                guarded_active: false,
                cancellation: None,
                release_requested: false,
                release_in_progress: false,
            },
        );
        self.inner.changed.notify_all();
        log::info!("Launch gate acquired for root PID {pid}");
        json!({"status":"paused", "pid":pid, "lease_id":lease_id, "lease_ttl_seconds":LEASE_TTL.as_secs()})
    }

    pub fn renew(&self, pid: i32, lease_id: &str) -> Value {
        if let Err(message) = validate_pid(pid) {
            return json!({"status":"failed", "message":message});
        }
        let mut state = lock(&self.inner.state);
        let Some(lease) = state.leases.get_mut(&pid) else {
            return gate_failure(pid, "Process not paused");
        };
        if lease.lease_id != lease_id {
            return gate_failure(pid, "Lease ID mismatch");
        }
        if lease.release_requested || lease.release_in_progress {
            return gate_failure(pid, "Launch gate release is already in progress");
        }
        if lease.scope.is_none() && stop_only_failure(&self.inner.proc_root, pid, lease).is_some() {
            return gate_failure(pid, "Stop-only launch gate identity changed");
        }
        for scope in lease.scope.iter().chain(lease.recovery_scopes.iter()) {
            let verified = verify_frozen(&self.inner.controller, scope);
            if !verified.success {
                return gate_failure(pid, &verified.reason);
            }
        }
        lease.deadline = Instant::now() + LEASE_TTL;
        json!({"status":"renewed", "pid":pid, "lease_ttl_seconds":LEASE_TTL.as_secs()})
    }

    pub fn verify_gate(&self, pid: i32, lease_id: &str) -> bool {
        if validate_pid(pid).is_err() {
            return false;
        }
        let state = lock(&self.inner.state);
        let Some(lease) = state.leases.get(&pid) else {
            return false;
        };
        if lease.lease_id != lease_id
            || lease.release_requested
            || lease.release_in_progress
            || current_expiry_reason(lease, Instant::now()).is_some()
        {
            return false;
        }
        if let Some(scope) = &lease.scope {
            verify_frozen(&self.inner.controller, scope).success
        } else {
            stop_only_failure(&self.inner.proc_root, pid, lease).is_none()
        }
    }

    pub fn resume(&self, pid: i32, lease_id: Option<&str>) -> Value {
        if let Err(message) = validate_pid(pid) {
            return json!({"status":"failed", "message":message});
        }
        let lease = {
            let mut state = lock(&self.inner.state);
            let Some(lease) = state.leases.get_mut(&pid) else {
                return gate_failure(pid, "Process not paused");
            };
            if lease_id.is_some_and(|id| id != lease.lease_id) {
                return gate_failure(pid, "Lease ID mismatch");
            }
            if lease.release_in_progress {
                return gate_failure(pid, "Launch gate release already in progress");
            }
            lease.release_requested = true;
            lease.release_in_progress = true;
            if let Some(cancel) = &lease.cancellation {
                cancel.store(true, Ordering::Release);
            }
            lease.clone()
        };
        let mut state = lock(&self.inner.state);
        let deadline = Instant::now() + GUARDED_COMPLETION_TIMEOUT;
        while state
            .leases
            .get(&pid)
            .is_some_and(|current| current.guarded_active)
        {
            let now = Instant::now();
            if now >= deadline {
                if let Some(current) = state.leases.get_mut(&pid) {
                    current.release_in_progress = false;
                }
                self.inner.changed.notify_all();
                return gate_failure(pid, "Guarded operation completion was not confirmed");
            }
            let (next, timeout) = self
                .inner
                .changed
                .wait_timeout(state, deadline - now)
                .unwrap_or_else(|error| error.into_inner());
            state = next;
            if timeout.timed_out()
                && state
                    .leases
                    .get(&pid)
                    .is_some_and(|current| current.guarded_active)
            {
                if let Some(current) = state.leases.get_mut(&pid) {
                    current.release_in_progress = false;
                }
                self.inner.changed.notify_all();
                return gate_failure(pid, "Guarded operation completion was not confirmed");
            }
        }
        drop(state);
        self.release_lease(pid, &lease)
    }

    pub(crate) fn run_guarded<T>(
        &self,
        pid: i32,
        lease_id: &str,
        callback: impl FnOnce(Arc<AtomicBool>) -> GuardedOperationResult<T>,
    ) -> Option<T> {
        if validate_pid(pid).is_err() || lease_id.is_empty() {
            return None;
        }
        let cancel = Arc::new(AtomicBool::new(false));
        {
            let mut state = lock(&self.inner.state);
            let lease = state.leases.get(&pid)?;
            if lease.lease_id != lease_id
                || lease.guarded_active
                || lease.release_requested
                || lease.release_in_progress
                || current_expiry_reason(lease, Instant::now()).is_some()
            {
                return None;
            }
            let valid = lease.scope.as_ref().map_or_else(
                || stop_only_failure(&self.inner.proc_root, pid, lease).is_none(),
                |scope| verify_frozen(&self.inner.controller, scope).success,
            );
            if !valid {
                return None;
            }
            let lease = state.leases.get_mut(&pid)?;
            lease.guarded_active = true;
            lease.cancellation = Some(Arc::clone(&cancel));
        }
        let mut result = callback(Arc::clone(&cancel));
        result.completion.wait(Some(&cancel));
        let release_requested = {
            let mut state = lock(&self.inner.state);
            let lease = state.leases.get_mut(&pid)?;
            lease.guarded_active = false;
            lease.cancellation = None;
            let requested = lease.release_requested;
            self.inner.changed.notify_all();
            requested
        };
        (!release_requested).then_some(result.result)
    }

    pub fn resume_all(&self) {
        let pids = lock(&self.inner.state)
            .leases
            .keys()
            .copied()
            .collect::<Vec<_>>();
        for pid in pids {
            let _ = self.resume(pid, None);
        }
    }

    pub fn stop(&self) -> bool {
        self.inner.stopping.store(true, Ordering::Release);
        self.inner.changed.notify_all();
        if let Some(thread) = lock(&self.inner.thread).take()
            && thread.thread().id() != thread::current().id()
        {
            let _ = thread.join();
        }
        for attempt in 0..SHUTDOWN_THAW_ATTEMPTS {
            self.resume_all();
            if lock(&self.inner.state).leases.is_empty() {
                return true;
            }
            if attempt + 1 < SHUTDOWN_THAW_ATTEMPTS {
                thread::sleep(SHUTDOWN_THAW_RETRY);
            }
        }
        let count = lock(&self.inner.state).leases.len();
        log::error!(
            "Shutdown left {count} launch-gate lease(s) unconfirmed after {SHUTDOWN_THAW_ATTEMPTS} thaw attempts"
        );
        false
    }

    fn release_lease(&self, pid: i32, lease: &PauseLease) -> Value {
        if let Some(scope) = &lease.scope {
            for owned in std::iter::once(scope).chain(lease.recovery_scopes.iter()) {
                let result = self.inner.controller.thaw(owned);
                if !result.success {
                    if let Some(current) = lock(&self.inner.state).leases.get_mut(&pid) {
                        current.release_in_progress = false;
                    }
                    return gate_failure(pid, &result.reason);
                }
            }
        } else if let Err(message) =
            release_stop_only(&self.inner.proc_root, lease.identity.as_ref())
        {
            if let Some(current) = lock(&self.inner.state).leases.get_mut(&pid) {
                current.release_in_progress = false;
            }
            return gate_failure(pid, &message);
        }
        let mut state = lock(&self.inner.state);
        if state
            .leases
            .get(&pid)
            .is_some_and(|current| current.lease_id == lease.lease_id)
        {
            state.leases.remove(&pid);
        }
        json!({"status":"resumed", "pid":pid})
    }
}

impl Inner {
    fn ensure_watchdog(self: &Arc<Self>) -> io::Result<()> {
        let mut thread_slot = lock(&self.thread);
        if thread_slot.as_ref().is_some_and(JoinHandle::is_finished) {
            thread_slot.take();
        }
        if thread_slot.is_some() {
            return Ok(());
        }
        if self.stopping.load(Ordering::Acquire) {
            return Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "watchdog is stopping",
            ));
        }
        let weak = Arc::downgrade(self);
        *thread_slot = Some(
            thread::Builder::new()
                .name("sdh-ludusavi-watchdog".to_owned())
                .spawn(move || {
                    while let Some(inner) = weak.upgrade() {
                        let state = lock(&inner.state);
                        if inner.stopping.load(Ordering::Acquire) {
                            break;
                        }
                        let (state, _) = inner
                            .changed
                            .wait_timeout(state, WATCHDOG_INTERVAL)
                            .unwrap_or_else(|error| error.into_inner());
                        if inner.stopping.load(Ordering::Acquire) {
                            break;
                        }
                        let now = Instant::now();
                        let expired = state
                            .leases
                            .iter()
                            .filter_map(|(&pid, lease)| {
                                current_expiry_reason(lease, now)
                                    .map(|reason| (pid, lease.lease_id.clone(), reason))
                            })
                            .collect::<Vec<_>>();
                        drop(state);
                        for (pid, lease_id, reason) in expired {
                            log::warn!(
                                "Watchdog releasing launch gate for root PID {pid}: {reason}"
                            );
                            let watchdog = ProcessWatchdog {
                                inner: Arc::clone(&inner),
                            };
                            let _ = watchdog.resume(pid, Some(&lease_id));
                        }
                    }
                })?,
        );
        Ok(())
    }
}

fn current_expiry_reason(lease: &PauseLease, now: Instant) -> Option<&'static str> {
    lease_expiry_reason(
        0.0,
        lease.deadline.duration_since(lease.started).as_secs_f64(),
        now.duration_since(lease.started).as_secs_f64(),
    )
}

pub(crate) fn lease_expiry_reason(
    paused_at: f64,
    lease_deadline: f64,
    now: f64,
) -> Option<&'static str> {
    if now - paused_at > ABSOLUTE_RESUME.as_secs_f64() {
        Some("absolute ceiling")
    } else if now > lease_deadline {
        Some("lease expired")
    } else {
        None
    }
}

fn verify_frozen(
    controller: &SystemdScopeController,
    scope: &SteamAppScope,
) -> ScopeTransitionResult {
    if !controller.freeze_requested(scope) {
        return ScopeTransitionResult {
            success: false,
            reason: "Steam app scope is no longer frozen".to_owned(),
            disappeared: false,
        };
    }
    controller.wait_for_frozen(scope, true)
}

fn validate_pid(pid: i32) -> Result<(), String> {
    if (2..=2_147_483_647).contains(&pid) {
        Ok(())
    } else {
        Err("PID is outside the safe process range".to_owned())
    }
}

fn stop_only_failure(proc_root: &Path, pid: i32, lease: &PauseLease) -> Option<String> {
    let Some(identity) = lease.identity.as_ref() else {
        return Some("Launch PID identity changed".to_owned());
    };
    if process_identity(proc_root, pid).as_ref() != Some(identity) {
        return Some("Launch PID identity changed".to_owned());
    }
    if !thread_group_stopped(proc_root, pid) {
        return Some("Launch PID is no longer stopped".to_owned());
    }
    None
}

fn process_identity(proc_root: &Path, pid: i32) -> Option<LaunchProcessIdentity> {
    let dir = proc_root.join(pid.to_string());
    let owner_uid = std::fs::metadata(&dir).ok()?.uid();
    let stat = std::fs::read_to_string(dir.join("stat")).ok()?;
    Some(LaunchProcessIdentity {
        pid,
        owner_uid,
        start_ticks: parse_start_ticks(&stat, pid)?,
    })
}

fn release_stop_only(
    proc_root: &Path,
    identity: Option<&LaunchProcessIdentity>,
) -> Result<(), String> {
    let Some(identity) = identity else {
        return Err("Stop-only lease has no process identity".to_owned());
    };
    if process_identity(proc_root, identity.pid).as_ref() != Some(identity) {
        return Ok(());
    }
    if unsafe { libc::kill(identity.pid, libc::SIGCONT) } == 0 {
        Ok(())
    } else {
        Err(format!(
            "Unable to release stopped launch PID: {}",
            io::Error::last_os_error()
        ))
    }
}

fn gate_failure(pid: i32, message: &str) -> Value {
    json!({"status":"failed", "pid":pid, "message":message})
}

fn new_lease_id() -> io::Result<String> {
    let mut random = [0u8; 16];
    File::open("/dev/urandom")?.read_exact(&mut random)?;
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(32);
    for byte in random {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 15) as usize] as char);
    }
    Ok(result)
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}
#[cfg(test)]
mod tests {
    use std::{
        fs,
        os::unix::process::CommandExt,
        process::{Command, Stdio},
        sync::mpsc,
        thread,
        time::Duration,
    };

    use tempfile::tempdir_in;

    use super::{Inner, LEASE_TTL, PauseLease, ProcessWatchdog, State, lock};
    use crate::{
        launch_gate::{LaunchProcessIdentity, LaunchScopeAcquirer, SystemdScopeController},
        operations::{GuardedOperationResult, ProcessGroupCompletion},
    };

    #[test]
    fn guarded_lease_stays_pinned_until_process_group_exit_is_confirmed() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let proc_root = temporary.path().join("proc");
        let cgroup_root = temporary.path().join("cgroup");
        fs::create_dir_all(&proc_root).unwrap();
        fs::create_dir_all(&cgroup_root).unwrap();
        let uid = unsafe { libc::geteuid() };
        let controller = SystemdScopeController::new(&proc_root, &cgroup_root, uid);
        let acquirer = LaunchScopeAcquirer::new(controller.clone(), &proc_root, uid);
        let watchdog = ProcessWatchdog {
            inner: std::sync::Arc::new(Inner {
                state: std::sync::Mutex::new(State::default()),
                changed: std::sync::Condvar::new(),
                controller,
                acquirer,
                proc_root: proc_root.clone(),
                stopping: std::sync::atomic::AtomicBool::new(false),
                thread: std::sync::Mutex::new(None),
            }),
        };
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
        let task_dir = proc_dir.join("task").join(pid.to_string());
        fs::create_dir_all(&task_dir).unwrap();
        let fields = std::iter::repeat_n("1", 18).collect::<Vec<_>>().join(" ");
        let stat = format!("{pid} (fixture process) T {fields} 991");
        fs::write(proc_dir.join("stat"), &stat).unwrap();
        fs::write(task_dir.join("stat"), &stat).unwrap();
        lock(&watchdog.inner.state).leases.insert(
            pid,
            PauseLease {
                scope: None,
                recovery_scopes: Vec::new(),
                started: std::time::Instant::now(),
                deadline: std::time::Instant::now() + LEASE_TTL,
                lease_id: "guarded-test".to_owned(),
                identity: Some(LaunchProcessIdentity {
                    pid,
                    owner_uid: uid,
                    start_ticks: 991,
                }),
                guarded_active: false,
                cancellation: None,
                release_requested: false,
                release_in_progress: false,
            },
        );

        let (done_sender, done_receiver) = mpsc::channel();
        let guarded_watchdog = watchdog.clone();
        let mut worker = Some(thread::spawn(move || {
            let _ = guarded_watchdog.run_guarded(pid, "guarded-test", |_| GuardedOperationResult {
                result: (),
                completion: ProcessGroupCompletion::pending(pid),
            });
            done_sender.send(()).unwrap();
        }));
        let completed_early = done_receiver
            .recv_timeout(Duration::from_millis(100))
            .is_ok();
        if completed_early {
            child.kill().unwrap();
            child.wait().unwrap();
            worker.take().unwrap().join().unwrap();
        }
        assert!(
            !completed_early,
            "guarded lease completed while its process group was still alive"
        );
        assert!(
            lock(&watchdog.inner.state).leases[&pid].guarded_active,
            "guarded lease was not retained while process exit was unconfirmed"
        );

        child.kill().unwrap();
        child.wait().unwrap();
        done_receiver.recv_timeout(Duration::from_secs(1)).unwrap();
        worker.unwrap().join().unwrap();
    }
}
