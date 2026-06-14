from __future__ import annotations

import json
from pathlib import Path
import pytest

from tests.test_service import FakeAdapter, service_with_state


def test_history_manual_backup_success(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    # The adapter initially has Hades and Celeste
    service.refresh_games()

    result = service.force_backup("Hades")
    assert result.get("status") == "backed_up"

    # Refresh to see the history
    refresh = service.refresh_games()
    history = refresh["history"]["Hades"]

    assert history["last_backup"] is not None
    assert history["last_backup"]["operation"] == "backup"
    assert history["last_backup"]["trigger"] == "manual_backup"
    assert history["last_backup"]["status"] == "backed_up"
    assert history["last_backup"]["reason"] is None
    assert history["last_backup"]["message"] is None
    assert isinstance(history["last_backup"]["timestamp"], str)


def test_history_manual_restore_success(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    result = service.force_restore("Hades")
    assert result["status"] == "restored"

    refresh = service.refresh_games()
    history = refresh["history"]["Hades"]

    assert history["last_restore"] is not None
    assert history["last_restore"]["operation"] == "restore"
    assert history["last_restore"]["trigger"] == "manual_restore"
    assert history["last_restore"]["status"] == "restored"


def test_history_point_in_time_restore_records_restored(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    result = service.restore_backup_version("Hades", "backup-123")
    assert result["status"] == "restored"

    refresh = service.refresh_games()
    history = refresh["history"]["Hades"]
    assert history["last_restore"] is not None
    assert history["last_restore"]["trigger"] == "manual_restore"
    assert history["last_restore"]["status"] == "restored"
    assert history["last_operation"]["status"] == "restored"
    assert history["last_operation"]["operation"] == "restore"


def test_history_auto_start_skip_records_last_skip(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.set_auto_sync_enabled(True)
    service.refresh_games()

    # recency is "local_current" for Hades by default in FakeAdapter
    result = service.handle_game_start("Hades", app_id="123")
    assert result.get("status") == "skipped"

    refresh = service.refresh_games()
    history = refresh["history"]["Hades"]

    assert history["last_skip"] is not None
    assert history["last_skip"]["operation"] == "start"
    assert history["last_skip"]["trigger"] == "auto_start"
    assert history["last_skip"]["status"] == "skipped"
    assert history["last_skip"]["reason"] == "local_current"


def test_history_global_auto_sync_disabled_no_history(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.set_auto_sync_enabled(False)
    service.refresh_games()

    result = service.handle_game_start("Hades", app_id="123")
    assert result.get("status") == "skipped"

    refresh = service.refresh_games()
    # Global disable should not record a game-specific skip
    assert "Hades" not in refresh["history"] or refresh["history"]["Hades"]["last_skip"] is None


def test_history_game_scoped_failure_records_last_failure(tmp_path: Path) -> None:
    class ErrorAdapter(FakeAdapter):
        def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
            raise RuntimeError("Fake backup crash")

    service = service_with_state(tmp_path, adapter=ErrorAdapter())
    service.refresh_games()

    with pytest.raises(RuntimeError, match="Fake backup crash"):
        service.force_backup("Hades")

    refresh = service.refresh_games()
    history = refresh["history"]["Hades"]

    assert history["last_failure"] is not None
    assert history["last_failure"]["operation"] == "backup"
    assert history["last_failure"]["status"] == "failed"
    assert history["last_failure"]["message"] == "Fake backup crash"


def test_history_reloading_preserves_history(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()
    service.force_backup("Hades")

    reloaded = service_with_state(tmp_path)
    refresh = reloaded.refresh_games()

    assert "Hades" in refresh["history"]
    assert refresh["history"]["Hades"]["last_backup"] is not None


def test_history_malformed_state_loads_safely(tmp_path: Path) -> None:
    state = {
        "auto_sync_enabled": True,
        "selected_game": "",
        "games": [],
        "aliases": {},
        "game_history": {"Hades": {"last_backup": "not_a_dict"}, "Celeste": "not_a_dict_either"},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))

    service = service_with_state(tmp_path)
    refresh = service.refresh_games()

    # Malformed parts are dropped or ignored, but it shouldn't crash
    # The exact handling of malformed per-game summary is "ignored for that game"
    assert "Celeste" not in refresh["history"]
    assert refresh["history"].get("Hades", {}).get("last_backup") is None


def test_history_refresh_disappeared_game_keeps_history(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.refresh_games()
    service.force_backup("Hades")

    # Remove Hades from Ludusavi
    adapter.games = [g for g in adapter.games if g["name"] != "Hades"]

    refresh = service.refresh_games(force=True)
    assert not any(g["name"] == "Hades" for g in refresh["games"])
    assert "Hades" in refresh["history"]
    assert refresh["history"]["Hades"]["last_backup"] is not None


def test_history_dependency_error_returns_cached_history(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.refresh_games()
    service.force_backup("Hades")

    # Next refresh will fail
    adapter.refresh_error = RuntimeError("Cannot find flatpak")

    refresh = service.refresh_games(force=True)
    assert refresh["dependency_error"] == "Cannot find flatpak"
    assert "Hades" in refresh["history"]


def test_history_cache_hit_returns_cached_history(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.refresh_games()
    service.force_backup("Hades")

    # Ensure next refresh is a cache hit
    # The config mtime hasn't changed
    adapter.config_mtime_ns = adapter.config_mtime_ns  # same

    refresh = service.refresh_games()
    assert refresh.get("dependency_error") is None
    assert "Hades" in refresh["history"]


def test_force_backup_no_changes_records_skip(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.refresh_games()
    original_backup = adapter.backup

    def backup_same(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return original_backup(game_name, preview=True)
        adapter.backups.append(game_name)
        return {
            "overall": {"changedGames": {"new": 0, "different": 0, "same": 1}},
            "games": {game_name: {"change": "Same", "decision": "Processed"}},
        }

    adapter.backup = backup_same

    result = service.force_backup("Hades")

    assert result["status"] == "skipped"
    assert result["reason"] == "local_current"
    history = service.refresh_games()["history"]["Hades"]
    assert history["last_skip"]["status"] == "skipped"
    assert history["last_skip"]["reason"] == "local_current"
    assert history["last_skip"]["operation"] == "backup"
    assert history["last_skip"]["trigger"] == "manual_backup"
    assert history["last_backup"] is None
    assert history["last_operation"]["status"] == "skipped"


def test_force_backup_different_records_backed_up(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.refresh_games()
    original_backup = adapter.backup

    def backup_different(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return original_backup(game_name, preview=True)
        adapter.backups.append(game_name)
        return {"games": {game_name: {"change": "Different", "decision": "Processed"}}}

    adapter.backup = backup_different

    result = service.force_backup("Hades")

    assert result["status"] == "backed_up"
    history = service.refresh_games()["history"]["Hades"]
    assert history["last_backup"]["status"] == "backed_up"


def test_force_backup_missing_change_defaults_backed_up(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    result = service.force_backup("Hades")

    assert result["status"] == "backed_up"
    history = service.refresh_games()["history"]["Hades"]
    assert history["last_backup"]["status"] == "backed_up"


def test_force_restore_no_changes_records_skip(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.refresh_games()
    original_restore = adapter.restore

    def restore_same(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return original_restore(game_name, preview=True)
        adapter.restores.append(game_name)
        return {"games": {game_name: {"change": "Same", "decision": "Processed"}}}

    adapter.restore = restore_same

    result = service.force_restore("Hades")

    assert result["status"] == "skipped"
    assert result["reason"] == "local_current"
    history = service.refresh_games()["history"]["Hades"]
    assert history["last_skip"]["status"] == "skipped"
    assert history["last_skip"]["reason"] == "local_current"
    assert history["last_skip"]["operation"] == "restore"
    assert history["last_skip"]["trigger"] == "manual_restore"
    assert history["last_restore"] is None
    assert history["last_operation"]["status"] == "skipped"


def test_force_restore_different_records_restored(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.refresh_games()
    original_restore = adapter.restore

    def restore_different(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return original_restore(game_name, preview=True)
        adapter.restores.append(game_name)
        return {"games": {game_name: {"change": "Different", "decision": "Processed"}}}

    adapter.restore = restore_different

    result = service.force_restore("Hades")

    assert result["status"] == "restored"
    history = service.refresh_games()["history"]["Hades"]
    assert history["last_restore"]["status"] == "restored"


def test_history_does_not_alter_cache_markers(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    # Give it an installed_app_ids to persist
    service.refresh_games(installed_app_ids="123")
    service.force_backup("Hades")

    state = json.loads((tmp_path / "cache.json").read_text())
    assert state["installed_app_ids"] == "123"
    assert state["ludusavi_config_mtime_ns"] == 100
    assert "Hades" in state["game_history"]
