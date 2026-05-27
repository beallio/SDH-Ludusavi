from __future__ import annotations


from sdh_ludusavi.matcher import GameRegistryMatcher
from sdh_ludusavi.service import GameStatus


def test_game_registry_matcher_normalization() -> None:
    matcher = GameRegistryMatcher()
    assert matcher.normalize("Hades II (Supergiant)") == "hades ii supergiant"
    assert matcher.normalize("Portal-2...!") == "portal-2..."


def test_game_registry_matcher_exact_and_alias() -> None:
    matcher = GameRegistryMatcher()
    games = {
        "Hades": GameStatus("Hades", True, True, False),
        "Celeste": GameStatus("Celeste", True, False, True),
    }
    aliases = {"Hades 1": "Hades"}
    ids = {"1145360": "Hades"}

    # Match by Steam ID
    res = matcher.match_game("Hades 1", "1145360", games, aliases, ids)
    assert res is not None
    assert res.name == "Hades"

    # Match by Alias
    res_alias = matcher.match_game("Hades 1", None, games, aliases, ids)
    assert res_alias is not None
    assert res_alias.name == "Hades"

    # Match by Normalized Exact
    res_exact = matcher.match_game("celeste", None, games, aliases, ids)
    assert res_exact is not None
    assert res_exact.name == "Celeste"


def test_game_registry_matcher_fuzzy() -> None:
    matcher = GameRegistryMatcher()
    games = {
        "Super Metroid": GameStatus("Super Metroid", True, True, False),
    }

    # Match by Substring
    res = matcher.match_game("Metroid", None, games, {}, {})
    assert res is not None
    assert res.name == "Super Metroid"

    # Short substring matching is blocked for unconfigured/too short matches
    res_short = matcher.match_game("Met", None, games, {}, {})
    assert res_short is None
