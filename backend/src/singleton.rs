use std::{
    fs, io,
    path::Path,
    thread,
    time::{Duration, Instant},
};

use std::os::unix::fs::MetadataExt;

const MAX_STALE_SIBLINGS: usize = 8;
const TERM_TIMEOUT: Duration = Duration::from_secs(3);
const KILL_TIMEOUT: Duration = Duration::from_secs(1);
const POLL_INTERVAL: Duration = Duration::from_millis(100);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcessIdentity {
    pub pid: i32,
    uid: u32,
    start_ticks: u64,
    cmdline: Vec<u8>,
}

#[derive(Debug, Default, Eq, PartialEq)]
pub struct SingletonReport {
    pub status: &'static str,
    pub stale_pids: Vec<i32>,
    pub terminated: Vec<i32>,
    pub killed: Vec<i32>,
    pub skipped: Vec<i32>,
    pub failed: Vec<i32>,
    pub refused: Vec<i32>,
}

pub fn enforce_single_instance() -> io::Result<SingletonReport> {
    enforce_single_instance_at(
        Path::new("/proc"),
        std::process::id() as i32,
        |pid, signal| {
            if unsafe { libc::kill(pid, signal) } == 0 {
                Ok(())
            } else {
                Err(io::Error::last_os_error())
            }
        },
    )
}

pub fn enforce_single_instance_at(
    proc_root: &Path,
    own_pid: i32,
    mut signal_process: impl FnMut(i32, i32) -> io::Result<()>,
) -> io::Result<SingletonReport> {
    let Some(own) = capture_identity(proc_root, own_pid) else {
        return Ok(SingletonReport::default());
    };
    let mut siblings = Vec::new();
    for entry in fs::read_dir(proc_root)? {
        let entry = match entry {
            Ok(entry) => entry,
            Err(_) => continue,
        };
        let Some(pid) = entry
            .file_name()
            .to_str()
            .and_then(|value| value.parse::<i32>().ok())
        else {
            continue;
        };
        if pid <= 1 || pid == own_pid {
            continue;
        }
        let Some(candidate) = capture_identity(proc_root, pid) else {
            continue;
        };
        if candidate.uid == own.uid
            && same_commandline(&candidate.cmdline, &own.cmdline)
            && (candidate.start_ticks, candidate.pid) < (own.start_ticks, own.pid)
        {
            siblings.push(candidate);
        }
    }
    siblings.sort_by_key(|identity| identity.pid);
    let stale_pids = siblings.iter().map(|identity| identity.pid).collect();
    let mut report = SingletonReport {
        status: "ok",
        stale_pids,
        ..SingletonReport::default()
    };
    if siblings.is_empty() {
        return Ok(report);
    }
    if siblings.len() > MAX_STALE_SIBLINGS {
        report.status = "failed";
        report.refused = siblings.into_iter().map(|identity| identity.pid).collect();
        return Ok(report);
    }

    let mut signalled = Vec::new();
    for sibling in siblings {
        match process_status(proc_root, &sibling) {
            IdentityStatus::Gone => push_unique(&mut report.terminated, sibling.pid),
            IdentityStatus::Changed => push_unique(&mut report.skipped, sibling.pid),
            IdentityStatus::Running => match signal_process(sibling.pid, libc::SIGTERM) {
                Ok(()) => signalled.push(sibling),
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    push_unique(&mut report.terminated, sibling.pid)
                }
                Err(_) => push_unique(&mut report.failed, sibling.pid),
            },
        }
    }

    let survivors = wait_until_stopped_or_changed(
        proc_root,
        signalled,
        TERM_TIMEOUT,
        &mut report.terminated,
        &mut report.skipped,
    );
    let mut killed = Vec::new();
    for sibling in survivors {
        match process_status(proc_root, &sibling) {
            IdentityStatus::Gone => push_unique(&mut report.terminated, sibling.pid),
            IdentityStatus::Changed => push_unique(&mut report.skipped, sibling.pid),
            IdentityStatus::Running => match signal_process(sibling.pid, libc::SIGKILL) {
                Ok(()) => killed.push(sibling),
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    push_unique(&mut report.terminated, sibling.pid)
                }
                Err(_) => push_unique(&mut report.failed, sibling.pid),
            },
        }
    }
    let still_running = wait_until_stopped_or_changed(
        proc_root,
        killed,
        KILL_TIMEOUT,
        &mut report.killed,
        &mut report.skipped,
    );
    for sibling in still_running {
        push_unique(&mut report.failed, sibling.pid);
    }
    Ok(report)
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum IdentityStatus {
    Gone,
    Changed,
    Running,
}

fn capture_identity(proc_root: &Path, pid: i32) -> Option<ProcessIdentity> {
    if pid <= 1 {
        return None;
    }
    let dir = proc_root.join(pid.to_string());
    let uid = fs::metadata(&dir).ok()?.uid();
    let stat = fs::read_to_string(dir.join("stat")).ok()?;
    let start_ticks = parse_start_ticks(&stat, pid)?;
    let cmdline = fs::read(dir.join("cmdline")).ok()?;
    if cmdline.is_empty() || process_state(&stat) == Some('Z') {
        return None;
    }
    Some(ProcessIdentity {
        pid,
        uid,
        start_ticks,
        cmdline,
    })
}

fn parse_start_ticks(stat: &str, pid: i32) -> Option<u64> {
    let open = stat.find('(')?;
    let close = stat.rfind(')')?;
    if close <= open || stat[..open].trim().parse::<i32>().ok()? != pid {
        return None;
    }
    stat[close + 1..].split_whitespace().nth(19)?.parse().ok()
}

fn process_state(stat: &str) -> Option<char> {
    let close = stat.rfind(')')?;
    stat[close + 1..].split_whitespace().next()?.chars().next()
}

fn process_status(proc_root: &Path, expected: &ProcessIdentity) -> IdentityStatus {
    let dir = proc_root.join(expected.pid.to_string());
    let Ok(stat) = fs::read_to_string(dir.join("stat")) else {
        return IdentityStatus::Gone;
    };
    if process_state(&stat) == Some('Z') {
        return IdentityStatus::Gone;
    }
    match capture_identity(proc_root, expected.pid) {
        Some(current) if current == *expected => IdentityStatus::Running,
        Some(_) => IdentityStatus::Changed,
        None if dir.exists() => IdentityStatus::Changed,
        None => IdentityStatus::Gone,
    }
}

fn wait_until_stopped_or_changed(
    proc_root: &Path,
    mut remaining: Vec<ProcessIdentity>,
    timeout: Duration,
    gone: &mut Vec<i32>,
    changed: &mut Vec<i32>,
) -> Vec<ProcessIdentity> {
    let deadline = Instant::now() + timeout;
    while !remaining.is_empty() && Instant::now() < deadline {
        thread::sleep(POLL_INTERVAL.min(deadline.saturating_duration_since(Instant::now())));
        remaining.retain(|identity| match process_status(proc_root, identity) {
            IdentityStatus::Gone => {
                push_unique(gone, identity.pid);
                false
            }
            IdentityStatus::Changed => {
                push_unique(changed, identity.pid);
                false
            }
            IdentityStatus::Running => true,
        });
    }
    remaining
}

fn push_unique(values: &mut Vec<i32>, pid: i32) {
    if !values.contains(&pid) {
        values.push(pid);
    }
}

pub(crate) fn same_commandline(left: &[u8], right: &[u8]) -> bool {
    left == right
}

#[cfg(test)]
mod tests {
    use std::{fs, io, path::Path};

    use tempfile::tempdir_in;

    use super::{IdentityStatus, capture_identity, enforce_single_instance_at, process_status};

    #[test]
    fn singleton_requires_byte_identical_full_commandline() {
        let current = b"/runtime/backend\0--plugin\0SDH-Ludusavi\0";
        assert!(super::same_commandline(current, current));
        assert!(!super::same_commandline(
            current,
            b"/runtime/backend\0--plugin\0"
        ));
        assert!(!super::same_commandline(
            current,
            b"/runtime/backend-other\0--plugin\0SDH-Ludusavi\0"
        ));
    }

    fn write_process(root: &Path, pid: i32, start_ticks: u64, cmdline: &[u8]) {
        let directory = root.join(pid.to_string());
        fs::create_dir_all(&directory).unwrap();
        let fields = std::iter::repeat_n("1", 18).collect::<Vec<_>>().join(" ");
        fs::write(
            directory.join("stat"),
            format!("{pid} (contract process) S {fields} {start_ticks}"),
        )
        .unwrap();
        fs::write(directory.join("cmdline"), cmdline).unwrap();
    }

    #[test]
    fn singleton_escalates_only_if_process_identity_stays_the_same() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let root = temporary.path();
        let command = b"/runtime/backend\0--plugin\0SDH-Ludusavi\0";
        write_process(root, 100, 20, command);
        write_process(root, 101, 10, command);
        let mut signals = Vec::new();
        let report = enforce_single_instance_at(root, 100, |pid, signal| {
            signals.push((pid, signal));
            if signal == libc::SIGKILL {
                fs::remove_dir_all(root.join(pid.to_string()))?;
            }
            Ok::<(), io::Error>(())
        })
        .unwrap();
        assert_eq!(signals, [(101, libc::SIGTERM), (101, libc::SIGKILL)]);
        assert_eq!(report.killed, [101]);

        write_process(root, 101, 10, command);
        let mut signals = Vec::new();
        let report = enforce_single_instance_at(root, 100, |pid, signal| {
            signals.push((pid, signal));
            write_process(root, pid, 99, command);
            Ok::<(), io::Error>(())
        })
        .unwrap();
        assert_eq!(signals, [(101, libc::SIGTERM)]);
        assert_eq!(report.skipped, [101]);
    }

    #[test]
    fn singleton_signals_only_strictly_older_byte_identical_processes() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let root = temporary.path();
        let command = b"/runtime/backend\0--plugin\0SDH-Ludusavi\0";
        write_process(root, 100, 20, command);
        write_process(root, 101, 10, command);
        write_process(root, 102, 5, b"/runtime/backend\0--plugin\0");
        write_process(root, 103, 30, command);

        let mut signals = Vec::new();
        let report = enforce_single_instance_at(root, 100, |pid, signal| {
            signals.push((pid, signal));
            fs::remove_dir_all(root.join(pid.to_string()))?;
            Ok::<(), io::Error>(())
        })
        .unwrap();

        assert_eq!(report.stale_pids, [101]);
        assert_eq!(report.terminated, [101]);
        assert_eq!(signals, [(101, libc::SIGTERM)]);
    }

    #[test]
    fn singleton_detects_process_reuse_by_changed_start_ticks() {
        let temporary = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let root = temporary.path();
        let command = b"/runtime/backend\0--plugin\0SDH-Ludusavi\0";
        write_process(root, 100, 20, command);
        let original = capture_identity(root, 100).unwrap();
        write_process(root, 100, 21, command);
        assert!(matches!(
            process_status(root, &original),
            IdentityStatus::Changed
        ));
    }
}
