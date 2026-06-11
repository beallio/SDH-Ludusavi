from __future__ import annotations

from unittest.mock import MagicMock
import threading

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


def test_targeted_refresh_merges_single_game() -> None:
    gateway = MagicMock()
    run_locked = MagicMock(side_effect=lambda op, game, cb: cb())
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)
    registry._games = {
        "Hades": GameStatus("Hades", True, True, False, "1145360"),
        "Portal": GameStatus("Portal", True, True, False, "400"),
    }
    registry._ids = {"1145360": "Hades", "400": "Portal"}

    adapter = MagicMock()
    gateway.get_adapter.return_value = adapter
    adapter.refresh_statuses.return_value = [
        {
            "name": "Hades",
            "configured": True,
            "has_backup": False,
            "needs_first_backup": True,
            "steam_id": "99999",
            "error": None,
        }
    ]

    registry.refresh_after_operation(game_name="Hades")

    assert "Portal" in registry._games
    assert registry._games["Portal"].has_backup is True
    assert "Hades" in registry._games
    assert registry._games["Hades"].has_backup is False
    assert len(registry._games) == 2
    assert registry._ids == {"99999": "Hades", "400": "Portal"}
    save.assert_called_once()


def test_targeted_refresh_empty_result_logs_warning() -> None:
    gateway = MagicMock()
    run_locked = MagicMock(side_effect=lambda op, game, cb: cb())
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)
    registry._games = {
        "Hades": GameStatus("Hades", True, True, False, "1145360"),
    }
    registry._ids = {"1145360": "Hades"}

    adapter = MagicMock()
    gateway.get_adapter.return_value = adapter
    adapter.refresh_statuses.return_value = []

    registry.refresh_after_operation(game_name="Hades")

    log.assert_any_call(
        "warning", "Targeted refresh for 'Hades' returned no results; cache unchanged", "refresh"
    )
    assert registry._games == {"Hades": GameStatus("Hades", True, True, False, "1145360")}
    assert registry._ids == {"1145360": "Hades"}


def test_refresh_after_operation_null_game_name_does_full_refresh() -> None:
    gateway = MagicMock()
    run_locked = MagicMock(side_effect=lambda op, game, cb: cb())
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)
    registry._games = {
        "Portal": GameStatus("Portal", True, True, False, "400"),
    }
    registry._ids = {"400": "Portal"}

    adapter = MagicMock()
    gateway.get_adapter.return_value = adapter
    adapter.refresh_statuses.return_value = [
        {
            "name": "Hades",
            "configured": True,
            "has_backup": True,
            "needs_first_backup": False,
            "steam_id": "1145360",
            "error": None,
        }
    ]

    registry.refresh_after_operation(game_name=None)

    assert "Portal" not in registry._games
    assert "Hades" in registry._games


def test_targeted_refresh_skips_alias_rebuild_when_config_stale() -> None:
    gateway = MagicMock()
    run_locked = MagicMock(side_effect=lambda op, game, cb: cb())
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})

    registry = GameRegistry(gateway, run_locked, log, save, get_history)
    registry._ludusavi_config_mtime_ns = 12345
    registry._games = {"Hades": GameStatus("Hades", True, True, False)}

    adapter = MagicMock()
    gateway.get_adapter.return_value = adapter
    adapter.refresh_statuses.return_value = [
        {
            "name": "Hades",
            "configured": True,
            "has_backup": True,
            "needs_first_backup": False,
            "steam_id": None,
            "error": None,
        }
    ]

    registry.refresh_after_operation(game_name="Hades")
    adapter.get_aliases.assert_not_called()

    registry._ludusavi_config_mtime_ns = None
    registry.refresh_after_operation(game_name="Hades")
    adapter.get_aliases.assert_not_called()


class TrackingRLock:
    """RLock wrapper that records acquisition depth for lock-coverage tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.depth = 0
        self.acquisitions = 0

    def __enter__(self) -> "TrackingRLock":
        self._lock.acquire()
        self.depth += 1
        self.acquisitions += 1
        return self

    def __exit__(self, *exc: object) -> None:
        self.depth -= 1
        self._lock.release()


def test_refresh_games_cache_hit_reads_under_state_lock() -> None:
    gateway = MagicMock()
    run_locked = MagicMock()
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})
    gateway.current_config_mtime_ns.return_value = 12345

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
    registry._state_lock = TrackingRLock()

    result = registry.refresh_games(force=False, installed_app_ids="300,413150")

    assert result["dependency_error"] is None
    assert len(result["games"]) == 1
    run_locked.assert_not_called()
    assert registry._state_lock.acquisitions >= 1


def test_refresh_games_fallback_reads_under_state_lock() -> None:
    gateway = MagicMock()
    run_locked = MagicMock(side_effect=RuntimeError("boom"))
    log = MagicMock()
    save = MagicMock()
    get_history = MagicMock(return_value={})
    gateway.current_config_mtime_ns.return_value = 12345

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
    registry._state_lock = TrackingRLock()

    result = registry.refresh_games(force=True)

    assert "boom" in str(result["dependency_error"])
    assert len(result["games"]) == 1
    assert registry._state_lock.acquisitions >= 1
