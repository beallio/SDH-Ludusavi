from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdh_ludusavi.service import OperationLockedError, SDHLudusaviService


class FakeAdapter:
    def __init__(self) -> None:
        self.games = [
            {
                "name": "Hades",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
            },
            {
                "name": "Celeste",
                "configured": True,
                "has_backup": False,
                "needs_first_backup": True,
                "error": None,
            },
        ]
        self.recency = {"Hades": "local_current"}
        self.backups: list[str] = []
        self.restores: list[str] = []
        self.versions = {"ludusavi": "ludusavi 0.31.0", "rclone": "rclone v1.66.0"}
        self.refresh_error: Exception | None = None

    def refresh_statuses(self) -> list[dict[str, object]]:
        if self.refresh_error:
            raise self.refresh_error
        return [dict(game) for game in self.games]

    def compare_recency(self, game_name: str) -> str:
        return self.recency.get(game_name, "ambiguous")

    def backup(self, game_name: str) -> dict[str, object]:
        self.backups.append(game_name)
        return {"ok": True, "game": game_name}

    def restore(self, game_name: str) -> dict[str, object]:
        self.restores.append(game_name)
        return {"ok": True, "game": game_name}

    def get_versions(self) -> dict[str, str]:
        return dict(self.versions)


def service_with_state(tmp_path: Path, adapter: FakeAdapter | None = None) -> SDHLudusaviService:
    return SDHLudusaviService(adapter=adapter or FakeAdapter(), state_path=tmp_path / "state.json")


def test_settings_persist_auto_sync_toggle(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    assert service.get_settings() == {"auto_sync_enabled": False}
    assert service.set_auto_sync_enabled(True) == {"auto_sync_enabled": True}

    reloaded = service_with_state(tmp_path)

    assert reloaded.get_settings() == {"auto_sync_enabled": True}
    assert json.loads((tmp_path / "state.json").read_text())["auto_sync_enabled"] is True


def test_refresh_games_caches_statuses(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    result = service.refresh_games()

    assert [game["name"] for game in result["games"]] == ["Hades", "Celeste"]
    assert result["games"][0]["status"] == "has_backup"
    assert result["games"][1]["status"] == "needs_first_backup"
    assert service.get_operation_status()["is_running"] is False


def test_start_matches_steam_and_non_steam_names_conservatively(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    adapter.recency["Hades"] = "backup_newer"
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    steam_result = service.handle_game_start("hades", app_id="1145360")
    non_steam_result = service.handle_game_start("Celeste")

    assert steam_result["status"] == "restored"
    assert non_steam_result["status"] == "skipped"
    assert non_steam_result["reason"] == "no_backup"
    assert adapter.restores == ["Hades"]


def test_start_skips_disabled_unmatched_local_current_and_ambiguous(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    disabled = service.handle_game_start("Hades")
    service.set_auto_sync_enabled(True)
    unmatched = service.handle_game_start("Unknown Game")
    local_current = service.handle_game_start("Hades")
    adapter.recency["Hades"] = "ambiguous"
    ambiguous = service.handle_game_start("Hades")

    assert disabled["reason"] == "auto_sync_disabled"
    assert unmatched["reason"] == "unmatched_game"
    assert local_current["reason"] == "local_current"
    assert ambiguous["reason"] == "ambiguous_recency"
    assert adapter.restores == []


def test_exit_backs_up_only_when_auto_sync_enabled_and_matched(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    disabled = service.handle_game_exit("Hades")
    service.set_auto_sync_enabled(True)
    unmatched = service.handle_game_exit("Unknown Game")
    backed_up = service.handle_game_exit("Hades")

    assert disabled["reason"] == "auto_sync_disabled"
    assert unmatched["reason"] == "unmatched_game"
    assert backed_up["status"] == "backed_up"
    assert adapter.backups == ["Hades"]


def test_force_operations_work_when_auto_sync_disabled(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    backup = service.force_backup("Hades")
    restore = service.force_restore("Hades")

    assert service.get_settings() == {"auto_sync_enabled": False}
    assert backup["status"] == "backed_up"
    assert restore["status"] == "restored"
    assert adapter.backups == ["Hades"]
    assert adapter.restores == ["Hades"]


def test_global_operation_lock_blocks_new_operations(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()
    service._operation.is_running = True
    service._operation.name = "refresh"

    with pytest.raises(OperationLockedError):
        service.force_backup("Hades")

    assert service.get_operation_status()["name"] == "refresh"


def test_version_lookup_and_missing_dependency_states_are_logged(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    assert service.get_versions() == {"ludusavi": "ludusavi 0.31.0", "rclone": "rclone v1.66.0"}

    adapter.refresh_error = RuntimeError("Ludusavi Flatpak is not installed")
    result = service.refresh_games()

    assert result["dependency_error"] == "Ludusavi Flatpak is not installed"
    assert service.get_recent_logs()[0]["level"] == "error"
    assert "Ludusavi Flatpak" in service.get_recent_logs()[0]["message"]
