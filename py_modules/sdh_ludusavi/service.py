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
from typing import Any, Protocol, cast

from ._version import resolve_version

LOGGER = logging.getLogger(__name__)


class OperationLockedError(RuntimeError):
    """Raised when a global Ludusavi operation is already running."""


class DeckyLogHandler(logging.Handler):
    """
    A logging handler that routes standard Python logs into the plugin's
    internal LogModal buffer and the Decky Loader logger.
    """

    def __init__(self, service: SDHLudusaviService) -> None:
        super().__init__()
        self._service = service

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # Map Python levels to our LogModal levels
            level = record.levelname.lower()
            log_modal_map = {
                "warning": "warning",
                "error": "error",
                "critical": "error",
                "debug": "debug",
                "info": "info",
            }
            level = log_modal_map.get(level, "info")

            # Push to LogModal buffer
            self._service._push_log_record(level, msg)

            # Also push to decky.logger if available
            _decky_log(level, msg)
        except Exception:
            self.handleError(record)


def _decky_log(level: str, message: str) -> None:
    """Helper to log to decky.logger if available."""
    try:
        import decky

        logger = getattr(decky, "logger", None)
        if logger:
            logger_level_map = {
                "warning": logger.warning,
                "error": logger.error,
                "debug": logger.info,  # Decky doesn't have a debug level, so route it to info with a prefix
                "info": logger.info,
            }
            logger_level = logger_level_map.get(level, logger.info)
            # Prefix with [DEBUG] because Decky UI usually filters info only
            logger_level(f"[DEBUG] {message}" if level == "debug" else message)
    except (ImportError, AttributeError):
        pass


class LudusaviAdapter(Protocol):
    def refresh_statuses(self) -> list[dict[str, object]]: ...

    def compare_recency(self, game_name: str) -> str: ...

    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]: ...

    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]: ...

    def get_versions(self) -> dict[str, str]: ...

    def get_log_contents(self) -> str: ...


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
        log_limit: int = 100,
    ) -> None:
        if adapter is not None and adapter_factory is not None:
            raise ValueError("adapter and adapter_factory cannot both be provided")

        self._adapter = adapter
        self._adapter_factory = adapter_factory or _default_adapter_factory
        self._state_path = state_path or Path("/tmp/sdh_ludusavi/state.json")
        self._auto_sync_enabled = False
        self._selected_game = ""
        self._ludusavi_launcher_shortcut_id = -1
        self._games: dict[str, GameStatus] = {}
        self._aliases: dict[str, str] = {}
        self._ids: dict[str, str] = {}
        self._versions: dict[str, str] | None = None
        self._operation = OperationState()
        self._operation_lock = threading.Lock()
        self._logs: deque[LogEntry] = deque(maxlen=log_limit)
        self._refreshed_once = False
        self._setup_logging()
        self._load_state()
        self.log("info", "SDH-ludusavi service initialized", "init")

        import getpass

        identity = f"uid={os.getuid()}, euid={os.geteuid()}, user={getpass.getuser()}"
        self.log("debug", f"Process identity: {identity}", "init")

        # Log relevant environment variables at DEBUG level for troubleshooting.
        _relevant_keys = {
            "PATH",
            "HOME",
            "USER",
            "LOGNAME",
            "SHELL",
            "LANG",
            "LD_LIBRARY_PATH",
            "XDG_DATA_DIRS",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
        }
        _filtered_env = {
            k: v
            for k, v in os.environ.items()
            if k in _relevant_keys or k.startswith(("DECKY_", "FLATPAK_"))
        }
        self.log("debug", f"Filtered environment variables: {_filtered_env}", "init")

    def _setup_logging(self) -> None:
        """Configure the standard logging library to route through our handler."""
        handler = DeckyLogHandler(self)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))

        # Attach to our own package and pyludusavi
        for name in ("sdh_ludusavi", "pyludusavi"):
            logger = logging.getLogger(name)
            logger.setLevel(logging.DEBUG)
            # Remove existing handlers to avoid duplicates on reload
            has_our_handler = False
            for h in logger.handlers[:]:
                if isinstance(h, DeckyLogHandler):
                    has_our_handler = True
                    continue
                logger.removeHandler(h)

            if not has_our_handler:
                logger.addHandler(handler)

            # Disable propagation in Decky Loader to avoid double-logging,
            # as our DeckyLogHandler already routes to decky.logger.
            # Keep it enabled in other environments (e.g. tests) for capture.
            logger.propagate = not bool(os.environ.get("DECKY_VERSION"))

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

    def get_ludusavi_launcher_shortcut_id(self) -> int:
        """Return the saved shortcut app ID, or -1 if none exists."""
        return self._ludusavi_launcher_shortcut_id

    def set_ludusavi_launcher_shortcut_id(self, app_id: int) -> bool:
        """Persist the shortcut app ID."""
        self._ludusavi_launcher_shortcut_id = int(app_id)
        self._save_state()
        self.log("info", f"Saved Ludusavi launcher shortcut ID: {app_id}")
        return True

    def clear_ludusavi_launcher_shortcut_id(self) -> bool:
        """Remove the saved shortcut app ID from config."""
        self._ludusavi_launcher_shortcut_id = -1
        self._save_state()
        self.log("info", "Cleared Ludusavi launcher shortcut ID")
        return True

    def get_ludusavi_command(self) -> dict[str, object] | None:
        """
        Return the command path and args used by the plugin for GUI launching.
        Returns None if Ludusavi is not found.
        """
        try:
            from pyludusavi.discovery import find_ludusavi

            # Use the same parameters as PyludusaviAdapter
            from .ludusavi import FLATPAK_ID, _decky_user, _decky_user_home

            user_home = _decky_user_home()
            user = _decky_user()

            # find_ludusavi returns a list[str] like ["/usr/bin/flatpak", "run", ...]
            # or just ["/usr/bin/ludusavi"]
            prefix = find_ludusavi(
                flatpak_id=FLATPAK_ID, flatpak_user_home=user_home, flatpak_user=user
            )

            if not prefix:
                return None

            return {
                "commandPath": prefix[0],
                "args": prefix[1:],
                "compatTool": "",  # Standard launcher doesn't need compat tool for native/flatpak
            }
        except Exception as exc:
            self.log("error", f"Failed to discover Ludusavi command: {exc}")
            return None

    def refresh_games(self, force: bool = False) -> dict[str, object]:
        """
        Refresh the list of games and their backup status from Ludusavi.

        If force is False, returns the cached game list if available.
        """
        if not force and self._refreshed_once and self._games:
            self.log("debug", "Returning cached game list", "refresh")
            return {
                "games": self._cached_games(),
                "aliases": self._aliases,
                "dependency_error": None,
            }

        self.log("debug", f"Forcing refresh_games (force={force})", "refresh")
        try:
            games = self._run_locked("refresh", None, self._refresh_statuses_unlocked)
            return {
                "games": [game.to_dict() for game in games],
                "aliases": self._aliases,
                "dependency_error": None,
            }
        except (
            Exception
        ) as exc:  # pragma: no cover - concrete exception types come from pyludusavi.
            message = str(exc)
            return {
                "games": self._cached_games(),
                "aliases": self._aliases,
                "dependency_error": message,
            }

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

        if game.error:
            self.log(
                "info", f"Skipping: game has a reported error: {game.error}", "start", game.name
            )
            return self._skip("start", game.name, "game_error")

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

        if game.error:
            self.log(
                "info", f"Skipping: game has a reported error: {game.error}", "exit", game.name
            )
            return self._skip("exit", game.name, "game_error")

        self.log("debug", f"Checking if backup is needed for {game.name}", "exit", game.name)
        try:
            preview = self._ludusavi().backup(game.name, preview=True)
            games_output = cast(dict[str, Any], preview.get("games", {}))

            if game.name not in games_output:
                self.log(
                    "info",
                    "Skipping: game not found in backup preview (nothing to back up)",
                    "exit",
                    game.name,
                )
                return self._skip("exit", game.name, "not_in_preview")

            game_output = cast(dict[str, Any], games_output.get(game.name, {}))

            # Check if Ludusavi decided to skip this game (e.g., it is deselected in the UI).
            decision = game_output.get("decision")
            if decision in ("Ignored", "Cancelled"):
                self.log(
                    "info",
                    f"Skipping: game marked as {decision} in Ludusavi",
                    "exit",
                    game.name,
                )
                return self._skip("exit", game.name, "not_processed")

            # Check if Ludusavi found anything to back up.
            # Some games might be listed but have no files/registry entries found.
            files = game_output.get("files", {})
            registry = game_output.get("registry", {})
            if not files and not registry:
                self.log(
                    "info",
                    "Skipping: no files or registry entries found to back up",
                    "exit",
                    game.name,
                )
                return self._skip("exit", game.name, "no_files_found")

            change = game_output.get("change")
            self.log("debug", f"Backup preview result for {game.name}: {change}", "exit", game.name)

            if change == "Same":
                return self._skip("exit", game.name, "local_current")
        except Exception as exc:
            self.log("debug", f"Backup preview failed for {game.name}: {exc}", "exit", game.name)
            # If preview fails, we skip to avoid potentially invalid or redundant backup attempts.
            return self._skip("exit", game.name, "preview_failed")

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

        # Ensure pyludusavi is in the version map if not already provided by adapter
        if "pyludusavi" not in versions:
            try:
                import pyludusavi

                versions["pyludusavi"] = getattr(pyludusavi, "__version__", "unknown")
            except ImportError:
                versions["pyludusavi"] = "unknown"

        self._versions = versions
        return versions

    def get_ludusavi_logs(self) -> str:
        """
        Read and return the contents of the Ludusavi log file.
        """
        return self._ludusavi().get_log_contents()

    def get_operation_status(self) -> dict[str, object]:
        """Return information about the currently running or last completed operation."""
        return self._operation.to_dict()

    def get_recent_logs(self) -> list[dict[str, object]]:
        """Return the most recent log entries from the ring buffer in chronological order."""
        return [entry.to_dict() for entry in self._logs]

    def _load_state(self) -> None:
        """Load the plugin settings and game cache from the persistent state file."""
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
        self._ludusavi_launcher_shortcut_id = int(data.get("ludusaviLauncherShortcutAppId", -1))

        # Load cached games
        cached_games = data.get("games", [])
        if isinstance(cached_games, list):
            self._games = {}
            for g in cached_games:
                try:
                    game = self._coerce_game_status(g)
                    self._games[game.name] = game
                except Exception:
                    continue

        # Load cached aliases and IDs
        self._aliases = data.get("aliases", {})
        self._ids = data.get("ids", {})

        self.log(
            "debug",
            f"Loaded state: auto_sync_enabled={self._auto_sync_enabled}, selected_game={self._selected_game}, {len(self._games)} games cached",
        )

    def _save_state(self) -> None:
        """Persist the current plugin settings and game cache to the state file."""
        self._state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temp_path = self._state_path.with_name(f".{self._state_path.name}.tmp")

        data = self.get_settings()
        data["ludusaviLauncherShortcutAppId"] = self._ludusavi_launcher_shortcut_id
        data["games"] = [game.to_dict() for game in self._games.values()]
        data["aliases"] = self._aliases
        data["ids"] = self._ids

        try:
            temp_path.write_text(
                json.dumps(data, indent=2, sort_keys=True),
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
        self._refreshed_once = True
        self.log(
            "info",
            f"Refreshed {len(games)} Ludusavi games ({len(self._aliases)} aliases, {len(self._ids)} Steam IDs)",
            "refresh",
        )
        self._save_state()
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
        if not self._refreshed_once or not self._games:
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
                if len(normalized_input) > 4 and len(normalized_target) > 4:
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
        """
        Add an entry to the internal diagnostic log buffer.

        This method is primarily used by the frontend via RPC.
        """
        # If it's from the frontend, we still want it in the Decky log
        log_msg = f"{operation or 'frontend'}: {message}"
        if game_name:
            log_msg = f"[{game_name}] {log_msg}"

        _decky_log(level, log_msg)
        self._push_log_record(level, message, operation, game_name)

    def _push_log_record(
        self,
        level: str,
        message: str,
        operation: str | None = None,
        game_name: str | None = None,
    ) -> None:
        """Internal helper to push a record into the ring buffer."""
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
