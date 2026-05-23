from __future__ import annotations

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
        self.restores = []
        self.backups = []
        self.recency = {"Hades": "backup_newer"}

    def refresh_statuses(self) -> list[dict[str, object]]:
        return [dict(game) for game in self.games]

    def get_versions(self) -> dict[str, str]:
        return {"ludusavi": "0.0.0"}

    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]:
        self.restores.append(game_name)
        return {"status": "restored", "game": game_name}

    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
        self.backups.append(game_name)
        return {"status": "backed_up", "game": game_name}

    def compare_recency(self, game_name: str) -> str:
        return self.recency.get(game_name, "local_current")

    def get_conflict_metadata(self, game_name: str) -> dict[str, object]:
        return {}


def service_with_state(tmp_path: Path, adapter: FakeAdapter) -> SDHLudusaviService:
    return SDHLudusaviService(adapter=adapter, state_path=tmp_path / "state.json")


def test_get_game_history_empty_by_default(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    assert service.get_game_history() == {}


def test_get_game_history_populated_by_auto_actions(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = service_with_state(tmp_path, adapter)
    service.refresh_games()
    service.set_auto_sync_enabled(True)

    # Perform an auto restore on start
    service.restore_game_on_start("Hades", app_id="1145360")

    # The history should now contain Hades with the last_restore record
    history = service.get_game_history()
    assert "Hades" in history
    assert history["Hades"]["last_restore"]["trigger"] == "auto_start"
    assert history["Hades"]["last_restore"]["status"] == "restored"
    assert history["Hades"]["last_operation"]["trigger"] == "auto_start"
