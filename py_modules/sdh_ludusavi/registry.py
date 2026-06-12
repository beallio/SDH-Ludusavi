from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any, Callable, cast

from .constants import (
    CACHE_MARKER_UNCHANGED,
    CONFIG_MARKER_READ_FAILED,
    MAX_INSTALLED_APP_IDS_BYTES,
)
from .gateway import LudusaviGateway
from .matcher import GameRegistryMatcher
from .types import GameStatus
from sdh_ludusavi.game_names import sanitize_game_name

LOGGER = logging.getLogger("sdh_ludusavi.service.registry")


class GameRegistry:
    """Manages cached games, aliases, steam IDs, and handles game status refreshes and matching."""

    def __init__(
        self,
        gateway: LudusaviGateway,
        run_locked: Callable[..., Any],
        log_callback: Callable[..., None],
        save_callback: Callable[[], None],
        get_history_callback: Callable[[], dict[str, dict[str, Any]]],
    ) -> None:
        self._gateway = gateway
        self._run_locked = run_locked
        self.log = log_callback
        self._save_state = save_callback
        self._get_history = get_history_callback

        self._games: dict[str, GameStatus] = {}
        self._aliases: dict[str, str] = {}
        self._ids: dict[str, str] = {}
        self._installed_app_ids: str | None = None
        self._ludusavi_config_mtime_ns: int | None = None

        self._matcher = GameRegistryMatcher()
        self._state_lock = threading.RLock()

    def load_cache(self, cache: dict[str, object]) -> None:
        """Load cached game data and config markers from loaded dictionary."""
        with self._state_lock:
            self._games = {}
            cached_games = cache.get("games", [])
            if isinstance(cached_games, list):
                for g in cached_games:
                    if isinstance(g, dict):
                        try:
                            game = self._coerce_game_status(cast(dict[str, object], g))
                            self._games[game.name] = game
                        except (KeyError, TypeError, ValueError):
                            continue

            raw_aliases = cache.get("aliases", {})
            self._aliases = (
                {str(key): str(value) for key, value in raw_aliases.items()}
                if isinstance(raw_aliases, dict)
                else {}
            )

            raw_ids = cache.get("ids", {})
            self._ids = (
                {str(key): str(value) for key, value in raw_ids.items()}
                if isinstance(raw_ids, dict)
                else {}
            )

            raw_installed_app_ids = cache.get("installed_app_ids")
            self._installed_app_ids = (
                raw_installed_app_ids if isinstance(raw_installed_app_ids, str) else None
            )

            raw_config_mtime_ns = cache.get("ludusavi_config_mtime_ns")
            self._ludusavi_config_mtime_ns = (
                raw_config_mtime_ns if isinstance(raw_config_mtime_ns, int) else None
            )

    def cache_payload(self) -> dict[str, object]:
        """Generate cache payload dictionary for persistence."""
        with self._state_lock:
            return {
                "games": [game.to_dict() for game in self._games.values()],
                "aliases": dict(self._aliases),
                "ids": dict(self._ids),
                "installed_app_ids": self._installed_app_ids,
                "ludusavi_config_mtime_ns": self._ludusavi_config_mtime_ns,
            }

    def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
        """Check if cached data matches the current installed apps and config timestamp."""
        normalized = _normalize_installed_app_ids(installed_app_ids)
        mtime = self._gateway.current_config_mtime_ns()
        with self._state_lock:
            return self._matcher.is_game_cache_current(
                has_games=bool(self._games),
                installed_app_ids=self._installed_app_ids,
                target_installed_app_ids=normalized,
                config_mtime_ns=self._ludusavi_config_mtime_ns,
                target_config_mtime_ns=cast(Any, mtime),
            )

    def refresh_games(
        self, force: bool = False, installed_app_ids: str | None = None
    ) -> dict[str, object]:
        """Refresh statuses from the gateway if needed or requested."""
        normalized_installed_app_ids = _normalize_installed_app_ids(installed_app_ids)
        config_mtime_ns = self._gateway.current_config_mtime_ns()

        if config_mtime_ns is CONFIG_MARKER_READ_FAILED:
            committed_config_mtime_ns = None
        else:
            committed_config_mtime_ns = cast(int | None, config_mtime_ns)

        # Lock-ordering note: the decision reads and cached-payload reads must
        # hold _state_lock because _refresh_statuses_unlocked repopulates these
        # structures under it from coordinator-locked worker threads. The lock
        # is released before _run_locked so it never nests around the
        # coordinator's operation lock.
        with self._state_lock:
            needs_refresh = force or not self._games
            if not force and normalized_installed_app_ids is not None:
                if self._installed_app_ids != normalized_installed_app_ids:
                    needs_refresh = True
                    self.log("debug", "installed_app_ids changed, forcing refresh", "refresh")
            if config_mtime_ns is CONFIG_MARKER_READ_FAILED:
                needs_refresh = True
                self.log("debug", "Ludusavi config marker unavailable, forcing refresh", "refresh")
            if not force and self._ludusavi_config_mtime_ns != committed_config_mtime_ns:
                needs_refresh = True
                self.log("debug", "Ludusavi config changed, forcing refresh", "refresh")
            if not needs_refresh:
                cached_games = self._cached_games()
                cached_aliases = dict(self._aliases)

        if not needs_refresh:
            self.log("debug", "Returning cached game list", "refresh")
            return {
                "games": cached_games,
                "aliases": cached_aliases,
                "history": self._get_history(),
                "dependency_error": None,
            }

        if force:
            self._gateway.invalidate()

        self.log("debug", f"Forcing refresh_games (force={force})", "refresh")
        try:
            games = self._run_locked(
                "refresh",
                None,
                lambda: self._refresh_statuses_unlocked(
                    normalized_installed_app_ids,
                    committed_config_mtime_ns,
                ),
            )
            with self._state_lock:
                aliases = dict(self._aliases)
            return {
                "games": [game.to_dict() for game in games],
                "aliases": aliases,
                "history": self._get_history(),
                "dependency_error": None,
            }
        # Intentionally broad: fallback to cached statuses if refresh fails
        except Exception as exc:
            with self._state_lock:
                fallback_games = self._cached_games()
                fallback_aliases = dict(self._aliases)
            return {
                "games": fallback_games,
                "aliases": fallback_aliases,
                "history": self._get_history(),
                "dependency_error": str(exc),
            }

    def match_game(self, game_name: str, app_id: str | None = None) -> GameStatus | None:
        """Find a game status matching the query using matching rules and lazy-refresh."""
        game_name = sanitize_game_name(game_name)
        with self._state_lock:
            return self._matcher.match_game(
                game_name=game_name,
                app_id=app_id,
                games=self._games,
                aliases=self._aliases,
                ids=self._ids,
                log_callback=lambda level, msg: self.log(level, msg),
                refresh_callback=lambda: self._run_locked(
                    "refresh", None, self._refresh_statuses_unlocked
                ),
            )

    def refresh_after_operation(self, game_name: str | None = None) -> None:
        """Best-effort status refresh after a successful backup or restore."""
        try:
            self._refresh_statuses_unlocked(game_name=game_name)
        # Intentionally broad: catch any post-operation status refresh failure safely
        except Exception as exc:
            self.log("warning", f"Post-operation status refresh failed: {exc}", "refresh")

    def _refresh_statuses_unlocked(
        self,
        installed_app_ids: str | None | object = CACHE_MARKER_UNCHANGED,
        ludusavi_config_mtime_ns: int | None | object = CACHE_MARKER_UNCHANGED,
        game_name: str | None = None,
    ) -> list[GameStatus]:
        if game_name:
            raw_statuses = self._gateway.get_adapter().refresh_statuses(game_names=[game_name])
        else:
            raw_statuses = self._gateway.get_adapter().refresh_statuses()
        self.log(
            "debug", f"Retrieved {len(raw_statuses)} raw game statuses from Ludusavi", "refresh"
        )

        games = []
        for raw_game in raw_statuses:
            try:
                if not isinstance(raw_game, Mapping):
                    raise TypeError(
                        f"status entry must be a mapping, got {type(raw_game).__name__}"
                    )
                game = self._coerce_game_status(dict(raw_game))
                games.append(game)
            except (KeyError, TypeError, ValueError) as exc:
                raw_name = raw_game.get("name") if isinstance(raw_game, Mapping) else "<unknown>"
                self.log("error", f"Failed to parse status for game {raw_name}: {exc}", "refresh")

        with self._state_lock:
            if not game_name and not (
                isinstance(ludusavi_config_mtime_ns, int)
                and self._ludusavi_config_mtime_ns == ludusavi_config_mtime_ns
            ):
                adapter = self._gateway.get_adapter()
                new_aliases = getattr(adapter, "get_aliases", lambda: {})()
                self._aliases.clear()
                self._aliases.update(new_aliases)

            if game_name:
                # --- Targeted Merge Mode ---
                if not games:
                    self.log(
                        "warning",
                        f"Targeted refresh for '{game_name}' returned no results; cache unchanged",
                        "refresh",
                    )
                else:
                    for game in games:
                        # Remove old steam ID association before inserting new one
                        old_game = self._games.get(game.name)
                        if old_game and old_game.steam_id and old_game.steam_id in self._ids:
                            del self._ids[old_game.steam_id]

                        self._games[game.name] = game
                        if game.steam_id:
                            self._ids[game.steam_id] = game.name
            else:
                # --- Bulk Replacement Mode ---
                self._games.clear()
                self._games.update({game.name: game for game in games})

                self._ids.clear()
                self._ids.update({game.steam_id: game.name for game in games if game.steam_id})

                if installed_app_ids is not CACHE_MARKER_UNCHANGED:
                    self._installed_app_ids = cast(str | None, installed_app_ids)
                if ludusavi_config_mtime_ns is not CACHE_MARKER_UNCHANGED:
                    self._ludusavi_config_mtime_ns = cast(int | None, ludusavi_config_mtime_ns)

        self.log("info", f"Refreshed {len(games)} Ludusavi games", "refresh")
        self._save_state()
        return games

    def _coerce_game_status(self, data: dict[str, object]) -> GameStatus:
        self.log("debug", f"Coercing status for '{data.get('name')}'", "refresh")
        error = data.get("error")
        return GameStatus(
            name=str(data["name"]),
            configured=bool(data.get("configured", True)),
            has_backup=bool(data.get("has_backup", False)),
            needs_first_backup=bool(data.get("needs_first_backup", False)),
            steam_id=str(data.get("steam_id")) if data.get("steam_id") else None,
            error=str(error) if error else None,
        )

    def _cached_games(self) -> list[dict[str, object]]:
        with self._state_lock:
            return [game.to_dict() for game in self._games.values()]


def _normalize_installed_app_ids(raw: str | None) -> str | None:
    if raw is None:
        return None
    if len(raw) > MAX_INSTALLED_APP_IDS_BYTES:
        return None
    if not raw.strip():
        return ""
    tokens = raw.split(",")
    if any(not token.isdecimal() for token in tokens):
        return None
    app_ids = sorted({int(token) for token in tokens})
    return ",".join(str(app_id) for app_id in app_ids)
