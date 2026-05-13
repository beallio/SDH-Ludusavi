from __future__ import annotations

import json
import logging
import threading
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

    def get_log_contents(self) -> str:
        return ""


def service_with_state(tmp_path: Path, adapter: FakeAdapter | None = None) -> SDHLudusaviService:
    return SDHLudusaviService(adapter=adapter or FakeAdapter(), state_path=tmp_path / "state.json")


def test_settings_do_not_initialize_ludusavi_adapter(tmp_path: Path) -> None:
    def fail_factory() -> FakeAdapter:
        raise RuntimeError("Ludusavi should not be initialized")

    service = SDHLudusaviService(
        adapter_factory=fail_factory,
        state_path=tmp_path / "state.json",
    )

    assert service.get_settings() == {"auto_sync_enabled": False, "selected_game": ""}
    assert service.set_auto_sync_enabled(True) == {"auto_sync_enabled": True, "selected_game": ""}


def test_refresh_reports_ludusavi_adapter_initialization_failure(tmp_path: Path) -> None:
    def fail_factory() -> FakeAdapter:
        raise RuntimeError("Ludusavi Flatpak is not available to Decky")

    service = SDHLudusaviService(
        adapter_factory=fail_factory,
        state_path=tmp_path / "state.json",
    )

    result = service.refresh_games()

    assert result == {
        "games": [],
        "aliases": {},
        "dependency_error": "Ludusavi Flatpak is not available to Decky",
    }
    assert service.get_recent_logs()[-1]["level"] == "error"
    assert "Ludusavi Flatpak" in service.get_recent_logs()[-1]["message"]


def test_ludusavi_adapter_factory_is_reused_after_success(tmp_path: Path) -> None:
    calls = 0

    def factory() -> FakeAdapter:
        nonlocal calls
        calls += 1
        return FakeAdapter()

    service = SDHLudusaviService(
        adapter_factory=factory,
        state_path=tmp_path / "state.json",
    )

    service.refresh_games()
    service.get_versions()

    assert calls == 1


def test_settings_persist_auto_sync_toggle(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    assert service.get_settings() == {"auto_sync_enabled": False, "selected_game": ""}
    assert service.set_auto_sync_enabled(True) == {"auto_sync_enabled": True, "selected_game": ""}

    reloaded = service_with_state(tmp_path)

    assert reloaded.get_settings() == {"auto_sync_enabled": True, "selected_game": ""}
    assert json.loads((tmp_path / "state.json").read_text()) == {
        "auto_sync_enabled": True,
        "selected_game": "",
        "ludusaviLauncherShortcutAppId": -1,
        "games": [],
        "aliases": {},
        "ids": {},
    }


def test_failed_state_save_keeps_existing_state_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"auto_sync_enabled": false}', encoding="utf-8")
    service = service_with_state(tmp_path)
    original_write_text = Path.write_text

    def fail_after_partial_temp_write(
        path: Path, data: str, *args: object, **kwargs: object
    ) -> int:
        if path.parent == tmp_path:
            original_write_text(path, '{"auto_sync_enabled":', *args, **kwargs)
            raise OSError("disk full")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_after_partial_temp_write)

    with pytest.raises(OSError, match="disk full"):
        service.set_auto_sync_enabled(True)

    assert json.loads(state_path.read_text(encoding="utf-8")) == {"auto_sync_enabled": False}


@pytest.mark.parametrize("contents", ["", "{", "[]"])
def test_invalid_state_files_load_defaults_and_log_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    contents: str,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(contents, encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="sdh_ludusavi.service"):
        service = service_with_state(tmp_path)

    assert service.get_settings() == {"auto_sync_enabled": False, "selected_game": ""}
    assert "Ignoring SDH-ludusavi state" in caplog.text


def test_unreadable_state_file_loads_defaults_and_logs_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"auto_sync_enabled": true}', encoding="utf-8")
    original_read_text = Path.read_text

    def unreadable(path: Path, *args: object, **kwargs: object) -> str:
        if path == state_path:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)

    with caplog.at_level(logging.WARNING, logger="sdh_ludusavi.service"):
        service = service_with_state(tmp_path)

    assert service.get_settings() == {"auto_sync_enabled": False, "selected_game": ""}
    assert "permission denied" in caplog.text


def test_refresh_games_caches_statuses(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    result = service.refresh_games()

    assert [game["name"] for game in result["games"]] == ["Hades", "Celeste"]
    assert result["games"][0]["status"] == "has_backup"
    assert result["games"][1]["status"] == "needs_first_backup"
    assert service.get_operation_status()["is_running"] is False
    assert service.get_operation_status()["name"] is None
    assert service.get_operation_status()["game_name"] is None


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

    # local_current requires preview logic mock if using real adapter,
    # but FakeAdapter is static here.
    local_current = service.handle_game_start("Hades")
    adapter.recency["Hades"] = "ambiguous"
    ambiguous = service.handle_game_start("Hades")

    assert disabled["reason"] == "auto_sync_disabled"
    assert unmatched["reason"] == "unmatched_game"
    assert local_current["reason"] == "local_current"
    assert ambiguous["reason"] == "ambiguous_recency"
    assert adapter.restores == []

    # Verify log levels for skips are now 'info'
    logs = service.get_recent_logs()
    skip_logs = [log for log in logs if "Skipping" in log["message"] or "Skipped" in log["message"]]
    assert all(log["level"] == "info" for log in skip_logs)


def test_exit_backs_up_only_when_auto_sync_enabled_and_matched(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    disabled = service.handle_game_exit("Hades")
    service.set_auto_sync_enabled(True)
    unmatched = service.handle_game_exit("Unknown Game")

    # Mock backup preview to return "Same" for Hades first
    original_backup = adapter.backup

    def backup_with_preview(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return {"games": {game_name: {"change": "Same"}}}
        return original_backup(game_name)

    adapter.backup = backup_with_preview
    local_current = service.handle_game_exit("Hades")

    # Now mock backup preview to return "Different"
    def backup_with_changes(game_name: str, preview: bool = False) -> dict[str, object]:
        if preview:
            return {"games": {game_name: {"change": "Different"}}}
        return original_backup(game_name)

    adapter.backup = backup_with_changes
    backed_up = service.handle_game_exit("Hades")

    assert disabled["reason"] == "auto_sync_disabled"
    assert unmatched["reason"] == "unmatched_game"
    assert local_current["reason"] == "local_current"
    assert backed_up["status"] == "backed_up"
    assert adapter.backups == ["Hades"]


def test_force_operations_work_when_auto_sync_disabled(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()

    backup = service.force_backup("Hades")
    restore = service.force_restore("Hades")

    assert service.get_settings() == {"auto_sync_enabled": False, "selected_game": ""}
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


def test_concurrent_operations_are_rejected_by_thread_safe_lock(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()
    entered = threading.Event()
    release = threading.Event()
    first_result: list[dict[str, object]] = []
    first_errors: list[BaseException] = []

    def slow_callback() -> dict[str, object]:
        entered.set()
        release.wait(timeout=1)
        return {"ok": True}

    def run_first_operation() -> None:
        try:
            first_result.append(service._run_locked("backup", "Hades", slow_callback))
        except BaseException as exc:  # pragma: no cover - failure details are asserted below.
            first_errors.append(exc)

    first_thread = threading.Thread(target=run_first_operation)
    first_thread.start()
    assert entered.wait(timeout=1)

    with pytest.raises(OperationLockedError):
        service._run_locked("restore", "Hades", lambda: {"ok": True})

    release.set()
    first_thread.join(timeout=1)

    assert not first_thread.is_alive()
    assert first_errors == []
    assert first_result == [{"ok": True}]


def test_version_lookup_and_missing_dependency_states_are_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sdh_ludusavi.service.resolve_version", lambda: "0.1.dev104+gabcdef")
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    versions = service.get_versions()
    assert versions["sdh_ludusavi"] == "0.1.dev104+gabcdef"
    assert "ludusavi" in versions
    assert "pyludusavi" in versions

    adapter.refresh_error = RuntimeError("Ludusavi Flatpak is not installed")
    result = service.refresh_games()

    assert result["dependency_error"] == "Ludusavi Flatpak is not installed"
    assert service.get_recent_logs()[-1]["level"] == "error"
    assert "Ludusavi Flatpak" in service.get_recent_logs()[-1]["message"]


def test_get_ludusavi_logs(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)

    # Case: Log file exists
    monkeypatch.setattr(adapter, "get_log_contents", lambda: "test log content")
    assert service.get_ludusavi_logs() == "test log content"

    # Case: Log file missing or empty
    monkeypatch.setattr(adapter, "get_log_contents", lambda: "")
    assert service.get_ludusavi_logs() == ""
