"""Install the optional CSS Loader theme without taking over other themes."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

THEME_NAME = "SDH-Ludusavi Status"
_THEME_FILES = ("theme.json", "clean.css", "custom.css", "layout.css")
_MARKER = ".sdh-ludusavi-status-theme"
_MARKER_VALUE = "sdh-ludusavi-status-theme-1\n"
_PREFERENCE_BACKUPS = {
    "config_USER.json": "status-theme-choices.json",
    "config_ROOT.json": "status-theme-root-choices.json",
    "PRIORITY": "status-theme-priority",
}


class ThemeOwnershipError(Exception):
    """An existing theme folder or file belongs to someone else."""


def _theme_directory(decky_home: Path) -> Path:
    return decky_home / "themes" / THEME_NAME


def _atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(content)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install_status_theme(source: Path, decky_home: Path, preferences_dir: Path) -> bool:
    """Deploy bundled files and report whether CSS Loader must reload them."""
    manifest_file = source / "theme.json"
    if manifest_file.is_symlink() or any((source / name).is_symlink() for name in _THEME_FILES):
        raise ThemeOwnershipError("Bundled theme files must not be symlinks")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("name") != THEME_NAME:
        raise ValueError("Bundled CSS Loader theme has an unexpected name")
    changed = False

    destination = _theme_directory(decky_home)
    if destination.is_symlink():
        raise ThemeOwnershipError(f"Theme directory is a symlink: {destination}")
    if destination.exists():
        marker = destination / _MARKER
        if marker.is_symlink() or not marker.is_file() or marker.read_text() != _MARKER_VALUE:
            raise ThemeOwnershipError(
                f"Theme directory is not managed by SDH-Ludusavi: {destination}"
            )
    else:
        destination.mkdir(parents=True, mode=0o755)
        _atomic_write(destination / _MARKER, _MARKER_VALUE.encode("ascii"), mode=0o600)

    for name in _THEME_FILES:
        file = destination / name
        if file.is_symlink():
            raise ThemeOwnershipError(f"Managed theme file is a symlink: {file}")
        content = (source / name).read_bytes()
        if not file.exists() or file.read_bytes() != content:
            _atomic_write(file, content)
            changed = True

    for name, backup_name in _PREFERENCE_BACKUPS.items():
        file = destination / name
        backup = preferences_dir / backup_name
        if file.is_symlink() or backup.is_symlink():
            raise ThemeOwnershipError(f"Theme preferences contain a symlink: {file}")
        if not file.exists() and backup.is_file():
            _atomic_write(file, backup.read_bytes(), mode=0o644 if name == "PRIORITY" else 0o600)
            changed = True

    config = destination / "config_USER.json"
    if not config.exists():
        _atomic_write(config, b'{"active": true}\n', mode=0o600)
        changed = True
    return changed


def uninstall_status_theme(decky_home: Path, preferences_dir: Path) -> None:
    """Remove only an owned theme, keeping CSS Loader choices for reinstalls."""
    destination = _theme_directory(decky_home)
    if destination.is_symlink() or not destination.is_dir():
        return
    marker = destination / _MARKER
    if marker.is_symlink() or not marker.is_file() or marker.read_text() != _MARKER_VALUE:
        return

    known = {*_THEME_FILES, *_PREFERENCE_BACKUPS, _MARKER}
    if any(file.name not in known or file.is_symlink() for file in destination.iterdir()):
        raise ThemeOwnershipError(
            f"Theme has files that SDH-Ludusavi did not install: {destination}"
        )
    if preferences_dir.is_symlink():
        raise ThemeOwnershipError(f"Theme preferences directory is a symlink: {preferences_dir}")
    for backup_name in _PREFERENCE_BACKUPS.values():
        backup = preferences_dir / backup_name
        if backup.is_symlink():
            raise ThemeOwnershipError(f"Theme preferences backup is a symlink: {backup}")

    preferences_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    for name, backup_name in _PREFERENCE_BACKUPS.items():
        file = destination / name
        backup = preferences_dir / backup_name
        if file.is_file():
            _atomic_write(backup, file.read_bytes(), mode=0o600)
        else:
            backup.unlink(missing_ok=True)

    for name in known:
        (destination / name).unlink(missing_ok=True)
    destination.rmdir()
