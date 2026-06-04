from pathlib import Path
from sdh_ludusavi.service import SDHLudusaviService


class FakeGame:
    def __init__(self, name, has_backup=True, error=None):
        self.name = name
        self.has_backup = has_backup
        self.error = error

    def to_dict(self):
        return {"name": self.name, "has_backup": self.has_backup, "error": self.error}


class FakeAdapter:
    def __init__(self):
        self.backups = []
        self.preview_data = {}

    def refresh_statuses(self, game_names=None):
        return [{"name": "Hades", "has_backup": True, "error": None}]

    def backup(self, game_name, preview=False):
        if preview:
            return self.preview_data
        self.backups.append(game_name)
        return {"games": {game_name: {"change": "Processed"}}}

    def get_aliases(self):
        return {}


def test_handle_game_exit_respects_ignored_decision(tmp_path):
    adapter = FakeAdapter()
    service = SDHLudusaviService(adapter=adapter, state_path=Path(tmp_path) / "state.json")
    service.set_auto_sync_enabled(True)
    service.refresh_games()

    # Case 1: Game is ignored in Ludusavi
    adapter.preview_data = {
        "games": {"Hades": {"change": "Different", "decision": "Ignored", "files": {"a": {}}}}
    }
    result = service.handle_game_exit("Hades")
    assert result["reason"] == "not_processed"
    assert "Hades" not in adapter.backups

    # Case 2: Game is cancelled in Ludusavi
    adapter.preview_data = {
        "games": {"Hades": {"change": "Different", "decision": "Cancelled", "files": {"a": {}}}}
    }
    result = service.handle_game_exit("Hades")
    assert result["reason"] == "not_processed"
    assert "Hades" not in adapter.backups

    # Case 3: Game is processed (default/normal)
    adapter.preview_data = {
        "games": {"Hades": {"change": "Different", "decision": "Processed", "files": {"a": {}}}}
    }
    result = service.handle_game_exit("Hades")
    assert result["status"] == "backed_up"
    assert "Hades" in adapter.backups
