from __future__ import annotations

import re
from typing import Callable
from .service import GameStatus


class GameRegistryMatcher:
    """Contains logic for normalizing game names, executing exact, alias, or

    fuzzy matching queries, and verifying game cache freshness.
    """

    def normalize(self, game_name: str) -> str:
        """Normalize a game name for easier matching."""
        # Retain dots and hyphens for better precision in non-steam titles
        return re.sub(r"[^a-z0-9.-]+", " ", game_name.casefold()).strip()

    def fuzzy_match_allowed(
        self, normalized_input: str, normalized_target: str, configured: bool
    ) -> bool:
        """Verify if a fuzzy substring match is allowed based on length/configuration constraints."""
        if len(normalized_input) > 4 and len(normalized_target) > 4:
            return True
        if not configured:
            return False
        if len(normalized_target) != 4:
            return False
        if not normalized_input.startswith(normalized_target):
            return False
        if len(normalized_input) == len(normalized_target):
            return True
        return normalized_input[len(normalized_target)] in {" ", ".", "-"}

    def match_game(
        self,
        game_name: str,
        app_id: str | None,
        games: dict[str, GameStatus],
        aliases: dict[str, str],
        ids: dict[str, str],
        log_callback: Callable[[str, str], None] | None = None,
        refresh_callback: Callable[[], None] | None = None,
    ) -> GameStatus | None:
        """Attempt to match a game name or Steam ID to an entry in the game list."""

        def log(level: str, msg: str) -> None:
            if log_callback:
                log_callback(level, msg)

        log("debug", f"Attempting to match '{game_name}' (app_id: {app_id})")

        if not games and refresh_callback:
            log("debug", f"match_game triggering refresh for {game_name}")
            refresh_callback()

        # 1. Match by Steam ID (Highest Priority)
        if app_id and app_id in ids:
            target = ids[app_id]
            game = games.get(target)
            if game:
                log("info", f"Matched '{game_name}' via Steam ID '{app_id}' to '{game.name}'")
                return game
            log("debug", f"AppID '{app_id}' found in IDs map but game '{target}' not in games map")

        # 2. Match by Alias
        if game_name in aliases:
            target = aliases[game_name]
            game = games.get(target)
            if game:
                log("info", f"Matched '{game_name}' via Ludusavi alias to '{game.name}'")
                return game
            log("debug", f"Alias '{game_name}' found for '{target}' but game not in games map")

        # 3. Match by Normalized Name (Exact)
        normalized_input = self.normalize(game_name)
        log("debug", f"Checking exact normalized match for '{normalized_input}'")
        for game in games.values():
            if self.normalize(game.name) == normalized_input:
                log("info", f"Matched '{game_name}' via exact normalized name to '{game.name}'")
                return game

        # 4. Fuzzy Match (Substring)
        log("debug", f"Checking fuzzy substring match for '{normalized_input}'")
        for game in games.values():
            normalized_target = self.normalize(game.name)
            if normalized_input in normalized_target or normalized_target in normalized_input:
                if self.fuzzy_match_allowed(normalized_input, normalized_target, game.configured):
                    log("info", f"Matched '{game_name}' via fuzzy substring to '{game.name}'")
                    return game

        log(
            "info",
            f"Could not match game '{game_name}' (app_id: {app_id}, normalized: '{normalized_input}')",
        )
        return None

    def is_game_cache_current(
        self,
        has_games: bool,
        installed_app_ids: str | None,
        target_installed_app_ids: str | None,
        config_mtime_ns: int | None,
        target_config_mtime_ns: int | None,
    ) -> bool:
        """Check if the cache has game records and matches the installed ID set and config mtime."""
        if not has_games:
            return False

        if target_installed_app_ids is not None and installed_app_ids != target_installed_app_ids:
            return False

        from .service import _CONFIG_MARKER_READ_FAILED

        if target_config_mtime_ns is _CONFIG_MARKER_READ_FAILED:
            return False

        return config_mtime_ns == target_config_mtime_ns
