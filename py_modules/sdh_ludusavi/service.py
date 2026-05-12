from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime
from collections.abc import Callable
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from ._version import resolve_version

LOGGER = logging.getLogger(__name__)


class OperationLockedError(RuntimeError):
    """Raised when a global Ludusavi operation is already running."""


class LudusaviAdapter(Protocol):
    def refresh_statuses(self) -> list[dict[str, object]]: ...

    def compare_recency(self, game_name: str) -> str: ...

    def backup(self, game_name: str) -> dict[str, object]: ...

    def restore(self, game_name: str) -> dict[str, object]: ...

    def get_versions(self) -> dict[str, str]: ...


@dataclass
class GameStatus:
    """Represents the parsed Ludusavi status for a single game."""

    name: str
    configured: bool
    has_backup: bool
    needs_first_backup: bool
    steam_id: str | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.has_backup:
            return "has_backup"
        if self.needs_first_backup:
            return "needs_first_backup"
        return "configured" if self.configured else "error"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status
        return data


@dataclass
class OperationState:
    """Tracks the current active or last completed backend operation."""

    is_running: bool = False
    name: str | None = None
    game_name: str | None = None
    last_result: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class LogEntry:
    """A single diagnostic log entry held in the backend ring buffer."""

    level: str
    message: str
    timestamp: str
    operation: str | None = None
    game_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SDHLudusaviService:
    """
    The core synchronous backend service for SDH-ludusavi.

    This service orchestrates all Ludusavi operations (backups, restores, statuses),
    manages the internal game list cache, handles the plugin's configuration state,
    and enforces a thread lock to ensure only one Ludusavi subprocess runs at a time.
    """

    def __init__(
        self,
        adapter: LudusaviAdapter | None = None,
        adapter_factory: Callable[[], LudusaviAdapter] | None = None,
        state_path: Path | None = None,
        log_limit: int = 50,
    ) -> None:
        if adapter is not None and adapter_factory is not None:
            raise ValueError("adapter and adapter_factory cannot both be provided")

        self._adapter = adapter
        self._adapter_factory = adapter_factory or _default_adapter_factory
        self._state_path = state_path or Path("/tmp/sdh_ludusavi/state.json")
        self._auto_sync_enabled = False
        self._selected_game = ""
        self._games: dict[str, GameStatus] = {}
        self._aliases: dict[str, str] = {}
        self._ids: dict[str, str] = {}
        self._versions: dict[str, str] | None = None
        self._operation = OperationState()
        self._operation_lock = threading.Lock()
        self._logs: deque[LogEntry] = deque(maxlen=log_limit)
        self._load_state()

    def get_settings(self) -> dict[str, Any]:
        """Return the current plugin settings."""
        return {
            "auto_sync_enabled": self._auto_sync_enabled,
            "selected_game": self._selected_game,
        }

    def set_auto_sync_enabled(self, enabled: bool) -> dict[str, Any]:
        """Update the automatic sync setting and persist it to disk."""
        self._auto_sync_enabled = bool(enabled)
        self._save_state()
        self.log("info", f"Automatic sync {'enabled' if enabled else 'disabled'}")
        return self.get_settings()

    def set_selected_game(self, game_name: str) -> dict[str, Any]:
        """Update the currently selected game and persist it to disk."""
        self._selected_game = str(game_name)
        self._save_state()
        self.log("debug", f"Selected game changed to {game_name}")
        return self.get_settings()

    def refresh_games(self, force: bool = False) -> dict[str, object]:
        """
        Refresh the list of games and their backup status from Ludusavi.

        If force is False, returns the cached game list if available.
        """
        if not force and self._games:
            self.log("debug", "Returning cached game list", "refresh")
            return {"games": self._cached_games(), "dependency_error": None}

        self.log("debug", f"Forcing refresh_games (force={force})", "refresh")
        try:
            games = self._run_locked("refresh", None, self._refresh_statuses_unlocked)
        except (
            Exception
        ) as exc:  # pragma: no cover - concrete exception types come from pyludusavi.
            message = str(exc)
            return {"games": self._cached_games(), "dependency_error": message}

        return {"games": [game.to_dict() for game in games], "dependency_error": None}

    def handle_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """
        Logic triggered when a game is launched in Steam.

        Checks if a restore is needed based on backup recency.
        """
        self.log(
            "info",
            f"handle_game_start triggered for game='{game_name}', app_id='{app_id}'",
            "start",
            game_name,
        )
        if not self._auto_sync_enabled:
            self.log("info", "Skipping: auto_sync_enabled is False", "start", game_name)
            return self._skip("start", game_name, "auto_sync_disabled")
        if self._operation.is_running:
            self.log(
                "info",
                f"Skipping: another operation is running ({self._operation.name})",
                "start",
                game_name,
            )
            return self._skip("start", game_name, "operation_running")

        game = self._match_game(game_name, app_id=app_id)
        if game is None:
            self.log(
                "info",
                f"Skipping: game not found in Ludusavi list (app_id: {app_id})",
                "start",
                game_name,
            )
            return self._skip("start", game_name, "unmatched_game")
        if not game.has_backup:
            self.log("info", "Skipping: game has no existing backup", "start", game.name)
            return self._skip("start", game.name, "no_backup")

        self.log("debug", f"Checking recency for {game.name}", "start", game.name)
        recency = self._ludusavi().compare_recency(game.name)
        self.log("info", f"Recency check result for {game.name}: {recency}", "start", game.name)

        if recency == "backup_newer":
            result = self._run_locked(
                "restore",
                game.name,
                lambda: self._ludusavi().restore(game.name),
            )
            self.log("info", f"Restored {game.name} before launch", "restore", game.name)
            return {"status": "restored", "game": game.name, "result": result}
        if recency == "local_current":
            return self._skip("start", game.name, "local_current")
        return self._skip("start", game.name, "ambiguous_recency")

    def handle_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """
        Logic triggered when a game is closed in Steam.

        Triggers an automatic backup if enabled.
        """
        self.log(
            "info",
            f"handle_game_exit triggered for game='{game_name}', app_id='{app_id}'",
            "exit",
            game_name,
        )
        if not self._auto_sync_enabled:
            self.log("info", "Skipping: auto_sync_enabled is False", "exit", game_name)
            return self._skip("exit", game_name, "auto_sync_disabled")
        if self._operation.is_running:
            self.log(
                "info",
                f"Skipping: another operation is running ({self._operation.name})",
                "exit",
                game_name,
            )
            return self._skip("exit", game_name, "operation_running")

        game = self._match_game(game_name, app_id=app_id)
        if game is None:
            self.log(
                "info",
                f"Skipping: game not found in Ludusavi list (app_id: {app_id})",
                "exit",
                game_name,
            )
            return self._skip("exit", game_name, "unmatched_game")

        result = self._run_locked("backup", game.name, lambda: self._ludusavi().backup(game.name))
        self._refresh_statuses_unlocked()
        self.log("info", f"Backed up {game.name} after exit", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_backup(self, game_name: str) -> dict[str, object]:
        """Trigger a manual backup for the specified game."""
        game = self._match_game(game_name)
        if game is None:
            self.log("debug", "Skipping: game not found in Ludusavi list", "backup", game_name)
            return self._skip("backup", game_name, "unmatched_game")

        result = self._run_locked("backup", game.name, lambda: self._ludusavi().backup(game.name))
        self._refresh_statuses_unlocked()
        self.log("info", f"Backed up {game.name}", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_restore(self, game_name: str) -> dict[str, object]:
        """Trigger a manual restore for the specified game."""
        game = self._match_game(game_name)
        if game is None:
            self.log("debug", "Skipping: game not found in Ludusavi list", "restore", game_name)
            return self._skip("restore", game_name, "unmatched_game")
        if not game.has_backup:
            self.log("debug", "Skipping: game has no backup to restore", "restore", game.name)
            return self._skip("restore", game.name, "no_backup")

        result = self._run_locked("restore", game.name, lambda: self._ludusavi().restore(game.name))
        self.log("info", f"Restored {game.name}", "restore", game.name)
        return {"status": "restored", "game": game.name, "result": result}

    def get_versions(self) -> dict[str, str]:
        """
        Fetch version information for Ludusavi and the plugin itself.

        Results are cached in memory for the duration of the session.
        """
        if self._versions is not None:
            self.log("debug", "Returning cached version list", "versions")
            return self._versions

        self.log("debug", "Fetching version list", "versions")
        versions = dict(self._run_locked("versions", None, lambda: self._ludusavi().get_versions()))
        versions["sdh_ludusavi"] = resolve_version()
        self._versions = versions
        return versions

    def get_operation_status(self) -> dict[str, object]:
        """Return information about the currently running or last completed operation."""
        return self._operation.to_dict()

    def get_recent_logs(self) -> list[dict[str, object]]:
        """Return the most recent log entries from the ring buffer in chronological order."""
        return [entry.to_dict() for entry in self._logs]

    def _load_state(self) -> None:
        """Load the plugin settings from the persistent state file."""
        if not self._state_path.exists():
            return
        try:
            raw_state = self._state_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._warn_state_load(f"unreadable state file: {exc}")
            return
        if not raw_state.strip():
            self._warn_state_load("empty state file")
            return
        try:
            data = json.loads(raw_state)
        except json.JSONDecodeError as exc:
            self._warn_state_load(f"invalid JSON: {exc}")
            return
        if not isinstance(data, dict):
            self._warn_state_load("state file must contain a JSON object")
            return
        self._auto_sync_enabled = bool(data.get("auto_sync_enabled", False))
        self._selected_game = str(data.get("selected_game", ""))
        self.log(
            "debug",
            f"Loaded state: auto_sync_enabled={self._auto_sync_enabled}, selected_game={self._selected_game}",
        )

    def _save_state(self) -> None:
        """Persist the current plugin settings to the state file."""
        self._state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temp_path = self._state_path.with_name(f".{self._state_path.name}.tmp")
        try:
            temp_path.write_text(
                json.dumps(self.get_settings(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self._state_path)
            self.log("debug", f"Saved state to {self._state_path}")
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    def _refresh_statuses_unlocked(self) -> list[GameStatus]:
        """
        Internal implementation of status refresh, executed within
        the operation lock.
        """
        raw_statuses = self._ludusavi().refresh_statuses()
        self.log(
            "debug", f"Retrieved {len(raw_statuses)} raw game statuses from Ludusavi", "refresh"
        )

        games = []
        for raw_game in raw_statuses:
            try:
                game = self._coerce_game_status(raw_game)
                games.append(game)
            except Exception as exc:
                self.log(
                    "error",
                    f"Failed to parse status for game {raw_game.get('name')}: {exc}",
                    "refresh",
                )

        self._games = {game.name: game for game in games}
        self._aliases = getattr(self._ludusavi(), "get_aliases", lambda: {})()
        self._ids = {game.steam_id: game.name for game in games if game.steam_id}
        self.log(
            "info",
            f"Refreshed {len(games)} Ludusavi games ({len(self._aliases)} aliases, {len(self._ids)} Steam IDs)",
            "refresh",
        )
        return games

    def _coerce_game_status(self, data: dict[str, object]) -> GameStatus:
        """Parse raw Ludusavi JSON output into a GameStatus object."""
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
        return [game.to_dict() for game in self._games.values()]

    def _match_game(self, game_name: str, app_id: str | None = None) -> GameStatus | None:
        """
        Attempt to match a Steam game name or ID to an entry in the Ludusavi
        game list, with fallback to aliases and fuzzy matching.
        """
        self.log("debug", f"Attempting to match '{game_name}' (app_id: {app_id})")
        if not self._games:
            self.log("debug", f"_match_game triggering refresh for {game_name}", "refresh")
            self._refresh_statuses_unlocked()

        # 1. Match by Steam ID (Highest Priority)
        if app_id and app_id in self._ids:
            target = self._ids[app_id]
            game = self._games.get(target)
            if game:
                self.log("info", f"Matched '{game_name}' via Steam ID '{app_id}' to '{game.name}'")
                return game
            self.log(
                "debug", f"AppID '{app_id}' found in IDs map but game '{target}' not in games map"
            )

        # 2. Match by Alias
        if game_name in self._aliases:
            target = self._aliases[game_name]
            game = self._games.get(target)
            if game:
                self.log("info", f"Matched '{game_name}' via Ludusavi alias to '{game.name}'")
                return game
            self.log("debug", f"Alias '{game_name}' found for '{target}' but game not in games map")

        # 3. Match by Normalized Name (Exact)
        normalized_input = _normalize(game_name)
        self.log("debug", f"Checking exact normalized match for '{normalized_input}'")
        for game in self._games.values():
            if _normalize(game.name) == normalized_input:
                self.log(
                    "info", f"Matched '{game_name}' via exact normalized name to '{game.name}'"
                )
                return game

        # 4. Fuzzy Match (Substring)
        self.log("debug", f"Checking fuzzy substring match for '{normalized_input}'")
        for game in self._games.values():
            normalized_target = _normalize(game.name)
            if normalized_input in normalized_target or normalized_target in normalized_input:
                # Minimum length check to avoid matching e.g. "A" to every game with "A"
                if len(normalized_input) > 4 or len(normalized_target) > 4:
                    self.log("info", f"Matched '{game_name}' via fuzzy substring to '{game.name}'")
                    return game

        self.log(
            "info",
            f"Could not match game '{game_name}' (app_id: {app_id}, normalized: '{normalized_input}')",
        )
        return None

    def _run_locked(self, operation: str, game_name: str | None, callback: Any) -> Any:
        """
        Execute a callback while holding the operation lock, ensuring
        exclusive access to Ludusavi.
        """
        if self._operation.is_running or not self._operation_lock.acquire(blocking=False):
            raise OperationLockedError(f"{self._operation.name or 'operation'} is already running")

        self.log("info", f"Starting {operation}", operation, game_name)
        self._operation.is_running = True
        self._operation.name = operation
        self._operation.game_name = game_name
        self._operation.last_error = None
        try:
            result = callback()
        except Exception as exc:
            self._operation.last_error = str(exc)
            self._operation.last_result = "failed"
            self.log("error", f"{operation} failed: {exc}", operation, game_name)
            raise
        else:
            self._operation.last_result = "ok"
            return result
        finally:
            self._operation.is_running = False
            self._operation.name = None
            self._operation.game_name = None
            self._operation_lock.release()

    def _skip(self, operation: str, game_name: str, reason: str) -> dict[str, object]:
        """Record a skipped operation status."""
        self.log("info", f"Skipped {operation} for {game_name}: {reason}", operation, game_name)
        return {"status": "skipped", "game": game_name, "reason": reason}

    def log(
        self,
        level: str,
        message: str,
        operation: str | None = None,
        game_name: str | None = None,
    ) -> None:
        """Add an entry to the internal diagnostic log buffer."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._logs.append(LogEntry(level, message, timestamp, operation, game_name))

    def _warn_state_load(self, reason: str) -> None:
        """Log a warning about a failed state load."""
        LOGGER.warning("Ignoring SDH-ludusavi state at %s: %s", self._state_path, reason)

    def _ludusavi(self) -> LudusaviAdapter:
        """Lazy initializer for the Ludusavi adapter."""
        if self._adapter is None:
            self._adapter = self._adapter_factory()
        return self._adapter


def _normalize(game_name: str) -> str:
    """Normalize a game name for easier matching."""
    # Retain dots and hyphens for better precision in non-steam titles
    return re.sub(r"[^a-z0-9.-]+", " ", game_name.casefold()).strip()


def _default_adapter_factory() -> LudusaviAdapter:
    """The default factory for creating a Ludusavi adapter."""
    from .ludusavi import PyludusaviAdapter

    return PyludusaviAdapter()
