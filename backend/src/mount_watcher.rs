use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    os::fd::AsRawFd,
    sync::{Arc, atomic::{AtomicBool, Ordering}},
    thread::{self, JoinHandle},
    time::Duration,
};

use decky_plugin::Context;

/// Uses procfs POLLPRI notifications; the kernel sleeps while the mount table is unchanged.
pub struct MountWatcher {
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl MountWatcher {
    pub fn start(context: Context) -> std::io::Result<Self> {
        let mut mounts = File::open("/proc/self/mounts")?;
        let mut previous = read_mount_snapshot(&mut mounts)?;
        let stop = Arc::new(AtomicBool::new(false));
        let thread_stop = Arc::clone(&stop);
        let runtime = tokio::runtime::Handle::try_current().map_err(std::io::Error::other)?;
        let thread = thread::Builder::new()
            .name("sdh-ludusavi-mount-watch".to_owned())
            .spawn(move || {
                let mut descriptor = libc::pollfd { fd: mounts.as_raw_fd(), events: libc::POLLPRI, revents: 0 };
                while !thread_stop.load(Ordering::Acquire) {
                    descriptor.revents = 0;
                    // Timeout bounds unload latency; no periodic scan occurs while idle.
                    let ready = unsafe { libc::poll(&mut descriptor, 1, 1000) };
                    if ready <= 0 || descriptor.revents & libc::POLLPRI == 0 { continue; }
                    let Ok(snapshot) = read_mount_snapshot(&mut mounts) else { continue; };
                    if snapshot == previous { continue; }
                    thread::sleep(Duration::from_millis(700));
                    let Ok(settled) = read_mount_snapshot(&mut mounts) else { continue; };
                    let changed = settled != previous;
                    previous = settled;
                    if changed && !thread_stop.load(Ordering::Acquire) {
                        if let Err(error) = runtime.block_on(context.emit("sdh_ludusavi_mount_changed", Vec::new())) {
                            log::debug!("Could not notify frontend about mount change: {error}");
                        }
                    }
                }
            })?;
        Ok(Self { stop, thread: Some(thread) })
    }

    pub fn stop(mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(thread) = self.thread.take() { let _ = thread.join(); }
    }
}

fn read_mount_snapshot(file: &mut File) -> std::io::Result<String> {
    file.seek(SeekFrom::Start(0))?;
    let mut snapshot = String::new();
    file.read_to_string(&mut snapshot)?;
    Ok(snapshot)
}
