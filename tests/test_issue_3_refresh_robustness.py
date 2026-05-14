from __future__ import annotations
from sdh_ludusavi.service import SDHLudusaviService


class MalformedAdapter:
    def __init__(self):
        self.games = [
            {
                "name": "Hades",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
            },
            None,
            {
                "name": "Celeste",
                "configured": True,
                "has_backup": False,
                "needs_first_backup": True,
                "error": None,
            },
        ]

    def refresh_statuses(self):
        return self.games

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


def test_refresh_robustness_with_non_mapping(tmp_path):
    state_file = tmp_path / "state.json"
    service = SDHLudusaviService(adapter=MalformedAdapter(), state_path=state_file)

    # This should not crash despite the 'None' in the games list
    service.refresh_games(force=True)

    assert "Hades" in service._games
    assert "Celeste" in service._games
    assert len(service._games) == 2
