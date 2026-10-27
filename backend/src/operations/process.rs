use super::*;
pub(crate) struct ProcessGroupCompletion {
    pid: Option<i32>,
    confirmed: bool,
    groups: Option<Arc<Mutex<BTreeSet<i32>>>>,
    child: Option<Child>,
    readers: ProcessReaders,
}

impl ProcessGroupCompletion {
    pub(crate) fn confirmed() -> Self {
        Self {
            pid: None,
            confirmed: true,
            groups: None,
            child: None,
            readers: (None, None),
        }
    }

    #[cfg(test)]
    pub(crate) fn pending(pid: i32) -> Self {
        Self {
            pid: Some(pid),
            confirmed: false,
            groups: None,
            child: None,
            readers: (None, None),
        }
    }

    fn track(&mut self, pid: i32, groups: Arc<Mutex<BTreeSet<i32>>>, child: Child) {
        self.pid = Some(pid);
        self.confirmed = false;
        self.groups = Some(groups);
        self.child = Some(child);
    }

    fn child_mut(&mut self) -> &mut Child {
        self.child
            .as_mut()
            .expect("tracked process group has child")
    }

    fn set_stdout_reader(&mut self, reader: ProcessOutputReader) {
        self.readers.0 = Some(reader);
    }

    fn set_stderr_reader(&mut self, reader: ProcessOutputReader) {
        self.readers.1 = Some(reader);
    }

    fn take_stdout_reader(&mut self) -> Option<ProcessOutputReader> {
        self.readers.0.take()
    }

    fn take_stderr_reader(&mut self) -> Option<ProcessOutputReader> {
        self.readers.1.take()
    }

    fn confirm_exit(&mut self) {
        if let (Some(pid), Some(groups)) = (self.pid, &self.groups) {
            lock(groups).remove(&pid);
        }
        self.confirmed = true;
    }

    pub(crate) fn wait(&mut self, cancellation: Option<&AtomicBool>) {
        if !self.confirmed
            && let Some(pid) = self.pid
        {
            while group_exists(pid) {
                if cancellation.is_some_and(|token| token.load(Ordering::Acquire)) {
                    let _ = signal_group(pid, libc::SIGKILL);
                }
                if let Some(child) = self.child.as_mut() {
                    let _ = child.try_wait();
                }
                thread::sleep(Duration::from_millis(10));
            }
        }
        self.reap_child();
        if !self.confirmed {
            self.confirm_exit();
        }
        if let Some(reader) = self.readers.0.take() {
            let _ = reader.join();
        }
        if let Some(reader) = self.readers.1.take() {
            let _ = reader.join();
        }
    }

    fn reap_child(&mut self) {
        if let Some(child) = self.child.as_mut() {
            if child.try_wait().ok().flatten().is_none() {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
    }
}

impl Drop for ProcessGroupCompletion {
    fn drop(&mut self) {
        let cancellation = AtomicBool::new(true);
        self.wait(Some(&cancellation));
    }
}

#[derive(Default)]
pub(super) struct ProcessManager {
    pub(super) stopping: AtomicBool,
    groups: Arc<Mutex<BTreeSet<i32>>>,
    #[cfg(test)]
    fail_reader_at: std::sync::atomic::AtomicUsize,
    #[cfg(test)]
    reader_attempt: std::sync::atomic::AtomicUsize,
    #[cfg(test)]
    pub(super) after_track_hook: Mutex<Option<AfterTrackHook>>,
}

impl ProcessManager {
    fn spawn_output_reader(
        &self,
        pipe: impl Read + Send + 'static,
    ) -> io::Result<ProcessOutputReader> {
        #[cfg(test)]
        {
            let attempt = self.reader_attempt.fetch_add(1, Ordering::AcqRel) + 1;
            if self.fail_reader_at.load(Ordering::Acquire) == attempt {
                return Err(io::Error::other("fixture output reader creation failure"));
            }
        }
        thread::Builder::new().spawn(move || read_pipe(pipe))
    }
    pub(super) fn run_at(
        &self,
        program: &Path,
        args: &[std::ffi::OsString],
        timeout: Duration,
        text: bool,
    ) -> Result<String, String> {
        let mut completion = ProcessGroupCompletion::confirmed();
        let result = self.run_at_cancellable(program, args, timeout, text, None, &mut completion);
        completion.wait(Some(&self.stopping));
        result
    }

    pub(super) fn run_at_cancellable(
        &self,
        program: &Path,
        args: &[std::ffi::OsString],
        timeout: Duration,
        text: bool,
        cancellation: Option<&AtomicBool>,
        completion: &mut ProcessGroupCompletion,
    ) -> Result<String, String> {
        if self.stopping.load(Ordering::Acquire)
            || cancellation.is_some_and(|token| token.load(Ordering::Acquire))
        {
            return Err("Ludusavi operation cancelled".to_owned());
        }
        let mut command = Command::new(program);
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        command.env("LD_LIBRARY_PATH", "");
        if env::var_os("XDG_RUNTIME_DIR").is_none() {
            let uid = unsafe { libc::getuid() };
            let candidate = format!("/run/user/{uid}");
            command.env(
                "XDG_RUNTIME_DIR",
                if Path::new(&candidate).is_dir() {
                    candidate
                } else {
                    "/run/user/1000".to_owned()
                },
            );
        }
        command.process_group(0);
        let mut child = command
            .spawn()
            .map_err(|error| format!("Could not start Ludusavi command: {error}"))?;
        let pid = match i32::try_from(child.id()) {
            Ok(pid) => pid,
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Ludusavi process ID is out of range".to_owned());
            }
        };
        completion.track(pid, Arc::clone(&self.groups), child);
        lock(&self.groups).insert(pid);
        #[cfg(test)]
        if let Some(hook) = lock(&self.after_track_hook).take() {
            hook(pid);
        }
        if self.stopping.load(Ordering::Acquire)
            || cancellation.is_some_and(|token| token.load(Ordering::Acquire))
        {
            let _ = signal_group(pid, libc::SIGTERM);
        }
        let stdout = completion.child_mut().stdout.take().expect("piped stdout");
        let stderr = completion.child_mut().stderr.take().expect("piped stderr");
        let stdout_reader = match self.spawn_output_reader(stdout) {
            Ok(reader) => reader,
            Err(error) => {
                if terminate_group(pid, completion.child_mut()) {
                    completion.confirm_exit();
                    completion.wait(None);
                }
                return Err(format!("Could not start Ludusavi stdout reader: {error}"));
            }
        };
        completion.set_stdout_reader(stdout_reader);
        let stderr_reader = match self.spawn_output_reader(stderr) {
            Ok(reader) => reader,
            Err(error) => {
                if terminate_group(pid, completion.child_mut()) {
                    completion.confirm_exit();
                    completion.wait(None);
                }
                return Err(format!("Could not start Ludusavi stderr reader: {error}"));
            }
        };
        completion.set_stderr_reader(stderr_reader);
        let started = Instant::now();
        let mut status = None;
        let mut outcome = None;
        loop {
            if self.stopping.load(Ordering::Acquire)
                || cancellation.is_some_and(|token| token.load(Ordering::Acquire))
            {
                outcome = Some("cancelled".to_owned());
                break;
            }
            match completion.child_mut().try_wait() {
                Ok(Some(child_status)) => {
                    status = Some(child_status);
                    if !group_exists(pid) {
                        break;
                    }
                }
                Ok(None) => {}
                Err(error) => {
                    outcome = Some(format!("Could not wait for Ludusavi: {error}"));
                    break;
                }
            }
            if started.elapsed() >= timeout {
                outcome = Some(format!("timeout:{timeout:?}"));
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        let group_exited = if outcome.is_some() || group_exists(pid) {
            terminate_group(pid, completion.child_mut())
        } else {
            true
        };
        if !group_exited {
            return Err("Could not confirm Ludusavi process group exit".to_owned());
        }
        if status.is_none() {
            status = completion.child_mut().wait().ok();
        }
        completion.confirm_exit();
        let stdout = match completion
            .take_stdout_reader()
            .ok_or_else(|| "Ludusavi stdout reader was not started".to_owned())?
            .join()
            .unwrap_or_else(|_| Err(io::Error::other("stdout reader panicked")))
        {
            Ok(stdout) => stdout,
            Err(error) => return Err(format!("Could not read Ludusavi stdout: {error}")),
        };
        let stderr = match completion
            .take_stderr_reader()
            .ok_or_else(|| "Ludusavi stderr reader was not started".to_owned())?
            .join()
            .unwrap_or_else(|_| Err(io::Error::other("stderr reader panicked")))
        {
            Ok(stderr) => stderr,
            Err(error) => return Err(format!("Could not read Ludusavi stderr: {error}")),
        };
        if let Some(outcome) = outcome {
            if outcome == "cancelled" {
                Err("Ludusavi operation cancelled".to_owned())
            } else if let Some(timeout) = outcome.strip_prefix("timeout:") {
                Err(format!(
                    "Ludusavi command exceeded its configured timeout after {timeout}: {}",
                    args.join(std::ffi::OsStr::new(" ")).to_string_lossy()
                ))
            } else {
                Err(outcome)
            }
        } else if let Some(status) = status {
            if !status.success() {
                Err(format!(
                    "Ludusavi command failed with exit code {}: {}",
                    status.code().unwrap_or(-1),
                    String::from_utf8_lossy(&stderr).trim()
                ))
            } else if text {
                Ok(String::from_utf8_lossy(&stdout).into_owned())
            } else {
                String::from_utf8(stdout)
                    .map_err(|error| format!("Ludusavi output is not UTF-8: {error}"))
            }
        } else {
            Err("Could not reap Ludusavi child process".to_owned())
        }
    }

    pub(super) fn cancel_all(&self) {
        self.stopping.store(true, Ordering::Release);
        for pid in lock(&self.groups).iter().copied() {
            let _ = signal_group(pid, libc::SIGTERM);
        }
    }
    pub(super) fn groups_exited(&self) -> bool {
        let mut groups = lock(&self.groups);
        groups.retain(|pid| group_exists(*pid));
        groups.is_empty()
    }
}

fn read_pipe(mut pipe: impl Read) -> io::Result<Vec<u8>> {
    let mut output = Vec::new();
    pipe.read_to_end(&mut output)?;
    Ok(output)
}

fn terminate_group(pid: i32, child: &mut Child) -> bool {
    let _ = signal_group(pid, libc::SIGTERM);
    let grace_end = Instant::now() + TERMINATE_GRACE;
    while Instant::now() < grace_end && group_exists(pid) {
        let _ = child.try_wait();
        thread::sleep(Duration::from_millis(10));
    }
    if group_exists(pid) {
        let _ = signal_group(pid, libc::SIGKILL);
    }
    let deadline = Instant::now() + KILL_CONFIRM_TIMEOUT;
    while group_exists(pid) && Instant::now() < deadline {
        let _ = child.try_wait();
        thread::sleep(Duration::from_millis(10));
    }
    if child.try_wait().ok().flatten().is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
    !group_exists(pid)
}
fn signal_group(pid: i32, signal: i32) -> bool {
    if pid <= 1 {
        return false;
    }
    unsafe { libc::kill(-pid, signal) == 0 }
}

fn group_exists(pid: i32) -> bool {
    if pid <= 1 {
        return false;
    }
    if unsafe { libc::kill(-pid, 0) } == 0 {
        true
    } else {
        io::Error::last_os_error().raw_os_error() != Some(libc::ESRCH)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn timeout_kills_and_confirms_the_entire_process_group() {
        let directory = tempfile::tempdir().unwrap();
        let pid_file = directory.path().join("process-group");
        let args = [
            "-c".into(),
            "trap '' TERM; sleep 30 & echo $$ > \"$1\"; wait".into(),
            "sh".into(),
            pid_file.as_os_str().to_owned(),
        ];
        let processes = ProcessManager::default();
        let error = processes
            .run_at(Path::new("/bin/sh"), &args, Duration::from_millis(80), true)
            .unwrap_err();
        assert!(error.contains("timeout"), "{error}");
        let process_group = std::fs::read_to_string(pid_file)
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        assert!(!group_exists(process_group));
        assert!(processes.groups_exited());
    }
    #[test]
    fn output_reader_creation_failure_terminates_the_owned_process_group() {
        for failure_index in [1, 2] {
            let args = [
                "-c".into(),
                "trap '' TERM; sleep 30 & wait".into(),
                "sh".into(),
            ];
            let processes = ProcessManager::default();
            processes
                .fail_reader_at
                .store(failure_index, std::sync::atomic::Ordering::Release);
            let mut completion = super::ProcessGroupCompletion::confirmed();
            let error = processes
                .run_at_cancellable(
                    Path::new("/bin/sh"),
                    &args,
                    Duration::from_secs(2),
                    true,
                    None,
                    &mut completion,
                )
                .unwrap_err();
            completion.wait(None);
            let process_group = completion.pid.unwrap();
            assert!(completion.confirmed);
            assert!(!group_exists(process_group));
            assert!(processes.groups_exited());
            assert!(
                error.contains("reader"),
                "failure at reader {failure_index} returned {error}"
            );
        }
    }
    #[test]
    fn successful_leader_waits_for_writer_descendant_before_returning() {
        let directory = tempfile::tempdir().unwrap();
        let marker = directory.path().join("writer-finished");
        let args = [
            "-c".into(),
            "printf '{}\\n'; (sleep 0.1; printf child-finished > \"$1\") &".into(),
            "sh".into(),
            marker.as_os_str().to_owned(),
        ];
        let processes = ProcessManager::default();
        let output = processes
            .run_at(Path::new("/bin/sh"), &args, Duration::from_secs(1), true)
            .unwrap();
        assert_eq!(output, "{}\n");
        assert!(
            marker.exists(),
            "writer descendant was terminated before finishing"
        );
        assert_eq!(std::fs::read_to_string(marker).unwrap(), "child-finished");
        assert!(processes.groups_exited());
    }
}
