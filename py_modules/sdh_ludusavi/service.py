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
MAX_INSTALLED_APP_IDS_BYTES = 16_384
_CONFIG_MARKER_READ_FAILED = object()
_CACHE_MARKER_UNCHANGED = object()

try:
    import decky

    _DECKY_LOGGER = getattr(decky, "logger", None)
except (ImportError, AttributeError):
    _DECKY_LOGGER = None


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
    if not _DECKY_LOGGER:
        return

    logger_level_map = {
        "warning": _DECKY_LOGGER.warning,
        "error": _DECKY_LOGGER.error,
        "debug": _DECKY_LOGGER.info,  # Decky doesn't have a debug level.
        "info": _DECKY_LOGGER.info,
    }
    logger_level = logger_level_map.get(level, _DECKY_LOGGER.info)
    logger_level(f"[DEBUG] {message}" if level == "debug" else message)


class LudusaviAdapter(Protocol):
    def refresh_statuses(self) -> list[dict[str, object]]: ...

    def compare_recency(self, game_name: str) -> str: ...

    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]: ...

    def restore(self, game_name: str, preview: bool = False) -> dict[str, object]: ...

    def get_versions(self) -> dict[str, str]: ...

    def get_log_contents(self) -> str: ...

    def get_config_mtime_ns(self) -> int | None: ...


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
        self._adapter_lock = threading.Lock()
        self._adapter_factory = adapter_factory or _default_adapter_factory
        self._state_path = state_path or Path("/tmp/sdh_ludusavi/state.json")
        self._auto_sync_enabled = False
        self._selected_game = ""
        self._ludusavi_launcher_shortcut_id = -1
        self._games: dict[str, GameStatus] = {}
        self._aliases: dict[str, str] = {}
        self._ids: dict[str, str] = {}
        self._versions: dict[str, str] | None = None
        self._installed_app_ids: str | None = None
        self._ludusavi_config_mtime_ns: int | None = None
        self._game_history: dict[str, dict[str, Any]] = {}
        self._operation = OperationState()
        self._operation_lock = threading.Lock()
        self._logs: deque[LogEntry] = deque(maxlen=log_limit)
        self._setup_logging()
        self._load_state()
        self.log("info", "SDH-ludusavi service initialized", "init")

        import getpass

        identity = f"uid={os.getuid()}, euid={os.geteuid()}, user={getpass.getuser()}"
        self.log("debug", f"Process identity: {identity}", "init")

        # Log relevant environment variables at DEBUG level for troubleshooting.
        _allowed_env_keys = {
            "LANG",
            "DECKY_VERSION",
            "DECKY_PLUGIN_RUNTIME_DIR",
            "DECKY_PLUGIN_SETTINGS_DIR",
            "FLATPAK_ID",
        }
        _filtered_env = {
            key: ("<set>" if "DIR" in key or key.endswith("HOME") else value)
            for key, value in os.environ.items()
            if key in _allowed_env_keys
        }
        self.log("debug", f"Environment summary: {_filtered_env}", "init")

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
        self._selected_game = self._sanitize_name(game_name)
        self._save_state()
        self.log("debug", f"Selected game changed to {self._selected_game}")
        return self.get_settings()

    def _sanitize_name(self, name: str | None) -> str:
        if not name:
            return ""
        # Remove control characters and newlines
        return " ".join(str(name).split())

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

            from .ludusavi import FLATPAK_ID, _ludusavi_env

            # find_ludusavi returns a list[str] like ["/usr/bin/flatpak", "run", ...]
            # or just ["/usr/bin/ludusavi"]
            prefix = find_ludusavi(explicit_flatpak_id=FLATPAK_ID, env=_ludusavi_env())

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

    def _coerce_history_entry(self, entry: Any) -> dict[str, Any] | None:
        """Validate and sanitize a history entry dictionary."""
        if not isinstance(entry, dict):
            return None

        # Required fields and their expected types
        schema = {
            "operation": str,
            "trigger": str,
            "status": str,
            "timestamp": str,
        }

        # Optional fields and their expected types
        optional = {
            "reason": (str, type(None)),
            "message": (str, type(None)),
        }

        coerced = {}
        for field, expected_type in schema.items():
            val = entry.get(field)
            if not isinstance(val, expected_type):
                return None
            coerced[field] = val

        # Validate basic enums to prevent arbitrary data injection
        if coerced["status"] not in ("backed_up", "restored", "skipped", "failed"):
            return None
        if coerced["operation"] not in ("backup", "restore", "start", "exit"):
            return None
        if coerced["trigger"] not in (
            "manual_backup",
            "manual_restore",
            "auto_start",
            "auto_exit",
        ):
            return None

        for field, expected_types in optional.items():
            val = entry.get(field)
            if isinstance(val, expected_types):
                coerced[field] = val
            else:
                coerced[field] = None

        return coerced

    def _update_last_operation(self, history: dict[str, Any]) -> None:
        """Compute the last_operation field based on the newest timestamp."""
        entries = [
            history.get("last_backup"),
            history.get("last_restore"),
            history.get("last_skip"),
            history.get("last_failure"),
        ]
        valid_entries = [e for e in entries if isinstance(e, dict) and e.get("timestamp")]
        if not valid_entries:
            history["last_operation"] = None
            return

        # Simple string comparison works for "YYYY-MM-DD HH:MM:SS"
        valid_entries.sort(key=lambda x: str(x["timestamp"]), reverse=True)
        history["last_operation"] = valid_entries[0]

    def _record_history(
        self,
        game_name: str,
        operation: str,
        trigger: str,
        status: str,
        reason: str | None = None,
        message: str | None = None,
    ) -> None:
        """Record a history entry for a specific game and persist state."""
        entry = self._coerce_history_entry(
            {
                "operation": operation,
                "trigger": trigger,
                "status": status,
                "reason": reason,
                "message": message,
                "timestamp": datetime.now().isoformat(timespec="microseconds"),
            }
        )
        if entry is None:
            return

        if game_name not in self._game_history:
            self._game_history[game_name] = {
                "last_backup": None,
                "last_restore": None,
                "last_skip": None,
                "last_failure": None,
                "last_operation": None,
            }

        history = self._game_history[game_name]
        if status == "backed_up":
            field = "last_backup"
        elif status == "restored":
            field = "last_restore"
        elif status == "failed":
            field = "last_failure"
        else:
            field = "last_skip"

        history[field] = entry
        self._update_last_operation(history)
        self._save_state()

    def refresh_games(
        self, force: bool = False, installed_app_ids: str | None = None
    ) -> dict[str, object]:
        """
        Refresh the list of games and their backup status from Ludusavi.

        If force is False, returns the cached game list if available.
        """
        normalized_installed_app_ids = _normalize_installed_app_ids(installed_app_ids)
        config_mtime_ns = self._current_ludusavi_config_mtime_ns()
        needs_refresh = force or not self._games

        if not force and normalized_installed_app_ids is not None:
            if self._installed_app_ids != normalized_installed_app_ids:
                needs_refresh = True
                self.log("debug", "installed_app_ids changed, forcing refresh", "refresh")

        if config_mtime_ns is _CONFIG_MARKER_READ_FAILED:
            needs_refresh = True
            committed_config_mtime_ns = None
            self.log("debug", "Ludusavi config marker unavailable, forcing refresh", "refresh")
        else:
            committed_config_mtime_ns = cast(int | None, config_mtime_ns)

        if not force and self._ludusavi_config_mtime_ns != committed_config_mtime_ns:
            needs_refresh = True
            self.log("debug", "Ludusavi config changed, forcing refresh", "refresh")

        if not needs_refresh:
            self.log("debug", "Returning cached game list", "refresh")
            return {
                "games": self._cached_games(),
                "aliases": self._aliases,
                "history": self._game_history,
                "dependency_error": None,
            }

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
            return {
                "games": [game.to_dict() for game in games],
                "aliases": self._aliases,
                "history": self._game_history,
                "dependency_error": None,
            }
        except (
            Exception
        ) as exc:  # pragma: no cover - concrete exception types come from pyludusavi.
            message = str(exc)
            return {
                "games": self._cached_games(),
                "aliases": self._aliases,
                "history": self._game_history,
                "dependency_error": message,
            }

    def handle_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """
        Logic triggered when a game is launched in Steam.

        Checks if a restore is needed based on backup recency.
        """
        game_name = self._sanitize_name(game_name)
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
            try:
                result = self._run_locked(
                    "restore",
                    game.name,
                    lambda: self._ludusavi().restore(game.name),
                )
            except Exception as exc:
                self._record_history(game.name, "restore", "auto_start", "failed", message=str(exc))
                raise
            self.log("info", f"Restored {game.name} before launch", "restore", game.name)
            self._record_history(game.name, "restore", "auto_start", "restored")
            return {"status": "restored", "game": game.name, "result": result}
        if recency == "local_current":
            return self._skip("start", game.name, "local_current")
        return self._skip("start", game.name, "ambiguous_recency")

    def handle_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """
        Logic triggered when a game is closed in Steam.

        Triggers an automatic backup if enabled.
        """
        game_name = self._sanitize_name(game_name)
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

        try:
            result = self._run_locked(
                "backup", game.name, lambda: self._ludusavi().backup(game.name)
            )
            # Record success immediately before the potentially failing refresh.
            self._record_history(game.name, "backup", "auto_exit", "backed_up")
        except Exception as exc:
            self._record_history(game.name, "backup", "auto_exit", "failed", message=str(exc))
            raise

        try:
            self._refresh_statuses_unlocked()
        except Exception as exc:
            self.log("warning", f"Post-backup status refresh failed: {exc}", "backup", game.name)

        self.log("info", f"Backed up {game.name} after exit", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_backup(self, game_name: str) -> dict[str, object]:
        """Trigger a manual backup for the specified game."""
        game_name = self._sanitize_name(game_name)
        game = self._match_game(game_name)
        if game is None:
            self.log("debug", "Skipping: game not found in Ludusavi list", "backup", game_name)
            return self._skip("backup", game_name, "unmatched_game")

        try:
            result = self._run_locked(
                "backup", game.name, lambda: self._ludusavi().backup(game.name)
            )
            # Record success immediately before the potentially failing refresh.
            self._record_history(game.name, "backup", "manual_backup", "backed_up")
        except Exception as exc:
            self._record_history(game.name, "backup", "manual_backup", "failed", message=str(exc))
            raise

        try:
            self._refresh_statuses_unlocked()
        except Exception as exc:
            self.log("warning", f"Post-backup status refresh failed: {exc}", "backup", game.name)

        self.log("info", f"Backed up {game.name}", "backup", game.name)
        return {"status": "backed_up", "game": game.name, "result": result}

    def force_restore(self, game_name: str) -> dict[str, object]:
        """Trigger a manual restore for the specified game."""
        game_name = self._sanitize_name(game_name)
        game = self._match_game(game_name)
        if game is None:
            self.log("debug", "Skipping: game not found in Ludusavi list", "restore", game_name)
            return self._skip("restore", game_name, "unmatched_game")
        if not game.has_backup:
            self.log("debug", "Skipping: game has no backup to restore", "restore", game.name)
            return self._skip("restore", game.name, "no_backup")

        try:
            result = self._run_locked(
                "restore", game.name, lambda: self._ludusavi().restore(game.name)
            )
        except Exception as exc:
            self._record_history(game.name, "restore", "manual_restore", "failed", message=str(exc))
            raise
        self.log("info", f"Restored {game.name}", "restore", game.name)
        self._record_history(game.name, "restore", "manual_restore", "restored")
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

        raw_shortcut_id = data.get("ludusaviLauncherShortcutAppId", -1)
        try:
            self._ludusavi_launcher_shortcut_id = int(raw_shortcut_id)
        except (TypeError, ValueError):
            self._warn_state_load("invalid ludusaviLauncherShortcutAppId; using -1")
            self._ludusavi_launcher_shortcut_id = -1

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

        self._installed_app_ids = data.get("installed_app_ids")
        raw_config_mtime_ns = data.get("ludusavi_config_mtime_ns")
        if isinstance(raw_config_mtime_ns, int):
            self._ludusavi_config_mtime_ns = raw_config_mtime_ns

        raw_history = data.get("game_history", {})
        if isinstance(raw_history, dict):
            self._game_history = {}
            for game_name, history in raw_history.items():
                if not isinstance(history, dict):
                    continue

                # Sanitize inner fields: each must be a dict or None
                validated_history = {}
                for field in ("last_backup", "last_restore", "last_skip", "last_failure"):
                    val = history.get(field)
                    validated_history[field] = self._coerce_history_entry(val)

                self._update_last_operation(validated_history)
                self._game_history[str(game_name)] = validated_history

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
        data["installed_app_ids"] = self._installed_app_ids
        data["ludusavi_config_mtime_ns"] = self._ludusavi_config_mtime_ns
        data["game_history"] = self._game_history

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

    def _refresh_statuses_unlocked(
        self,
        installed_app_ids: str | None | object = _CACHE_MARKER_UNCHANGED,
        ludusavi_config_mtime_ns: int | None | object = _CACHE_MARKER_UNCHANGED,
    ) -> list[GameStatus]:
        """
        Internal implementation of status refresh, executed within
        the operation lock.
        """
        raw_statuses = self._ludusavi().refresh_statuses()
        self.log(
            "debug", f"Retrieved {len(raw_statuses)} raw game statuses from Ludusavi", "refresh"
        )

        from collections.abc import Mapping

        games = []
        for raw_game in raw_statuses:
            try:
                if not isinstance(raw_game, Mapping):
                    raise TypeError(
                        f"status entry must be a mapping, got {type(raw_game).__name__}"
                    )
                game = self._coerce_game_status(dict(raw_game))
                games.append(game)
            except Exception as exc:
                raw_name = raw_game.get("name") if isinstance(raw_game, Mapping) else "<unknown>"
                self.log(
                    "error",
                    f"Failed to parse status for game {raw_name}: {exc}",
                    "refresh",
                )

        self._games = {game.name: game for game in games}
        self._aliases = getattr(self._ludusavi(), "get_aliases", lambda: {})()
        self._ids = {game.steam_id: game.name for game in games if game.steam_id}

        if installed_app_ids is not _CACHE_MARKER_UNCHANGED:
            self._installed_app_ids = cast(str | None, installed_app_ids)
        if ludusavi_config_mtime_ns is not _CACHE_MARKER_UNCHANGED:
            self._ludusavi_config_mtime_ns = cast(int | None, ludusavi_config_mtime_ns)

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
        game_name = self._sanitize_name(game_name)
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

        if reason not in ("auto_sync_disabled", "operation_running", "unmatched_game"):
            if operation in ("backup", "restore"):
                trigger = f"manual_{operation}"
            elif operation == "start":
                trigger = "auto_start"
            elif operation == "exit":
                trigger = "auto_exit"
            else:
                trigger = "unknown"
            self._record_history(game_name, operation, trigger, "skipped", reason=reason)

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
            with self._adapter_lock:
                if self._adapter is None:
                    self._adapter = self._adapter_factory()
        return self._adapter

    def _current_ludusavi_config_mtime_ns(self) -> int | None | object:
        try:
            return self._ludusavi().get_config_mtime_ns()
        except Exception as exc:
            self.log(
                "debug",
                f"Unable to read Ludusavi config marker; forcing refresh: {exc}",
                "refresh",
            )
            return _CONFIG_MARKER_READ_FAILED


def _normalize(game_name: str) -> str:
    """Normalize a game name for easier matching."""
    # Retain dots and hyphens for better precision in non-steam titles
    return re.sub(r"[^a-z0-9.-]+", " ", game_name.casefold()).strip()


def _normalize_installed_app_ids(raw: str | None) -> str | None:
    if raw is None:
        return None
    if len(raw) > MAX_INSTALLED_APP_IDS_BYTES:
        return None
    tokens = raw.split(",")
    if any(not token.isdecimal() for token in tokens):
        return None
    app_ids = sorted({int(token) for token in tokens})
    return ",".join(str(app_id) for app_id in app_ids)


def _default_adapter_factory() -> LudusaviAdapter:
    """The default factory for creating a Ludusavi adapter."""
    from .ludusavi import PyludusaviAdapter

    return PyludusaviAdapter()
