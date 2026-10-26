use std::{
    collections::BTreeMap,
    fs::File,
    io::{self, Read},
    path::Path,
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use std::os::unix::fs::MetadataExt;

use serde_json::{Value, json};

use crate::launch_gate::{
    LaunchProcessIdentity, LaunchScopeAcquirer, ScopeAcquisitionResult, ScopeTransitionResult,
    SteamAppScope, SystemdScopeController, parse_start_ticks, thread_group_stopped,
};
use crate::operations::ProcessGroupCompletion;

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
    generation: u64,
    guarded_generation: u64,
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
    acquirer: Arc<dyn ScopeAcquirer>,
    proc_root: std::path::PathBuf,
    transition_locks: Mutex<BTreeMap<i32, Arc<Mutex<()>>>>,
    next_generation: AtomicU64,
    stopping: AtomicBool,
    thread: Mutex<Option<JoinHandle<()>>>,
    shutdown_deadline: Mutex<Option<Instant>>,
    #[cfg(test)]
    stop_hook: Mutex<Option<Arc<dyn Fn() + Send + Sync>>>,
}

trait ScopeAcquirer: Send + Sync {
    fn acquire(&self, pid: i32, existing_scope: Option<&SteamAppScope>) -> ScopeAcquisitionResult;
}

impl ScopeAcquirer for LaunchScopeAcquirer {
    fn acquire(&self, pid: i32, existing_scope: Option<&SteamAppScope>) -> ScopeAcquisitionResult {
        LaunchScopeAcquirer::acquire(self, pid, existing_scope)
    }
}

#[derive(Clone)]
pub struct ProcessWatchdog {
    inner: Arc<Inner>,
}
struct GuardedOperationGuard {
    inner: Arc<Inner>,
    pid: i32,
    generation: u64,
    guarded_generation: u64,
    cancellation: Arc<AtomicBool>,
    completion: ProcessGroupCompletion,
    finalized: bool,
}

impl GuardedOperationGuard {
    fn finalize(&self) -> Option<bool> {
        let transition = self.inner.transition_lock(self.pid);
        let _transition = lock(&transition);
        let mut state = lock(&self.inner.state);
        let Some(lease) = state.leases.get_mut(&self.pid) else {
            self.inner.changed.notify_all();
            return None;
        };
        if lease.generation != self.generation
            || lease.guarded_generation != self.guarded_generation
        {
            self.inner.changed.notify_all();
            return None;
        }
        lease.guarded_active = false;
        lease.cancellation = None;
        let release_requested = lease.release_requested;
        self.inner.changed.notify_all();
        Some(release_requested)
    }

    fn finish(&mut self) -> Option<bool> {
        self.completion.wait(Some(&self.cancellation));
        let release_requested = self.finalize();
        self.finalized = true;
        release_requested
    }
}

impl Drop for GuardedOperationGuard {
    fn drop(&mut self) {
        if self.finalized {
            return;
        }
        self.cancellation.store(true, Ordering::Release);
        self.completion.wait(Some(&self.cancellation));
        let _ = self.finalize();
        self.finalized = true;
    }
}

impl Default for ProcessWatchdog {
    fn default() -> Self {
        let controller = SystemdScopeController::default();
        let proc_root = Path::new("/proc").to_path_buf();
        let uid = unsafe { libc::geteuid() };
        let acquirer: Arc<dyn ScopeAcquirer> = Arc::new(LaunchScopeAcquirer::new(
            controller.clone(),
            proc_root.clone(),
            uid,
        ));
        Self {
            inner: Arc::new(Inner {
                state: Mutex::new(State::default()),
                changed: Condvar::new(),
                controller,
                acquirer,
                proc_root,
                transition_locks: Mutex::new(BTreeMap::new()),
                next_generation: AtomicU64::new(1),
                stopping: AtomicBool::new(false),
                thread: Mutex::new(None),
                #[cfg(test)]
                stop_hook: Mutex::new(None),
                shutdown_deadline: Mutex::new(None),
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
        let transition = self.inner.transition_lock(pid);
        let _transition = lock(&transition);
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
                                && current.generation == previous.generation
                            {
                                current.recovery_scopes.push(new_scope);
                            }
                        }
                    }
                    return gate_failure(pid, &reason);
                }
            }
            let mut state = lock(&self.inner.state);
            if state
                .leases
                .get(&pid)
                .is_some_and(|current| current.generation == previous.generation)
            {
                state.leases.remove(&pid);
            }
        }
        let now = Instant::now();
        let started = existing
            .as_ref()
            .filter(|lease| lease.scope == scope)
            .map_or(now, |lease| lease.started);
        let generation = self.inner.next_generation.fetch_add(1, Ordering::Relaxed);
        lock(&self.inner.state).leases.insert(
            pid,
            PauseLease {
                scope,
                recovery_scopes: Vec::new(),
                started,
                deadline: now + LEASE_TTL,
                lease_id: lease_id.clone(),
                identity: acquired.identity,
                generation,
                guarded_generation: 0,
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
        let transition = self.inner.transition_lock(pid);
        let _transition = lock(&transition);
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
        let transition = self.inner.transition_lock(pid);
        let _transition = lock(&transition);
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
        self.resume_until(pid, lease_id, None)
    }

    fn resume_until(
        &self,
        pid: i32,
        lease_id: Option<&str>,
        mut shutdown_deadline: Option<Instant>,
    ) -> Value {
        shutdown_deadline = shutdown_deadline.or_else(|| *lock(&self.inner.shutdown_deadline));
        if let Err(message) = validate_pid(pid) {
            return json!({"status":"failed", "message":message});
        }
        if shutdown_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            return gate_failure(pid, "Shutdown deadline expired; launch gate retained");
        }
        let transition = self.inner.transition_lock(pid);
        let lease = {
            let _transition = if let Some(deadline) = shutdown_deadline {
                let Some(transition) = lock_until(&transition, deadline) else {
                    return gate_failure(pid, "Shutdown deadline expired; launch gate retained");
                };
                transition
            } else {
                lock(&transition)
            };
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
        let generation = lease.generation;
        let now = Instant::now();
        let mut guarded_deadline = shutdown_deadline
            .map_or(now + GUARDED_COMPLETION_TIMEOUT, |deadline| {
                deadline.min(now + GUARDED_COMPLETION_TIMEOUT)
            });
        let mut state = lock(&self.inner.state);
        while state
            .leases
            .get(&pid)
            .is_some_and(|current| current.generation == generation && current.guarded_active)
        {
            shutdown_deadline = shutdown_deadline.or_else(|| *lock(&self.inner.shutdown_deadline));
            if let Some(deadline) = shutdown_deadline {
                guarded_deadline = guarded_deadline.min(deadline);
            }
            let now = Instant::now();
            if now >= guarded_deadline {
                drop(state);
                self.reset_release(pid, generation);
                return gate_failure(
                    pid,
                    "Guarded operation completion was not confirmed; launch gate retained",
                );
            }
            let (next, _) = self
                .inner
                .changed
                .wait_timeout(state, guarded_deadline - now)
                .unwrap_or_else(|error| error.into_inner());
            state = next;
        }
        drop(state);
        shutdown_deadline = shutdown_deadline.or_else(|| *lock(&self.inner.shutdown_deadline));
        if shutdown_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            self.reset_release(pid, generation);
            return gate_failure(pid, "Shutdown deadline expired; launch gate retained");
        }
        let _transition = if let Some(deadline) = shutdown_deadline {
            let Some(transition) = lock_until(&transition, deadline) else {
                self.reset_release(pid, generation);
                return gate_failure(pid, "Shutdown deadline expired; launch gate retained");
            };
            transition
        } else {
            lock(&transition)
        };
        if !lock(&self.inner.state)
            .leases
            .get(&pid)
            .is_some_and(|current| current.generation == generation)
        {
            return gate_failure(pid, "Lease changed during release");
        }
        self.release_lease(pid, &lease, shutdown_deadline)
    }

    fn reset_release(&self, pid: i32, generation: u64) {
        if let Some(current) = lock(&self.inner.state).leases.get_mut(&pid)
            && current.generation == generation
        {
            current.release_in_progress = false;
        }
        self.inner.changed.notify_all();
    }

    pub(crate) fn run_guarded<T>(
        &self,
        pid: i32,
        lease_id: &str,
        callback: impl FnOnce(Arc<AtomicBool>, &mut ProcessGroupCompletion) -> T,
    ) -> Option<T> {
        if validate_pid(pid).is_err() || lease_id.is_empty() {
            return None;
        }
        let cancel = Arc::new(AtomicBool::new(false));
        let transition = self.inner.transition_lock(pid);
        let (generation, guarded_generation) = {
            let _transition = lock(&transition);
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
            lease.guarded_generation += 1;
            lease.guarded_active = true;
            lease.cancellation = Some(Arc::clone(&cancel));
            (lease.generation, lease.guarded_generation)
        };
        let mut operation = GuardedOperationGuard {
            inner: Arc::clone(&self.inner),
            pid,
            generation,
            guarded_generation,
            cancellation: Arc::clone(&cancel),
            completion: ProcessGroupCompletion::confirmed(),
            finalized: false,
        };
        let result = callback(cancel, &mut operation.completion);
        let release_requested = operation.finish()?;
        (!release_requested).then_some(result)
    }

    #[cfg(test)]
    pub(crate) fn set_stop_hook(&self, hook: Arc<dyn Fn() + Send + Sync>) {
        *lock(&self.inner.stop_hook) = Some(hook);
    }

    pub(crate) fn stop_until(&self, deadline: Instant) -> bool {
        let mut stored_deadline = lock(&self.inner.shutdown_deadline);
        *stored_deadline =
            Some((*stored_deadline).map_or(deadline, |current| current.min(deadline)));
        drop(stored_deadline);
        self.inner.stopping.store(true, Ordering::Release);
        self.inner.changed.notify_all();
        #[cfg(test)]
        if let Some(hook) = lock(&self.inner.stop_hook).clone() {
            hook();
        }
        loop {
            let current = thread::current().id();
            let mut slot = lock(&self.inner.thread);
            match slot.as_ref() {
                None => break,
                Some(thread) if thread.thread().id() == current => {
                    drop(slot);
                    return self.report_unconfirmed_leases();
                }
                Some(thread) if thread.is_finished() => {
                    let finished = slot.take().unwrap();
                    drop(slot);
                    let _ = finished.join();
                    break;
                }
                Some(_) if Instant::now() >= deadline => {
                    drop(slot);
                    return self.report_unconfirmed_leases();
                }
                Some(_) => {
                    drop(slot);
                    thread::sleep(
                        Duration::from_millis(10)
                            .min(deadline.saturating_duration_since(Instant::now())),
                    );
                }
            }
        }
        for attempt in 0..SHUTDOWN_THAW_ATTEMPTS {
            if Instant::now() >= deadline {
                break;
            }
            let pids = lock(&self.inner.state)
                .leases
                .keys()
                .copied()
                .collect::<Vec<_>>();
            for pid in pids {
                if Instant::now() >= deadline {
                    break;
                }
                let _ = self.resume_until(pid, None, Some(deadline));
            }
            if lock(&self.inner.state).leases.is_empty() {
                return true;
            }
            if attempt + 1 < SHUTDOWN_THAW_ATTEMPTS && Instant::now() < deadline {
                thread::sleep(
                    SHUTDOWN_THAW_RETRY.min(deadline.saturating_duration_since(Instant::now())),
                );
            }
        }
        self.report_unconfirmed_leases()
    }

    fn report_unconfirmed_leases(&self) -> bool {
        let count = lock(&self.inner.state).leases.len();
        log::error!(
            "Shutdown left {count} launch-gate lease(s) unconfirmed; retaining remaining gates"
        );
        false
    }

    fn release_lease(
        &self,
        pid: i32,
        lease: &PauseLease,
        shutdown_deadline: Option<Instant>,
    ) -> Value {
        let mut shutdown_deadline =
            shutdown_deadline.or_else(|| *lock(&self.inner.shutdown_deadline));
        if shutdown_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            self.reset_release(pid, lease.generation);
            return gate_failure(pid, "Shutdown deadline expired; launch gate retained");
        }
        if let Some(scope) = &lease.scope {
            let mut failed_scopes = Vec::new();
            let mut failure_reason = None;
            let mut scopes = std::iter::once(scope)
                .chain(lease.recovery_scopes.iter())
                .peekable();
            while let Some(owned) = scopes.next() {
                shutdown_deadline =
                    shutdown_deadline.or_else(|| *lock(&self.inner.shutdown_deadline));
                if shutdown_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
                    failure_reason.get_or_insert_with(|| {
                        "Shutdown deadline expired; launch gate retained".to_owned()
                    });
                    failed_scopes.push(owned.clone());
                    failed_scopes.extend(scopes.cloned());
                    break;
                }
                let result = shutdown_deadline.map_or_else(
                    || self.inner.controller.thaw(owned),
                    |deadline| self.inner.controller.thaw_until(owned, deadline),
                );
                if !result.success {
                    failure_reason.get_or_insert(result.reason);
                    failed_scopes.push(owned.clone());
                }
            }
            if !failed_scopes.is_empty() {
                let mut state = lock(&self.inner.state);
                if let Some(current) = state
                    .leases
                    .get_mut(&pid)
                    .filter(|current| current.generation == lease.generation)
                {
                    current.scope = failed_scopes.first().cloned();
                    current.recovery_scopes = failed_scopes.into_iter().skip(1).collect();
                    current.release_in_progress = false;
                }
                drop(state);
                self.inner.changed.notify_all();
                return gate_failure(
                    pid,
                    failure_reason
                        .as_deref()
                        .unwrap_or("Scope release failed; launch gate retained"),
                );
            }
        } else if let Err(message) =
            release_stop_only(&self.inner.proc_root, lease.identity.as_ref())
        {
            self.reset_release(pid, lease.generation);
            return gate_failure(pid, &message);
        }
        let mut state = lock(&self.inner.state);
        if state
            .leases
            .get(&pid)
            .is_some_and(|current| current.generation == lease.generation)
        {
            state.leases.remove(&pid);
        }
        json!({"status":"resumed", "pid":pid})
    }
}

impl Inner {
    fn transition_lock(&self, pid: i32) -> Arc<Mutex<()>> {
        Arc::clone(
            lock(&self.transition_locks)
                .entry(pid)
                .or_insert_with(|| Arc::new(Mutex::new(()))),
        )
    }

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
fn lock_until<T>(mutex: &Mutex<T>, deadline: Instant) -> Option<std::sync::MutexGuard<'_, T>> {
    loop {
        match mutex.try_lock() {
            Ok(guard) => return Some(guard),
            Err(std::sync::TryLockError::Poisoned(error)) => return Some(error.into_inner()),
            Err(std::sync::TryLockError::WouldBlock) => {
                let now = Instant::now();
                if now >= deadline {
                    return None;
                }
                thread::sleep(Duration::from_millis(1).min(deadline - now));
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use std::{
        fs,
        os::unix::process::CommandExt,
        path::Path,
        process::{Command, Stdio},
        sync::{Arc, Barrier, mpsc},
        thread,
        time::Duration,
    };

    use tempfile::tempdir_in;

    use super::{
        Inner, LEASE_TTL, PauseLease, ProcessWatchdog, ScopeAcquirer, State, lock,
        thread_group_stopped,
    };
    use crate::{
        launch_gate::{
            LaunchProcessIdentity, LaunchScopeAcquirer, ScopeAcquisitionResult,
            ScopeTransitionResult, SteamAppScope, SystemdScopeController,
        },
        operations::ProcessGroupCompletion,
    };

    fn test_watchdog(
        controller: SystemdScopeController,
        proc_root: std::path::PathBuf,
        acquirer: Arc<dyn ScopeAcquirer>,
    ) -> ProcessWatchdog {
        ProcessWatchdog {
            inner: Arc::new(Inner {
                state: std::sync::Mutex::new(State::default()),
                changed: std::sync::Condvar::new(),
                controller,
                acquirer,
                proc_root,
                transition_locks: std::sync::Mutex::new(std::collections::BTreeMap::new()),
                next_generation: std::sync::atomic::AtomicU64::new(2),
                stopping: std::sync::atomic::AtomicBool::new(false),
                thread: std::sync::Mutex::new(None),
                #[cfg(test)]
                stop_hook: std::sync::Mutex::new(None),
                shutdown_deadline: std::sync::Mutex::new(None),
            }),
        }
    }

    #[test]
    fn release_attempts_every_scope_and_retains_only_failures() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let proc_root = temporary.path().join("proc");
        fs::create_dir_all(&proc_root).unwrap();
        let cgroup_root = temporary.path().join("cgroup");
        fs::create_dir_all(&cgroup_root).unwrap();
        let controller =
            SystemdScopeController::new(&proc_root, &cgroup_root, unsafe { libc::geteuid() });
        let attempted = Arc::new(std::sync::Mutex::new(Vec::new()));
        let attempted_by_hook = Arc::clone(&attempted);
        let failed_unit = "app-steam-app1-2.scope".to_owned();
        let failed_recovery_unit = "app-steam-app5-6.scope".to_owned();
        let failed_unit_by_hook = failed_unit.clone();
        let failed_recovery_by_hook = failed_recovery_unit.clone();
        controller.set_thaw_hook(Arc::new(move |scope| {
            lock(&attempted_by_hook).push(scope.unit.clone());
            let failed = scope.unit == failed_unit_by_hook || scope.unit == failed_recovery_by_hook;
            ScopeTransitionResult {
                success: !failed,
                reason: if failed {
                    "scope remains frozen".to_owned()
                } else {
                    String::new()
                },
                disappeared: false,
            }
        }));
        let uid = unsafe { libc::geteuid() };
        let acquirer = Arc::new(LaunchScopeAcquirer::new(
            controller.clone(),
            proc_root.clone(),
            uid,
        ));
        let watchdog = test_watchdog(controller, proc_root, acquirer);
        let pid = 42;
        let primary = SteamAppScope {
            unit: failed_unit.clone(),
            cgroup_path: "/user.slice/app-steam-app1-2.scope".to_owned(),
            root_pid: pid,
            device: 1,
            inode: 2,
        };
        let recovery = SteamAppScope {
            unit: "app-steam-app3-4.scope".to_owned(),
            cgroup_path: "/user.slice/app-steam-app3-4.scope".to_owned(),
            root_pid: pid,
            device: 1,
            inode: 3,
        };
        let failed_recovery = SteamAppScope {
            unit: failed_recovery_unit.clone(),
            cgroup_path: "/user.slice/app-steam-app5-6.scope".to_owned(),
            root_pid: pid,
            device: 1,
            inode: 4,
        };
        lock(&watchdog.inner.state).leases.insert(
            pid,
            PauseLease {
                scope: Some(primary),
                recovery_scopes: vec![recovery, failed_recovery.clone()],
                started: std::time::Instant::now(),
                deadline: std::time::Instant::now() + LEASE_TTL,
                lease_id: "multi-scope-release".to_owned(),
                identity: None,
                generation: 1,
                guarded_generation: 0,
                guarded_active: false,
                cancellation: None,
                release_requested: false,
                release_in_progress: false,
            },
        );

        let result = watchdog.resume(pid, None);

        assert_eq!(result["status"], "failed");
        assert_eq!(
            *lock(&attempted),
            [
                "app-steam-app1-2.scope",
                "app-steam-app3-4.scope",
                "app-steam-app5-6.scope"
            ]
        );
        let state = lock(&watchdog.inner.state);
        let lease = state.leases.get(&pid).unwrap();
        assert_eq!(lease.scope.as_ref().unwrap().unit, failed_unit);
        assert_eq!(lease.recovery_scopes, vec![failed_recovery]);
        assert!(!lease.release_in_progress);
    }

    #[test]
    fn shutdown_deadline_retains_stop_only_gate() {
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
        let task_dir = proc_dir.join("task").join(pid.to_string());
        fs::create_dir_all(&task_dir).unwrap();
        let fields = std::iter::repeat_n("1", 18).collect::<Vec<_>>().join(" ");
        let stat = format!("{pid} (fixture process) T {fields} 991");
        fs::write(proc_dir.join("stat"), &stat).unwrap();
        fs::write(task_dir.join("stat"), &stat).unwrap();
        unsafe {
            libc::kill(pid, libc::SIGSTOP);
        }
        let stop_deadline = std::time::Instant::now() + Duration::from_secs(1);
        while !thread_group_stopped(Path::new("/proc"), pid)
            && std::time::Instant::now() < stop_deadline
        {
            thread::sleep(Duration::from_millis(2));
        }

        let controller = SystemdScopeController::new(&proc_root, &cgroup_root, uid);
        let acquirer: Arc<dyn ScopeAcquirer> = Arc::new(LaunchScopeAcquirer::new(
            controller.clone(),
            &proc_root,
            uid,
        ));
        let watchdog = test_watchdog(controller, proc_root, acquirer);
        lock(&watchdog.inner.state).leases.insert(
            pid,
            PauseLease {
                scope: None,
                recovery_scopes: Vec::new(),
                started: std::time::Instant::now(),
                deadline: std::time::Instant::now() + LEASE_TTL,
                lease_id: "shutdown-lease".to_owned(),
                identity: Some(LaunchProcessIdentity {
                    pid,
                    owner_uid: uid,
                    start_ticks: 991,
                }),
                generation: 1,
                guarded_generation: 0,
                guarded_active: false,
                cancellation: None,
                release_requested: false,
                release_in_progress: false,
            },
        );
        let entered = Arc::new(Barrier::new(2));
        let release = Arc::new(Barrier::new(2));
        let hook_entered = Arc::clone(&entered);
        let hook_release = Arc::clone(&release);
        watchdog.set_stop_hook(Arc::new(move || {
            hook_entered.wait();
            hook_release.wait();
        }));
        let shutdown_watchdog = watchdog.clone();
        let deadline = std::time::Instant::now() + Duration::from_millis(30);
        let worker = thread::spawn(move || shutdown_watchdog.stop_until(deadline));
        entered.wait();
        thread::sleep(Duration::from_millis(50));
        release.wait();
        let completed = worker.join().unwrap();
        let gate_retained = lock(&watchdog.inner.state).leases.contains_key(&pid);
        let process_stopped = thread_group_stopped(Path::new("/proc"), pid);
        let _ = watchdog.resume(pid, None);
        child.kill().unwrap();
        child.wait().unwrap();
        assert!(!completed, "shutdown succeeded beyond its deadline");
        assert!(gate_retained, "shutdown discarded an unthawed launch lease");
        assert!(
            process_stopped,
            "shutdown released a gate after its deadline"
        );
    }

    #[test]
    fn guarded_lease_stays_pinned_until_process_group_exit_is_confirmed() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let proc_root = temporary.path().join("proc");
        let cgroup_root = temporary.path().join("cgroup");
        fs::create_dir_all(&proc_root).unwrap();
        fs::create_dir_all(&cgroup_root).unwrap();
        let uid = unsafe { libc::geteuid() };
        let controller = SystemdScopeController::new(&proc_root, &cgroup_root, uid);
        let acquirer: Arc<dyn ScopeAcquirer> = Arc::new(LaunchScopeAcquirer::new(
            controller.clone(),
            &proc_root,
            uid,
        ));
        let watchdog = test_watchdog(controller, proc_root.clone(), acquirer);
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
                generation: 1,
                guarded_generation: 0,
                guarded_active: false,
                cancellation: None,
                release_requested: false,
                release_in_progress: false,
            },
        );

        let (done_sender, done_receiver) = mpsc::channel();
        let guarded_watchdog = watchdog.clone();
        let mut worker = Some(thread::spawn(move || {
            let _ = guarded_watchdog.run_guarded(pid, "guarded-test", |_, completion| {
                *completion = ProcessGroupCompletion::pending(pid);
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
    struct BlockingAcquirer {
        barriers: Arc<(Barrier, Barrier)>,
        identity: LaunchProcessIdentity,
    }

    impl ScopeAcquirer for BlockingAcquirer {
        fn acquire(
            &self,
            _pid: i32,
            _existing_scope: Option<&super::SteamAppScope>,
        ) -> ScopeAcquisitionResult {
            self.barriers.0.wait();
            self.barriers.1.wait();
            ScopeAcquisitionResult {
                success: true,
                scope: None,
                stop_only: true,
                reason: String::new(),
                identity: Some(self.identity.clone()),
            }
        }
    }

    #[test]
    fn pause_serializes_replacement_against_guarded_lease_pinning() {
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
        let task_dir = proc_dir.join("task").join(pid.to_string());
        fs::create_dir_all(&task_dir).unwrap();
        let fields = std::iter::repeat_n("1", 18).collect::<Vec<_>>().join(" ");
        let stat = format!("{pid} (fixture process) T {fields} 991");
        fs::write(proc_dir.join("stat"), &stat).unwrap();
        fs::write(task_dir.join("stat"), &stat).unwrap();
        fs::write(task_dir.join("children"), "").unwrap();
        let identity = LaunchProcessIdentity {
            pid,
            owner_uid: uid,
            start_ticks: 991,
        };
        let barriers = Arc::new((Barrier::new(2), Barrier::new(2)));
        let controller = SystemdScopeController::new(&proc_root, &cgroup_root, uid);
        let acquirer: Arc<dyn ScopeAcquirer> = Arc::new(BlockingAcquirer {
            barriers: Arc::clone(&barriers),
            identity: identity.clone(),
        });
        let watchdog = test_watchdog(controller, proc_root, acquirer);
        lock(&watchdog.inner.state).leases.insert(
            pid,
            PauseLease {
                scope: None,
                recovery_scopes: Vec::new(),
                started: std::time::Instant::now(),
                deadline: std::time::Instant::now() + LEASE_TTL,
                lease_id: "old-lease".to_owned(),
                identity: Some(identity),
                generation: 1,
                guarded_generation: 0,
                guarded_active: false,
                cancellation: None,
                release_requested: false,
                release_in_progress: false,
            },
        );

        let pause_watchdog = watchdog.clone();
        let pause_thread = thread::spawn(move || pause_watchdog.pause(pid));
        barriers.0.wait();
        let (attempt_sender, attempt_receiver) = mpsc::channel();
        let (started_sender, started_receiver) = mpsc::channel();
        let (finish_sender, finish_receiver) = mpsc::channel();
        let (result_sender, result_receiver) = mpsc::channel();
        let guarded_watchdog = watchdog.clone();
        let guarded_thread = thread::spawn(move || {
            attempt_sender.send(()).unwrap();
            let result = guarded_watchdog.run_guarded(pid, "old-lease", move |_, _| {
                started_sender.send(()).unwrap();
                finish_receiver.recv().unwrap();
            });
            result_sender.send(result.is_some()).unwrap();
        });
        attempt_receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap();
        let started_before_replacement = started_receiver
            .recv_timeout(Duration::from_millis(200))
            .is_ok();

        barriers.1.wait();
        let pause_result = pause_thread.join().unwrap();
        let _ = finish_sender.send(());
        let guarded_succeeded = result_receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap();
        guarded_thread.join().unwrap();
        if pause_result["status"] == "paused" {
            assert_eq!(watchdog.resume(pid, None)["status"], "resumed");
        }
        assert!(watchdog.stop_until(std::time::Instant::now() + Duration::from_secs(1)));
        child.kill().unwrap();
        child.wait().unwrap();

        assert!(
            !started_before_replacement,
            "guarded operation pinned the old lease during a replacement transition"
        );
        assert!(
            !guarded_succeeded,
            "old guarded lease completion applied to a replacement lease"
        );
    }
    #[test]
    fn guarded_callback_unwind_cancels_and_wakes_release_waiters() {
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
        let operation_child = Command::new("/bin/sleep")
            .arg("30")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .process_group(0)
            .spawn()
            .unwrap();
        let operation_pid = i32::try_from(operation_child.id()).unwrap();
        let (operation_exited_sender, operation_exited_receiver) = mpsc::channel();
        let operation_reaper = thread::spawn(move || {
            let mut operation_child = operation_child;
            loop {
                if operation_child.try_wait().unwrap().is_some() {
                    operation_exited_sender.send(()).unwrap();
                    break;
                }
                thread::sleep(Duration::from_millis(2));
            }
        });
        let proc_dir = proc_root.join(pid.to_string());
        let task_dir = proc_dir.join("task").join(pid.to_string());
        fs::create_dir_all(&task_dir).unwrap();
        let fields = std::iter::repeat_n("1", 18).collect::<Vec<_>>().join(" ");
        let stat = format!("{pid} (fixture process) T {fields} 991");
        fs::write(proc_dir.join("stat"), &stat).unwrap();
        fs::write(task_dir.join("stat"), &stat).unwrap();
        let controller = SystemdScopeController::new(&proc_root, &cgroup_root, uid);
        let acquirer: Arc<dyn ScopeAcquirer> = Arc::new(LaunchScopeAcquirer::new(
            controller.clone(),
            &proc_root,
            uid,
        ));
        let watchdog = test_watchdog(controller, proc_root, acquirer);
        lock(&watchdog.inner.state).leases.insert(
            pid,
            PauseLease {
                scope: None,
                recovery_scopes: Vec::new(),
                started: std::time::Instant::now(),
                deadline: std::time::Instant::now() + LEASE_TTL,
                lease_id: "panic-lease".to_owned(),
                identity: Some(LaunchProcessIdentity {
                    pid,
                    owner_uid: uid,
                    start_ticks: 991,
                }),
                generation: 1,
                guarded_generation: 0,
                guarded_active: false,
                cancellation: None,
                release_requested: false,
                release_in_progress: false,
            },
        );

        let (cancel_sender, cancel_receiver) = mpsc::channel();
        let (continue_sender, continue_receiver) = mpsc::channel();
        let (panic_sender, panic_receiver) = mpsc::channel();
        let worker_watchdog = watchdog.clone();
        let worker = thread::spawn(move || {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                worker_watchdog.run_guarded(pid, "panic-lease", move |cancel, completion| -> () {
                    *completion = ProcessGroupCompletion::pending(operation_pid);
                    cancel_sender.send(cancel).unwrap();
                    continue_receiver.recv().unwrap();
                    panic!("fixture guarded operation panic")
                })
            }));
            panic_sender.send(result.is_err()).unwrap();
        });
        let cancellation = cancel_receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap();

        let (waiting_sender, waiting_receiver) = mpsc::channel();
        let (woke_sender, woke_receiver) = mpsc::channel();
        let waiting_watchdog = watchdog.clone();
        let waiter = thread::spawn(move || {
            let mut state = lock(&waiting_watchdog.inner.state);
            waiting_sender.send(()).unwrap();
            while state
                .leases
                .get(&pid)
                .is_some_and(|lease| lease.guarded_active)
            {
                state = waiting_watchdog
                    .inner
                    .changed
                    .wait(state)
                    .unwrap_or_else(|error| error.into_inner());
            }
            woke_sender.send(()).unwrap();
        });
        waiting_receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap();
        let guarded_before_unwind = lock(&watchdog.inner.state).leases[&pid].guarded_active;
        continue_sender.send(()).unwrap();

        let panicked = panic_receiver.recv_timeout(Duration::from_secs(1)).unwrap();
        let operation_exited = operation_exited_receiver
            .recv_timeout(Duration::from_secs(1))
            .is_ok();
        let waiter_woke = woke_receiver
            .recv_timeout(Duration::from_millis(100))
            .is_ok();
        if !waiter_woke {
            if let Some(lease) = lock(&watchdog.inner.state).leases.get_mut(&pid) {
                lease.guarded_active = false;
                lease.cancellation = None;
            }
            watchdog.inner.changed.notify_all();
        }
        worker.join().unwrap();
        operation_reaper.join().unwrap();
        waiter.join().unwrap();
        let cancellation_requested = cancellation.load(std::sync::atomic::Ordering::Acquire);
        let resume = watchdog.resume(pid, None);
        child.kill().unwrap();
        child.wait().unwrap();

        assert!(panicked, "callback panic was swallowed");
        assert!(
            guarded_before_unwind,
            "test did not reach the guarded-operation state"
        );
        assert!(
            operation_exited,
            "unwinding returned before the exact operation process exited"
        );
        assert!(
            cancellation_requested,
            "unwinding did not request cancellation"
        );
        assert!(
            waiter_woke,
            "unwind finalization did not wake release waiters"
        );
        assert_eq!(resume["status"], "resumed");
    }
}
