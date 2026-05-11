from __future__ import annotations

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
    return SDHLudusaviService(adapter=FakeAdapter(), state_path=tmp_path / "state.json")


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
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["selected_game"] == "Hades"


def test_unified_logging_exposure(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)

    service.log("info", "Test message", operation="test_op", game_name="Test Game")

    logs = service.get_recent_logs()
    assert len(logs) == 1
    assert logs[0]["level"] == "info"
    assert logs[0]["message"] == "Test message"
    assert logs[0]["operation"] == "test_op"
    assert logs[0]["game_name"] == "Test Game"
