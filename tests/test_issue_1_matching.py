from __future__ import annotations
from sdh_ludusavi.service import SDHLudusaviService
from sdh_ludusavi.types import GameStatus


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


def test_fuzzy_matching_length_check(tmp_path):
    state_file = tmp_path / "state.json"
    service = SDHLudusaviService(adapter=FakeAdapter(), state_path=state_file)

    # Manually populate _games for testing _match_game
    service._registry._games = {
        "A Game": GameStatus(
            name="A Game", configured=True, has_backup=True, needs_first_backup=False, error=None
        ),
        "Portal 2": GameStatus(
            name="Portal 2", configured=True, has_backup=True, needs_first_backup=False, error=None
        ),
        "Game of Thrones": GameStatus(
            name="Game of Thrones",
            configured=True,
            has_backup=True,
            needs_first_backup=False,
            error=None,
        ),
    }

    # "A" should NOT match "A Game" (current failure case)
    # "A" has len 1, "A Game" has len 6.
    # Current logic: len("A") > 4 (False) or len("A Game") > 4 (True) -> True. MATCHES!
    assert service._registry.match_game("A") is None

    # "Portal" SHOULD match "Portal 2" (both > 4 chars)
    # len("Portal") = 6, len("Portal 2") = 8. BOTH > 4.
    assert service._registry.match_game("Portal") is not None
    assert service._registry.match_game("Portal").name == "Portal 2"

    # "Game" should NOT match "Game of Thrones" (4 chars <= 4 chars limit)
    # len("Game") = 4. 4 > 4 is False.
    assert service._registry.match_game("Game") is None
