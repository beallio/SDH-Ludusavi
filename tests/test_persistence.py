from __future__ import annotations
from sdh_ludusavi.persistence import JsonSettingsStore

import fcntl
import threading
from pathlib import Path

from sdh_ludusavi.persistence import PersistenceManager


def test_persistence_manager_split_storage(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    cache_file = tmp_path / "cache.json"

    store = JsonSettingsStore(settings_file)
    pm = PersistenceManager(settings_store=store, cache_path=cache_file)

    # Initial state should be empty/defaults
    data = pm.load_all()
    assert data["settings"] == {}
    assert data["cache"] == {}

    # Save settings and verify only settings file is written
    pm.save_settings({"auto_sync_enabled": True, "selected_game": "Hades"})
    assert settings_file.exists()
    assert not cache_file.exists()

    # Save cache and verify cache file is written
    pm.save_cache({"games": []})
    assert cache_file.exists()

    # Reload all
    data_reloaded = pm.load_all()
    assert data_reloaded["settings"]["auto_sync_enabled"] is True
    assert data_reloaded["cache"]["games"] == []


def test_locked_creates_lock_file_and_is_reentrant(tmp_path: Path) -> None:
    pm = PersistenceManager(
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )

    with pm.locked():
        with pm.locked():
            pm.save_settings({"auto_sync_enabled": True})
        assert pm.lock_path.exists()

    assert pm.load_all()["settings"]["auto_sync_enabled"] is True


def test_locked_excludes_other_lock_holders(tmp_path: Path) -> None:
    """flock exclusion is per open file description, so a second fd on the
    lock file stands in for a second plugin process."""
    pm = PersistenceManager(
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )

    def try_foreign_flock() -> bool:
        with open(pm.lock_path, "a", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return True

    with pm.locked():
        assert try_foreign_flock() is False
    assert try_foreign_flock() is True


def test_locked_serializes_other_threads(tmp_path: Path) -> None:
    pm = PersistenceManager(
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )
    inside = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def holder() -> None:
        with pm.locked():
            order.append("holder-in")
            inside.set()
            release.wait(timeout=5)
            order.append("holder-out")

    def contender() -> None:
        inside.wait(timeout=5)
        with pm.locked():
            order.append("contender-in")

    threads = [threading.Thread(target=holder), threading.Thread(target=contender)]
    for thread in threads:
        thread.start()
    assert inside.wait(timeout=5)
    release.set()
    for thread in threads:
        thread.join(timeout=10)

    assert order == ["holder-in", "holder-out", "contender-in"]
