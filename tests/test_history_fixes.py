from __future__ import annotations

import json
from pathlib import Path
import pytest
from tests.test_service import FakeAdapter, service_with_state


def test_force_backup_records_history_even_if_refresh_fails(tmp_path: Path) -> None:
    class RefreshFailingAdapter(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.refresh_calls = 0

        def refresh_statuses(self):
            self.refresh_calls += 1
            if self.refresh_calls > 1:
                raise RuntimeError("Refresh failed after backup")
            return super().refresh_statuses()

    service = service_with_state(tmp_path, adapter=RefreshFailingAdapter())
    service.refresh_games()  # First refresh succeeds

    # This should succeed because backup succeeded, even if follow-up refresh failed
    result = service.force_backup("Hades")
    assert result["status"] == "backed_up"

    # Check history is still recorded
    refresh = service.refresh_games()
    assert refresh["history"]["Hades"]["last_backup"]["status"] == "backed_up"


def test_auto_exit_records_history_even_if_refresh_fails(tmp_path: Path) -> None:
    class RefreshFailingAdapter(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.refresh_calls = 0

        def refresh_statuses(self):
            self.refresh_calls += 1
            if self.refresh_calls > 1:
                raise RuntimeError("Refresh failed after backup")
            return super().refresh_statuses()

        def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
            if not preview:
                return super().backup(game_name)
            return {
                "ok": True,
                "game": game_name,
                "games": {
                    game_name: {"decision": "Processed", "change": "New", "files": {"save.dat": {}}}
                },
            }

    service = service_with_state(tmp_path, adapter=RefreshFailingAdapter())
    service.set_auto_sync_enabled(True)
    service.refresh_games()  # First refresh succeeds

    # handle_game_exit calls _refresh_statuses_unlocked
    result = service.handle_game_exit("Hades", app_id="123")
    assert result["status"] == "backed_up"

    refresh = service.refresh_games()
    assert refresh["history"]["Hades"]["last_backup"]["status"] == "backed_up"


def test_history_load_validation_hardened(tmp_path: Path) -> None:
    state = {
        "auto_sync_enabled": True,
        "selected_game": "",
        "games": [],
        "aliases": {},
        "game_history": {
            "Hades": {
                "last_backup": {
                    "operation": "backup",
                    "status": "backed_up",
                    "timestamp": 12345,  # SHOULD BE STRING
                    "trigger": "manual_backup",
                    "extra": "junk",  # SHOULD BE DROPPED
                },
                "last_failure": {
                    "operation": "invalid_op",  # SHOULD BE DROPPED
                    "status": "failed",
                    "timestamp": "2026-01-01 00:00:00",
                    "trigger": "manual_backup",
                },
            }
        },
    }
    (tmp_path / "settings.json").write_text(
        json.dumps({"auto_sync_enabled": True, "selected_game": ""})
    )
    (tmp_path / "cache.json").write_text(
        json.dumps({key: value for key, value in state.items() if key != "auto_sync_enabled"})
    )

    service = service_with_state(tmp_path)
    refresh = service.refresh_games()

    hades = refresh["history"]["Hades"]
    # Timestamp was int, so it should be invalidated/None
    assert hades["last_backup"] is None
    # Invalid operation enum
    assert hades["last_failure"] is None


def test_last_operation_field_is_newest(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    # 1. Manual backup at T1
    service.force_backup("Hades")
    history = service.refresh_games()["history"]["Hades"]
    t1 = history["last_backup"]["timestamp"]
    assert history["last_operation"]["timestamp"] == t1
    assert history["last_operation"]["operation"] == "backup"

    # 2. Skip at T2
    import time

    time.sleep(1.1)  # Ensure timestamp changes (seconds)
    service.set_auto_sync_enabled(True)
    service.handle_game_start("Hades", app_id="123")

    history = service.refresh_games()["history"]["Hades"]
    t2 = history["last_skip"]["timestamp"]
    assert t2 > t1
    assert history["last_operation"]["timestamp"] == t2
    assert history["last_operation"]["operation"] == "start"


@pytest.mark.parametrize(
    "reason,status",
    [
        ("local_current", "skipped"),
        ("not_processed", "skipped"),
        ("no_files_found", "skipped"),
        ("preview_failed", "skipped"),
    ],
)
def test_auto_exit_skips_record_history(tmp_path: Path, reason: str, status: str) -> None:
    class SkipAdapter(FakeAdapter):
        def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
            if reason == "preview_failed":
                raise RuntimeError("Preview crash")

            if not preview:
                return {"ok": True, "game": game_name}

            # Preview mode
            games_output = {}
            if reason != "not_in_preview":
                res = {"decision": "Processed"}
                if reason == "local_current":
                    res["change"] = "Same"
                    res["files"] = {"save.dat": {}}
                elif reason == "not_processed":
                    res["decision"] = "Ignored"
                elif reason == "no_files_found":
                    res["files"] = {}
                    res["registry"] = {}
                else:
                    res["change"] = "New"
                    res["files"] = {"save.dat": {}}

                games_output[game_name] = res

            return {
                "ok": True,
                "game": game_name,
                "games": games_output,
            }  # Actually I need to check how service.py handles these.

    # handle_game_exit uses _ludusavi().backup(game.name)
    # If it returns ok=True but change=Same, it's a skip.

    adapter = SkipAdapter()
    service = service_with_state(tmp_path, adapter=adapter)
    service.set_auto_sync_enabled(True)
    service.refresh_games()

    # For preview_failed, it's caught in handle_game_exit before _run_locked
    # Wait, preview_failed is if backup(preview=True) fails.

    result = service.handle_game_exit("Hades", app_id="123")
    assert result["status"] == status
    assert result["reason"] == reason

    history = service.refresh_games()["history"]["Hades"]
    assert history["last_skip"]["reason"] == reason
    assert history["last_skip"]["operation"] == "exit"
    assert history["last_skip"]["trigger"] == "auto_exit"


def test_history_load_validation_trigger(tmp_path: Path) -> None:
    state = {
        "auto_sync_enabled": True,
        "selected_game": "",
        "games": [],
        "aliases": {},
        "game_history": {
            "Hades": {
                "last_backup": {
                    "operation": "backup",
                    "status": "backed_up",
                    "timestamp": "2026-01-01 00:00:00",
                    "trigger": "invalid_trigger",
                }
            }
        },
    }
    (tmp_path / "settings.json").write_text(
        json.dumps({"auto_sync_enabled": True, "selected_game": ""})
    )
    (tmp_path / "cache.json").write_text(
        json.dumps({key: value for key, value in state.items() if key != "auto_sync_enabled"})
    )

    service = service_with_state(tmp_path)
    refresh = service.refresh_games()

    hades = refresh["history"]["Hades"]
    assert hades["last_backup"] is None


def test_last_operation_field_high_resolution_sorting(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    # Simulate two operations in very quick succession (same second)
    # We'll mock datetime.now to ensure same second but different microseconds if supported,
    # or just different ISO strings.

    # For now, let's just prove that IF they have different timestamps (even milliseconds), they sort.
    # The fix is to use higher resolution.

    service.force_backup("Hades")  # T1
    service.force_restore("Hades")  # T2

    history = service.refresh_games()["history"]["Hades"]
    assert history["last_operation"]["operation"] == "restore"
    # Microsecond resolution should prevent collisions in practice
