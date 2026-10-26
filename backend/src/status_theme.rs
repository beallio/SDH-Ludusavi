use std::{
    fs,
    io::{self, Write},
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};

use tempfile::Builder;

const THEME_NAME: &str = "SDH-Ludusavi Status";
const THEME_FILES: [&str; 4] = ["theme.json", "clean.css", "custom.css", "layout.css"];
const MARKER: &str = ".sdh-ludusavi-status-theme";
const MARKER_VALUE: &[u8] = b"sdh-ludusavi-status-theme-1\n";
const PREFERENCE_BACKUPS: [(&str, &str); 3] = [
    ("config_USER.json", "status-theme-choices.json"),
    ("config_ROOT.json", "status-theme-root-choices.json"),
    ("PRIORITY", "status-theme-priority"),
];

fn theme_directory(decky_home: &Path) -> PathBuf {
    decky_home.join("themes").join(THEME_NAME)
}

fn atomic_write(path: &Path, contents: &[u8], mode: u32) -> io::Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("destination has no parent directory"))?;
    let mut temporary = Builder::new()
        .prefix(&format!(
            ".{}.",
            path.file_name().unwrap_or_default().to_string_lossy()
        ))
        .tempfile_in(parent)?;
    temporary.write_all(contents)?;
    temporary.as_file().sync_all()?;
    fs::set_permissions(temporary.path(), fs::Permissions::from_mode(mode))?;
    temporary.persist(path).map_err(|error| error.error)?;
    Ok(())
}

fn ownership_error(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message.into())
}

fn is_symlink(path: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(metadata) => Ok(metadata.file_type().is_symlink()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

pub fn install_status_theme(
    source: &Path,
    decky_home: &Path,
    preferences_dir: &Path,
) -> Result<bool, String> {
    let result = install(source, decky_home, preferences_dir);
    result.map_err(|error| error.to_string())
}

fn install(source: &Path, decky_home: &Path, preferences_dir: &Path) -> io::Result<bool> {
    let manifest = source.join("theme.json");
    if is_symlink(&manifest)?
        || THEME_FILES
            .iter()
            .any(|name| is_symlink(&source.join(name)).unwrap_or(true))
    {
        return Err(ownership_error("Bundled theme files must not be symlinks"));
    }
    let manifest_data = fs::read(&manifest)?;
    let manifest_json: serde_json::Value = serde_json::from_slice(&manifest_data)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    if manifest_json
        .get("name")
        .and_then(serde_json::Value::as_str)
        != Some(THEME_NAME)
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Bundled CSS Loader theme has an unexpected name",
        ));
    }

    let destination = theme_directory(decky_home);
    if is_symlink(&destination)? {
        return Err(ownership_error(format!(
            "Theme directory is a symlink: {}",
            destination.display()
        )));
    }
    if destination.exists() {
        let marker = destination.join(MARKER);
        if is_symlink(&marker)? || !marker.is_file() || fs::read(&marker)? != MARKER_VALUE {
            return Err(ownership_error(format!(
                "Theme directory is not managed by SDH-Ludusavi: {}",
                destination.display()
            )));
        }
    } else {
        fs::create_dir_all(&destination)?;
        fs::set_permissions(&destination, fs::Permissions::from_mode(0o755))?;
        atomic_write(&destination.join(MARKER), MARKER_VALUE, 0o600)?;
    }

    let mut changed = false;
    for name in THEME_FILES {
        let file = destination.join(name);
        if is_symlink(&file)? {
            return Err(ownership_error(format!(
                "Managed theme file is a symlink: {}",
                file.display()
            )));
        }
        let contents = fs::read(source.join(name))?;
        let current = match fs::read(&file) {
            Ok(current) => Some(current),
            Err(error) if error.kind() == io::ErrorKind::NotFound => None,
            Err(error) => return Err(error),
        };
        if current.as_deref() != Some(contents.as_slice()) {
            atomic_write(&file, &contents, 0o644)?;
            changed = true;
        }
    }

    for (name, backup_name) in PREFERENCE_BACKUPS {
        let file = destination.join(name);
        let backup = preferences_dir.join(backup_name);
        if is_symlink(&file)? || is_symlink(&backup)? {
            return Err(ownership_error(format!(
                "Theme preferences contain a symlink: {}",
                file.display()
            )));
        }
        if !file.exists() && backup.is_file() {
            let mode = if name == "PRIORITY" { 0o644 } else { 0o600 };
            atomic_write(&file, &fs::read(&backup)?, mode)?;
            changed = true;
        }
    }

    let config = destination.join("config_USER.json");
    if !config.exists() {
        atomic_write(&config, b"{\"active\": true}\n", 0o600)?;
        changed = true;
    }
    Ok(changed)
}

pub fn uninstall_status_theme(decky_home: &Path, preferences_dir: &Path) -> Result<(), String> {
    uninstall(decky_home, preferences_dir).map_err(|error| error.to_string())
}

fn uninstall(decky_home: &Path, preferences_dir: &Path) -> io::Result<()> {
    let destination = theme_directory(decky_home);
    if is_symlink(&destination)? || !destination.is_dir() {
        return Ok(());
    }
    let marker = destination.join(MARKER);
    if is_symlink(&marker)? || !marker.is_file() || fs::read(&marker)? != MARKER_VALUE {
        return Ok(());
    }

    let mut known = THEME_FILES
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    known.extend(PREFERENCE_BACKUPS.iter().map(|(name, _)| *name));
    known.insert(MARKER);
    for entry in fs::read_dir(&destination)? {
        let entry = entry?;
        let path = entry.path();
        let name = entry.file_name();
        if is_symlink(&path)? || !known.contains(name.to_string_lossy().as_ref()) {
            return Err(ownership_error(format!(
                "Theme has files that SDH-Ludusavi did not install: {}",
                destination.display()
            )));
        }
    }
    if is_symlink(preferences_dir)? {
        return Err(ownership_error(format!(
            "Theme preferences directory is a symlink: {}",
            preferences_dir.display()
        )));
    }
    for (_, backup_name) in PREFERENCE_BACKUPS {
        let backup = preferences_dir.join(backup_name);
        if is_symlink(&backup)? {
            return Err(ownership_error(format!(
                "Theme preferences backup is a symlink: {}",
                backup.display()
            )));
        }
    }

    if !preferences_dir.exists() {
        fs::create_dir_all(preferences_dir)?;
        fs::set_permissions(preferences_dir, fs::Permissions::from_mode(0o700))?;
    }
    for (name, backup_name) in PREFERENCE_BACKUPS {
        let file = destination.join(name);
        let backup = preferences_dir.join(backup_name);
        if file.is_file() {
            atomic_write(&backup, &fs::read(&file)?, 0o600)?;
        } else {
            match fs::remove_file(&backup) {
                Ok(()) => (),
                Err(error) if error.kind() == io::ErrorKind::NotFound => (),
                Err(error) => return Err(error),
            }
        }
    }
    for name in known {
        match fs::remove_file(destination.join(name)) {
            Ok(()) => (),
            Err(error) if error.kind() == io::ErrorKind::NotFound => (),
            Err(error) => return Err(error),
        }
    }
    fs::remove_dir(destination)
}

#[cfg(test)]
mod tests {
    use std::{fs, os::unix::fs::PermissionsExt, path::Path};

    use tempfile::tempdir_in;

    use super::{install_status_theme, uninstall_status_theme};

    fn fixture(root: &Path) -> (std::path::PathBuf, std::path::PathBuf, std::path::PathBuf) {
        let source = root.join("plugin/theme");
        fs::create_dir_all(&source).unwrap();
        fs::write(
            source.join("theme.json"),
            r#"{"name":"SDH-Ludusavi Status"}"#,
        )
        .unwrap();
        for name in ["clean.css", "custom.css", "layout.css"] {
            fs::write(source.join(name), name).unwrap();
        }
        let decky_home = root.join("homebrew");
        let preferences = root.join("runtime");
        (source, decky_home, preferences)
    }

    #[test]
    fn install_and_uninstall_restore_only_owned_theme_preferences() {
        let root = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let (source, home, preferences) = fixture(root.path());
        fs::create_dir_all(&preferences).unwrap();
        fs::write(preferences.join("status-theme-priority"), "25\n").unwrap();
        let unrelated = home.join("themes/Other");
        fs::create_dir_all(&unrelated).unwrap();
        fs::write(unrelated.join("keep.css"), "keep").unwrap();

        assert!(install_status_theme(&source, &home, &preferences).unwrap());
        let theme = home.join("themes/SDH-Ludusavi Status");
        assert_eq!(fs::read_to_string(theme.join("PRIORITY")).unwrap(), "25\n");
        assert!(!install_status_theme(&source, &home, &preferences).unwrap());
        fs::write(theme.join("PRIORITY"), "42\n").unwrap();
        uninstall_status_theme(&home, &preferences).unwrap();
        assert_eq!(
            fs::read_to_string(preferences.join("status-theme-priority")).unwrap(),
            "42\n"
        );
        assert_eq!(
            fs::read_to_string(unrelated.join("keep.css")).unwrap(),
            "keep"
        );
        assert!(!theme.exists());
    }

    #[test]
    fn unmarked_theme_and_user_files_are_never_removed() {
        let root = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let (_source, home, preferences) = fixture(root.path());
        let theme = home.join("themes/SDH-Ludusavi Status");
        fs::create_dir_all(&theme).unwrap();
        fs::write(theme.join("theme.json"), "user-owned").unwrap();
        uninstall_status_theme(&home, &preferences).unwrap();
        assert!(
            theme.join("theme.json").is_file(),
            "unmarked theme was deleted"
        );
        assert_eq!(
            fs::read_to_string(theme.join("theme.json")).unwrap(),
            "user-owned"
        );

        let (source, owned_home, _) = fixture(&root.path().join("second"));
        install_status_theme(&source, &owned_home, &preferences).unwrap();
        let owned = owned_home.join("themes/SDH-Ludusavi Status");
        fs::write(owned.join("added.css"), "user-owned").unwrap();
        assert!(uninstall_status_theme(&owned_home, &preferences).is_err());
        assert!(owned.join("theme.json").is_file());
    }

    #[test]
    fn install_refuses_symlinked_theme_destination() {
        let root = tempdir_in("/var/tmp/sdh_ludusavi").unwrap();
        let (source, home, preferences) = fixture(root.path());
        let themes = home.join("themes");
        fs::create_dir_all(&themes).unwrap();
        let outside = root.path().join("outside");
        fs::create_dir_all(&outside).unwrap();
        std::os::unix::fs::symlink(&outside, themes.join("SDH-Ludusavi Status")).unwrap();
        assert!(install_status_theme(&source, &home, &preferences).is_err());
        assert_eq!(fs::read_dir(outside).unwrap().count(), 0);
        assert_eq!(
            fs::metadata(&themes).unwrap().permissions().mode() & 0o777,
            0o755
        );
    }
}
