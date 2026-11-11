use std::{
    collections::HashSet,
    fs::File,
    io::{Read, Seek, SeekFrom},
    os::fd::{AsRawFd, FromRawFd, OwnedFd},
    sync::{Arc, atomic::{AtomicBool, Ordering}},
    thread::{self, JoinHandle},
    time::Duration,
};

use decky_plugin::Context;

/// Uses procfs POLLPRI notifications; the kernel sleeps while the mount table is unchanged.
pub struct MountWatcher {
    stop: Arc<AtomicBool>,
    stop_signal: OwnedFd,
    thread: Option<JoinHandle<()>>,
}

impl MountWatcher {
    pub fn start(context: Context, runtime: tokio::runtime::Handle) -> std::io::Result<Self> {
        let mut mounts = File::open("/proc/self/mounts")?;
        let mut previous = read_mount_snapshot(&mut mounts)?;
        let stop = Arc::new(AtomicBool::new(false));
        let thread_stop = Arc::clone(&stop);
        let stop_fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC | libc::EFD_NONBLOCK) };
        if stop_fd < 0 { return Err(std::io::Error::last_os_error()); }
        let stop_signal = unsafe { OwnedFd::from_raw_fd(stop_fd) };
        let thread_signal = stop_signal.try_clone()?;
        let thread = thread::Builder::new()
            .name("sdh-ludusavi-mount-watch".to_owned())
            .spawn(move || {
                let mut descriptors = [
                    libc::pollfd { fd: mounts.as_raw_fd(), events: libc::POLLPRI, revents: 0 },
                    libc::pollfd { fd: thread_signal.as_raw_fd(), events: libc::POLLIN, revents: 0 },
                ];
                while !thread_stop.load(Ordering::Acquire) {
                    descriptors[0].revents = 0;
                    descriptors[1].revents = 0;
                    // Block indefinitely: eventfd wakes this thread immediately on unload.
                    let ready = unsafe { libc::poll(descriptors.as_mut_ptr(), 2, -1) };
                    if ready < 0 { continue; }
                    if descriptors[1].revents & libc::POLLIN != 0 { break; }
                    if descriptors[0].revents & libc::POLLPRI == 0 { continue; }
                    let Ok(snapshot) = read_mount_snapshot(&mut mounts) else { continue; };
                    if snapshot == previous { continue; }
                    thread::sleep(Duration::from_millis(700));
                    let Ok(settled) = read_mount_snapshot(&mut mounts) else { continue; };
                    let changed = has_sd_mount_change(&previous, &settled);
                    previous = settled;
                    if changed && !thread_stop.load(Ordering::Acquire) {
                        if let Err(error) = runtime.block_on(context.emit("sdh_ludusavi_mount_changed", Vec::new())) {
                            log::debug!("Could not notify frontend about mount change: {error}");
                        }
                    }
                }
            })?;
        Ok(Self { stop, stop_signal, thread: Some(thread) })
    }

    pub fn stop(mut self) {
        self.stop.store(true, Ordering::Release);
        let wake = 1_u64;
        unsafe {
            libc::write(
                self.stop_signal.as_raw_fd(),
                (&wake as *const u64).cast(),
                std::mem::size_of::<u64>(),
            );
        }
        if let Some(thread) = self.thread.take() { let _ = thread.join(); }
    }
}

fn read_mount_snapshot(file: &mut File) -> std::io::Result<String> {
    file.seek(SeekFrom::Start(0))?;
    let mut snapshot = String::new();
    file.read_to_string(&mut snapshot)?;
    Ok(snapshot)
}

fn has_sd_mount_change(previous: &str, current: &str) -> bool {
    let old: HashSet<&str> = previous.lines().collect();
    let new: HashSet<&str> = current.lines().collect();
    old.symmetric_difference(&new).any(|line| {
        let Some(mount_point) = line.split_whitespace().nth(1) else {
            return false;
        };
        mount_point.starts_with("/run/media/deck/") || mount_point.starts_with("/media/")
    })
}
