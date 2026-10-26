use std::{
    fs::{self, File, OpenOptions},
    io,
    os::{
        fd::AsRawFd,
        unix::fs::{OpenOptionsExt, PermissionsExt},
    },
    path::{Path, PathBuf},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use serde::Serialize;
use serde_json::{Map, Value};

const LOCK_TIMEOUT: Duration = Duration::from_secs(5);
const LOCK_RETRY: Duration = Duration::from_millis(50);

pub struct StateLock {
    path: PathBuf,
    file: File,
    thread_lock: Mutex<()>,
}

impl StateLock {
    pub fn new(cache_path: &Path) -> io::Result<Self> {
        let parent = cache_path.parent().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidInput, "cache path has no parent")
        })?;
        ensure_private_directory(parent)?;
        let path = parent.join(".sdh_ludusavi.state.lock");
        let file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .open(&path)?;
        file.set_permissions(fs::Permissions::from_mode(0o600))?;
        Ok(Self {
            path,
            file,
            thread_lock: Mutex::new(()),
        })
    }

    pub fn with_lock<T>(&self, operation: impl FnOnce() -> io::Result<T>) -> io::Result<T> {
        let _thread_guard = self
            .thread_lock
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        let _file_guard = FileLockGuard::acquire(&self.file, &self.path)?;
        operation()
    }
}

struct FileLockGuard<'a> {
    file: &'a File,
}

impl<'a> FileLockGuard<'a> {
    fn acquire(file: &'a File, path: &Path) -> io::Result<Self> {
        let deadline = Instant::now() + LOCK_TIMEOUT;
        loop {
            // Python and Rust use this lock file to coordinate shared state across processes.
            let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
            if result == 0 {
                return Ok(Self { file });
            }
            let error = io::Error::last_os_error();
            if !matches!(
                error.kind(),
                io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
            ) {
                return Err(io::Error::new(
                    error.kind(),
                    format!("state lock unavailable at {}: {error}", path.display()),
                ));
            }
            if Instant::now() >= deadline {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    format!("timed out acquiring state lock at {}", path.display()),
                ));
            }
            thread::sleep(LOCK_RETRY);
        }
    }
}

impl Drop for FileLockGuard<'_> {
    fn drop(&mut self) {
        // Best effort: releasing an advisory lock cannot fail in normal operation.
        unsafe {
            libc::flock(self.file.as_raw_fd(), libc::LOCK_UN);
        }
    }
}

pub fn ensure_private_directory(path: &Path) -> io::Result<()> {
    fs::create_dir_all(path)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))
}

pub fn read_object(path: &Path) -> io::Result<Option<Map<String, Value>>> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    let value = serde_json::from_reader::<_, Value>(file)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    match value {
        Value::Object(object) => Ok(Some(object)),
        _ => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("JSON in {} is not an object", path.display()),
        )),
    }
}

pub fn existing_mode(path: &Path, default: u32) -> io::Result<u32> {
    match fs::metadata(path) {
        Ok(metadata) => Ok(metadata.permissions().mode() & 0o777),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(default),
        Err(error) => Err(error),
    }
}

pub fn write_json_atomic<T: Serialize + ?Sized>(
    path: &Path,
    value: &T,
    mode: u32,
    indent: &[u8],
) -> io::Result<()> {
    write_json_before_rename(path, value, mode, indent, || Ok(()))
}

fn write_json_before_rename<T: Serialize + ?Sized>(
    path: &Path,
    value: &T,
    mode: u32,
    indent: &[u8],
    before_rename: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "JSON path has no parent"))?;
    ensure_private_directory(parent)?;
    let mut temporary = tempfile::Builder::new()
        .prefix(".sdh-ludusavi-")
        .tempfile_in(parent)?;
    {
        let formatter = serde_json::ser::PrettyFormatter::with_indent(indent);
        let mut serializer =
            serde_json::Serializer::with_formatter(temporary.as_file_mut(), formatter);
        value.serialize(&mut serializer).map_err(io::Error::other)?;
    }
    temporary
        .as_file()
        .set_permissions(fs::Permissions::from_mode(mode))?;
    temporary.as_file().sync_all()?;
    before_rename()?;
    temporary.persist(path).map_err(|error| error.error)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{fs, os::unix::fs::PermissionsExt};

    use serde_json::json;
    use tempfile::tempdir_in;

    use super::write_json_before_rename;

    #[test]
    fn atomic_write_keeps_previous_file_when_rename_fails() {
        let directory = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let path = directory.path().join("settings.json");
        fs::write(&path, br#"{"old":true}"#).unwrap();

        let result = write_json_before_rename(&path, &json!({"new": true}), 0o600, b"    ", || {
            fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o500))?;
            Ok(())
        });
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();

        assert!(
            result.is_err(),
            "rename into the read-only directory must fail"
        );
        assert_eq!(fs::read(&path).unwrap(), br#"{"old":true}"#);
    }
}
