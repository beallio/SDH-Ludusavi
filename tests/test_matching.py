from __future__ import annotations

from pathlib import Path

from sdh_ludusavi.service import SDHLudusaviService


class FakeAdapter:
    def __init__(self) -> None:
        self.games = [
            {
                "name": "Hades",
                "steam_id": "413150",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
            },
            {
                "name": "The Witcher 3: Wild Hunt",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
            },
            {
                "name": "Doom",
                "steam_id": None,
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "error": None,
            },
        ]
        self.aliases = {"Custom Alias": "Hades", "Shortcut Name": "The Witcher 3: Wild Hunt"}

    def refresh_statuses(self) -> list[dict[str, object]]:
        return [dict(game) for game in self.games]

    def get_versions(self) -> dict[str, str]:
        return {"ludusavi": "0.0.0"}

    def get_aliases(self) -> dict[str, str]:
        return dict(self.aliases)

    def compare_recency(self, game_name: str) -> str:
        return "local_current"

    def backup(self, game_name: str) -> dict[str, object]:
        return {"ok": True}

    def restore(self, game_name: str) -> dict[str, object]:
        return {"ok": True}


def service_with_state(tmp_path: Path) -> SDHLudusaviService:
    return SDHLudusaviService(adapter=FakeAdapter(), state_path=tmp_path / "state.json")


def test_match_by_steam_id(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    # Matching by exact ID should work
    game = service._registry.match_game("Some Name", app_id="413150")
    assert game is not None
    assert game.name == "Hades"


def test_match_by_alias(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    # Matching by Ludusavi alias
    game = service._registry.match_game("Custom Alias")
    assert game is not None
    assert game.name == "Hades"

    game2 = service._registry.match_game("Shortcut Name")
    assert game2 is not None
    assert game2.name == "The Witcher 3: Wild Hunt"


def test_match_by_fuzzy_substring(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    # Matching by substring (Steam has shorter name)
    game = service._registry.match_game("The Witcher 3")
    assert game is not None
    assert game.name == "The Witcher 3: Wild Hunt"

    # Matching by reverse substring (Steam has longer name)
    game2 = service._registry.match_game("Hades: Battle Out of Hell")
    assert game2 is not None
    assert game2.name == "Hades"


def test_short_configured_game_name_matches_boundary_safe_launcher_name(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    game = service._registry.match_game("Doom v1.0")

    assert game is not None
    assert game.name == "Doom"


def test_normalization_retains_special_chars(tmp_path: Path) -> None:
    from sdh_ludusavi.matcher import GameRegistryMatcher

    # Periods and hyphens should be retained in the refined version
    assert GameRegistryMatcher().normalize("Game.v1-2") == "game.v1-2"
    assert GameRegistryMatcher().normalize("Game: Edition") == "game edition"
