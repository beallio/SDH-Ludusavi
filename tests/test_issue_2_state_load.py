from __future__ import annotations
from sdh_ludusavi.persistence import JsonSettingsStore
import json
from sdh_ludusavi.service import SDHLudusaviService


class FakeAdapter:
    def refresh_statuses(self):
        return []

    def compare_recency(self, name):
        return "local_current"

    def backup(self, name):
        return {"ok": True}

    def restore(self, name):
        return {"ok": True}

    def get_aliases(self):
        return {}

    def get_versions(self):
        return {"ludusavi": "0.0.0"}


def test_state_load_malformed_shortcut_id(tmp_path):
    state_file = tmp_path / "settings.json"

    # State with invalid shortcut ID
    malformed_data = {
        "auto_sync_enabled": True,
        "selected_game": "Hades",
        "ludusaviLauncherShortcutAppId": "not-an-int",
    }
    state_file.write_text(json.dumps(malformed_data))

    # This should not raise an exception
    service = SDHLudusaviService(
        adapter=FakeAdapter(),
        settings_store=JsonSettingsStore(state_file.with_name("settings.json")),
        cache_path=state_file.with_name("cache.json"),
    )

    assert service._auto_sync_enabled is True
    assert service._selected_game == "Hades"
    assert service._ludusavi_launcher_shortcut_id == -1


def test_state_load_null_shortcut_id(tmp_path):
    state_file = tmp_path / "settings.json"

    # State with null shortcut ID
    malformed_data = {"ludusaviLauncherShortcutAppId": None}
    state_file.write_text(json.dumps(malformed_data))

    service = SDHLudusaviService(
        adapter=FakeAdapter(),
        settings_store=JsonSettingsStore(state_file.with_name("settings.json")),
        cache_path=state_file.with_name("cache.json"),
    )
    assert service._ludusavi_launcher_shortcut_id == -1
