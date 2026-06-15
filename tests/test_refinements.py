from __future__ import annotations
from sdh_ludusavi.persistence import JsonSettingsStore

import json
from pathlib import Path

from sdh_ludusavi.service import SDHLudusaviService


class FakeAdapter:
    def __init__(self) -> None:
        self.games = [
            {
                "name": "Hades",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
            }
        ]

    def refresh_statuses(self) -> list[dict[str, object]]:
        return [dict(game) for game in self.games]

    def get_versions(self) -> dict[str, str]:
        return {"ludusavi": "0.0.0"}


def service_with_state(tmp_path: Path) -> SDHLudusaviService:
    return SDHLudusaviService(
        adapter=FakeAdapter(),
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )


def test_selected_game_persistence(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    # Default should be empty string
    assert service.get_settings()["selected_game"] == ""

    # Setting selected game
    service.set_selected_game("Hades")
    assert service.get_settings()["selected_game"] == "Hades"

    # Persistence check
    reloaded = service_with_state(tmp_path)
    assert reloaded.get_settings()["selected_game"] == "Hades"

    # File check
    state = json.loads((tmp_path / "settings.json").read_text())
    assert state["selected_game"] == "Hades"


def test_unified_logging_exposure(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    service.log("info", "First message", operation="op1")
    service.log("info", "Second message", operation="op2")

    logs = service.get_recent_logs()
    # account for the 3 initialization logs (init message, identity, environment) + 2 test logs
    assert len(logs) == 5

    # Chronological order: First should be at index 0
    assert logs[-2]["message"] == "First message"
    assert logs[-1]["message"] == "Second message"

    # Assert timestamp presence
    assert "timestamp" in logs[0]
    assert len(logs[0]["timestamp"]) == 19  # YYYY-MM-DD HH:MM:SS
