from __future__ import annotations

from unittest.mock import MagicMock

from sdh_ludusavi.registry import GameRegistry, _normalize_installed_app_ids
from sdh_ludusavi.types import GameStatus


def test_installed_app_normalization() -> None:
    assert _normalize_installed_app_ids(None) is None
    assert _normalize_installed_app_ids("") == ""
    assert _normalize_installed_app_ids("   ") == ""
    assert _normalize_installed_app_ids("413150,300,413150") == "300,413150"
    assert _normalize_installed_app_ids("abc") is None
    assert _normalize_installed_app_ids("a" * 20000) is None


def test_registry_load_cache_and_payload() -> None:
    gateway = MagicMock()
    run_locked = MagicMock()
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)

    cache = {
        "games": [
            {
                "name": "Hades",
                "configured": True,
                "has_backup": True,
                "needs_first_backup": False,
                "steam_id": "413150",
                "error": None,
            }
        ],
        "aliases": {"H": "Hades"},
        "ids": {"413150": "Hades"},
        "installed_app_ids": "300,413150",
        "ludusavi_config_mtime_ns": 12345,
    }

    registry.load_cache(cache)

    assert "Hades" in registry._games
    assert registry._games["Hades"].steam_id == "413150"
    assert registry._aliases == {"H": "Hades"}
    assert registry._ids == {"413150": "Hades"}
    assert registry._installed_app_ids == "300,413150"
    assert registry._ludusavi_config_mtime_ns == 12345

    payload = registry.cache_payload()
    assert payload["aliases"] == {"H": "Hades"}
    assert payload["installed_app_ids"] == "300,413150"
    assert payload["ludusavi_config_mtime_ns"] == 12345
    assert len(payload["games"]) == 1


def test_registry_coerce_malformed_statuses() -> None:
    gateway = MagicMock()
    run_locked = MagicMock()
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)

    cache = {
        "games": [
            "not a dict",
            {"name": "Bad Game", "configured": "not a bool"},
        ],
    }
    registry.load_cache(cache)
    # The string entry should be skipped, but the dict one is coerced using standard bool coercion
    assert "Bad Game" in registry._games


def test_registry_config_mtime_refresh_gating() -> None:
    gateway = MagicMock()
    gateway.current_config_mtime_ns.return_value = 12345
    run_locked = MagicMock(side_effect=lambda op, game, cb: cb())
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)
    registry._games = {"Hades": GameStatus("Hades", True, True, False)}
    registry._ludusavi_config_mtime_ns = 12345

    # Check: no refresh is needed since config mtime matches and force=False
    res = registry.refresh_games(force=False)
    assert "games" in res
    run_locked.assert_not_called()

    # If force=True, it should trigger refresh
    gateway.get_adapter().refresh_statuses.return_value = [{"name": "Hades"}]
    res2 = registry.refresh_games(force=True)
    assert len(res2["games"]) == 1
    run_locked.assert_called_once()


def test_registry_dependency_error_fallback() -> None:
    gateway = MagicMock()
    gateway.current_config_mtime_ns.return_value = 12345
    run_locked = MagicMock(side_effect=RuntimeError("Ludusavi binary missing"))
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)
    registry._games = {"Hades": GameStatus("Hades", True, True, False)}

    res = registry.refresh_games(force=True)
    assert len(res["games"]) == 1
    assert res["dependency_error"] == "Ludusavi binary missing"
