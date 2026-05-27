from __future__ import annotations

import json
from pathlib import Path

from sdh_ludusavi.persistence import PersistenceManager, JsonSettingsStore


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


def test_persistence_manager_combined_storage(tmp_path: Path) -> None:
    combined_file = tmp_path / "state.json"
    pm = PersistenceManager(state_path=combined_file)

    data = pm.load_all()
    assert data["settings"] == {}
    assert data["cache"] == {}

    pm.save_settings({"auto_sync_enabled": True})
    assert combined_file.exists()

    # Verify both are written to the same file
    raw = json.loads(combined_file.read_text(encoding="utf-8"))
    assert raw["auto_sync_enabled"] is True

    pm.save_cache({"games": [{"name": "Celeste"}]})
    raw_updated = json.loads(combined_file.read_text(encoding="utf-8"))
    assert raw_updated["auto_sync_enabled"] is True
    assert raw_updated["games"] == [{"name": "Celeste"}]
