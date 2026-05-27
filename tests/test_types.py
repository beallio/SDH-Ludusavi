from __future__ import annotations

from sdh_ludusavi.types import GameStatus


def test_game_status_properties() -> None:
    game = GameStatus(
        name="Test Game",
        configured=True,
        has_backup=False,
        needs_first_backup=True,
    )
    assert game.status == "needs_first_backup"
    assert game.to_dict()["status"] == "needs_first_backup"
