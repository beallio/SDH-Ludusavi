from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from collections import deque
from pathlib import Path
from typing import Any, cast

# For test backward compatibility, import helper objects into module scope
from ._version import resolve_version  # noqa: F401
from .persistence import JsonSettingsStore, SettingsStore, PersistenceManager  # noqa: F401
from .coordinator import OperationLockedError, OperationState, OperationCoordinator  # noqa: F401
from .watchdog import (  # noqa: F401
    _coerce_signal_pid,  # noqa: F401
    _send_signal_tree,  # noqa: F401
    _child_pids,  # noqa: F401
    MAX_SIGNAL_PID,  # noqa: F401
    _read_ppid,  # noqa: F401
    _process_tree,  # noqa: F401
)
from .log_buffer import LogEntry, DeckyLogHandler  # noqa: F401

from .constants import (
    DEFAULT_NOTIFICATION_SETTINGS,
    MAX_INSTALLED_APP_IDS_BYTES,
    CONFIG_MARKER_READ_FAILED,
    CACHE_MARKER_UNCHANGED,
)
from .types import LudusaviAdapter, GameStatus

LOGGER = logging.getLogger(__name__)

# For backward compatibility
_CONFIG_MARKER_READ_FAILED = CONFIG_MARKER_READ_FAILED
_CACHE_MARKER_UNCHANGED = CACHE_MARKER_UNCHANGED


# For test compatibility, keep references to LogEntry and DeckyLogHandler

# Maintain module level variables for AST check in test_service.py
try:
    import decky

    _DECKY_LOGGER = getattr(decky, "logger", None)
except (ImportError, AttributeError):
    _DECKY_LOGGER = None


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


class SDHLudusaviService:
    """The core synchronous backend service for SDH-ludusavi.

    Composes sub-managers to enforce SRP and delegate concerns.
    """

    def __init__(
        self,
        adapter: LudusaviAdapter | None = None,
        adapter_factory: Callable[[], LudusaviAdapter] | None = None,
        state_path: Path | None = None,
        settings_store: SettingsStore | None = None,
        cache_path: Path | None = None,
        log_limit: int = 100,
    ) -> None:
        if adapter is not None and adapter_factory is not None:
            raise ValueError("adapter and adapter_factory cannot both be provided")
        if state_path is not None and (settings_store is not None or cache_path is not None):
            raise ValueError("state_path cannot be combined with split settings/cache storage")

        # 1. State properties initialization for tests and facade proxying
        self._auto_sync_enabled = False
        self._selected_game = ""
        self._notification_settings = dict(DEFAULT_NOTIFICATION_SETTINGS)
        self._ludusavi_launcher_shortcut_id = -1
        self._games: dict[str, GameStatus] = {}
        self._aliases: dict[str, str] = {}
        self._ids: dict[str, str] = {}
        self._installed_app_ids: str | None = None
        self._ludusavi_config_mtime_ns: int | None = None
        self._diagnostics_logged = False
        self._state_lock = threading.RLock()

        # 2. Early sub-managers setup (so property proxies don't fail)
        from .log_buffer import DiagnosticLogBuffer

        self._log_buffer = DiagnosticLogBuffer(self, log_limit=log_limit)

        from .gateway import LudusaviGateway

        self._gateway = LudusaviGateway(self, adapter=adapter, adapter_factory=adapter_factory)

        self._coordinator = OperationCoordinator(self)

        # 3. Persistence Layer
        self._persistence = PersistenceManager(
            state_path=state_path,
            settings_store=settings_store,
            cache_path=cache_path,
        )

        # 4. Load State payloads
        self._load_state()

        # 5. Process Watchdog
        from .watchdog import ProcessWatchdog

        self._watchdog = ProcessWatchdog(
            self,
            log_callback=self.log,
            is_operation_running=lambda: self._coordinator.is_running,
        )

        # 6. History Manager
        from .history import HistoryManager

        self._history = HistoryManager(
            self,
            initial_history=self._game_history_raw,
            save_callback=self._save_state,
        )

        # 7. Game Registry Matcher
        from .matcher import GameRegistryMatcher

        self._matcher = GameRegistryMatcher()

        # 8. Game Lifecycle Manager
        from .lifecycle import GameLifecycleManager

        self._lifecycle = GameLifecycleManager(self)

        # Configure unified logging
        self._log_buffer.setup_logging()
        self.log("info", "SDH-ludusavi service initialized", "init")

        import getpass

        identity = f"uid={os.getuid()}, euid={os.geteuid()}, user={getpass.getuser()}"
        self.log("debug", f"Process identity: {identity}", "init")

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

    @property
    def _operation(self) -> OperationState:
        return self._coordinator._operation

    @_operation.setter
    def _operation(self, val: OperationState) -> None:
        self._coordinator._operation = val

    @property
    def _operation_lock(self) -> threading.Lock:
        return self._coordinator._operation_lock

    @property
    def _adapter(self) -> LudusaviAdapter | None:
        return self._gateway._adapter

    @_adapter.setter
    def _adapter(self, val: LudusaviAdapter | None) -> None:
        self._gateway._adapter = val

    @property
    def _adapter_lock(self) -> threading.Lock:
        return self._gateway._adapter_lock

    @property
    def _adapter_factory(self) -> Callable[[], LudusaviAdapter]:
        return self._gateway._adapter_factory

    @_adapter_factory.setter
    def _adapter_factory(self, val: Callable[[], LudusaviAdapter]) -> None:
        self._gateway._adapter_factory = val

    @property
    def _game_history(self) -> dict[str, dict[str, Any]]:
        return self._history._game_history

    @_game_history.setter
    def _game_history(self, val: dict[str, dict[str, Any]]) -> None:
        self._history._game_history = val

    @property
    def _logs(self) -> deque[LogEntry]:
        return self._log_buffer._logs

    @_logs.setter
    def _logs(self, val: deque[LogEntry]) -> None:
        self._log_buffer._logs = val

    @property
    def _paused_pids(self) -> dict[int, float]:
        return self._watchdog._paused_pids

    @_paused_pids.setter
    def _paused_pids(self, val: dict[int, float]) -> None:
        self._watchdog._paused_pids = val

    @property
    def _paused_pids_lock(self) -> threading.Lock:
        return self._watchdog._paused_pids_lock

    @property
    def _watchdog_active(self) -> bool:
        return self._watchdog._watchdog_active

    @_watchdog_active.setter
    def _watchdog_active(self, val: bool) -> None:
        self._watchdog._watchdog_active = val

    @property
    def _watchdog_thread(self) -> threading.Thread | None:
        return self._watchdog._watchdog_thread

    @_watchdog_thread.setter
    def _watchdog_thread(self, val: threading.Thread | None) -> None:
        self._watchdog._watchdog_thread = val

    @property
    def _watchdog_stop(self) -> threading.Event:
        return self._watchdog._watchdog_stop

    def _ludusavi(self) -> LudusaviAdapter:
        return self._gateway.get_adapter()

    def _log_ludusavi_diagnostics(self, adapter: LudusaviAdapter) -> None:
        if self._diagnostics_logged:
            return
        self._diagnostics_logged = True

        def run() -> None:
            try:
                diagnostics = adapter.get_diagnostics()
            # Intentionally broad: catch any diagnostics retrieval error safely
            except Exception as exc:
                self.log("debug", f"Ludusavi diagnostics unavailable: {exc}", "init")
                return

            version = diagnostics.get("version", "unknown")
            ludusavi_type = diagnostics.get("type", "unknown")
            path = diagnostics.get("path", "unknown")
            config_path = diagnostics.get("configPath", "unknown")
            backup_path = diagnostics.get("backupPath", "unknown")
            self.log("info", f"Ludusavi version: {version}", "init")
            self.log("info", f"Ludusavi type/path: {ludusavi_type} {path}", "init")
            self.log("info", f"Ludusavi config path: {config_path}", "init")
            self.log("info", f"Ludusavi backup path: {backup_path}", "init")

        threading.Thread(target=run, daemon=True).start()

    def _run_locked(self, operation: str, game_name: str | None, callback: Any) -> Any:
        return self._coordinator.run_locked(operation, game_name, callback, self.log)

    def stop(self) -> None:
        """Shut down the watchdog thread and resume all paused processes."""
        self._watchdog.stop()

    def log(
        self, level: str, message: str, operation: str | None = None, game_name: str | None = None
    ) -> None:
        """Add an entry to the internal diagnostic log buffer."""
        self._log_buffer.log(level, message, operation, game_name)

    def get_settings(self) -> dict[str, Any]:
        """Return the current plugin settings."""
        return {
            "auto_sync_enabled": self._auto_sync_enabled,
            "selected_game": self._selected_game,
            "notifications": dict(self._notification_settings),
        }

    def get_game_history(self) -> dict[str, dict[str, Any]]:
        """Return the current game operation history."""
        return self._history.get_history()

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

    def set_notification_settings(self, settings: dict[str, object]) -> dict[str, Any]:
        """Update notification preferences and persist them to disk."""
        self._notification_settings = self._coerce_notification_settings(settings)
        self._save_state()
        self.log("info", "Notification settings updated")
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
        """Return the command path and args used by the plugin for GUI launching."""
        return self._gateway.get_ludusavi_command()

    def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
        normalized = _normalize_installed_app_ids(installed_app_ids)
        mtime = self._current_ludusavi_config_mtime_ns()
        return self._matcher.is_game_cache_current(
            has_games=bool(self._games),
            installed_app_ids=self._installed_app_ids,
            target_installed_app_ids=normalized,
            config_mtime_ns=self._ludusavi_config_mtime_ns,
            target_config_mtime_ns=None
            if mtime is _CONFIG_MARKER_READ_FAILED
            else cast(int | None, mtime),
        )

    def refresh_games(
        self, force: bool = False, installed_app_ids: str | None = None
    ) -> dict[str, object]:
        """Refresh the list of games and their backup status from Ludusavi."""
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
                "aliases": dict(self._aliases),
                "history": self.get_game_history(),
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
                "aliases": dict(self._aliases),
                "history": self.get_game_history(),
                "dependency_error": None,
            }
        # Intentionally broad: fallback that reports dependency errors back to the caller instead of crashing the UI or service initialization.
        except Exception as exc:
            return {
                "games": self._cached_games(),
                "aliases": dict(self._aliases),
                "history": self.get_game_history(),
                "dependency_error": str(exc),
            }

    def check_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Check whether a game launch needs a restore without changing local saves."""
        return self._lifecycle.check_game_start(game_name, app_id)

    def resolve_game_start_conflict(
        self, game_name: str, app_id: str | None, resolution: str
    ) -> dict[str, object]:
        """Apply the user's choice for an ambiguous launch recency conflict."""
        return self._lifecycle.resolve_game_start_conflict(game_name, app_id, resolution)

    def restore_game_on_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Restore a game's backup during launch after a check reports it is needed."""
        return self._lifecycle.restore_game_on_start(game_name, app_id)

    def handle_game_start(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Compatibility wrapper for the original one-call launch autosync flow."""
        return self._lifecycle.handle_game_start(game_name, app_id)

    def check_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Check whether a game exit needs a backup without writing backup data."""
        return self._lifecycle.check_game_exit(game_name, app_id)

    def backup_game_on_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Back up a game during exit after a check reports it is needed."""
        return self._lifecycle.backup_game_on_exit(game_name, app_id)

    def handle_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        """Compatibility wrapper for the original one-call exit autosync flow."""
        return self._lifecycle.handle_game_exit(game_name, app_id)

    def force_backup(self, game_name: str) -> dict[str, object]:
        """Trigger a manual backup for the specified game."""
        return self._lifecycle.force_backup(game_name)

    def force_restore(self, game_name: str) -> dict[str, object]:
        """Trigger a manual restore for the specified game."""
        return self._lifecycle.force_restore(game_name)

    def get_versions(self) -> dict[str, str]:
        """Fetch version information for Ludusavi and the plugin."""
        return self._gateway.get_versions()

    def get_ludusavi_logs(self) -> str:
        """Read and return the contents of the Ludusavi log file."""
        return self._gateway.get_logs()

    def get_operation_status(self) -> dict[str, object]:
        """Return information about the currently running or last completed operation."""
        return self._coordinator.get_status()

    def get_recent_logs(self) -> list[dict[str, object]]:
        """Return the most recent log entries in chronological order."""
        return self._log_buffer.get_recent()

    def pause_game_process(self, pid: int) -> dict[str, object]:
        """Suspend a launched game process tree while start sync runs."""
        return self._watchdog.pause(pid)

    def resume_game_process(self, pid: int) -> dict[str, object]:
        """Resume a previously suspended game process tree."""
        return self._watchdog.resume(pid)

    def resume_all_paused_processes(self) -> None:
        """Best-effort cleanup for plugin unload or launch-gate failures."""
        self._watchdog.resume_all()

    # Internal persistence & matching coordination
    def _load_state(self) -> None:
        """Load plugin settings and runtime cache from persistent storage."""
        data = self._persistence.load_all()
        settings = data["settings"]
        cache = data["cache"]

        self._auto_sync_enabled = bool(settings.get("auto_sync_enabled", False))
        self._selected_game = str(settings.get("selected_game", ""))
        self._notification_settings = self._coerce_notification_settings(
            settings.get("notifications", {})
        )

        raw_shortcut_id = cache.get("ludusaviLauncherShortcutAppId", -1)
        try:
            self._ludusavi_launcher_shortcut_id = int(raw_shortcut_id)
        except (ValueError, TypeError):
            self._ludusavi_launcher_shortcut_id = -1

        # Load cached games
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

        # Load cached aliases and IDs
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

        # Raw history buffer for initial initialization of HistoryManager
        self._game_history_raw = cache.get("game_history", {})

    def _save_state(self) -> None:
        """Persist current plugin settings and runtime cache."""
        with self._state_lock:
            # Settings Payload
            settings_payload = {
                "auto_sync_enabled": self._auto_sync_enabled,
                "selected_game": self._selected_game,
                "notifications": dict(self._notification_settings),
            }
            self._persistence.save_settings(settings_payload)

            # Cache Payload
            history_data = getattr(self, "_history", None)
            game_history = history_data.get_history() if history_data else self._game_history_raw
            cache_payload = {
                "ludusaviLauncherShortcutAppId": self._ludusavi_launcher_shortcut_id,
                "games": [game.to_dict() for game in self._games.values()],
                "aliases": self._aliases,
                "ids": self._ids,
                "installed_app_ids": self._installed_app_ids,
                "ludusavi_config_mtime_ns": self._ludusavi_config_mtime_ns,
                "game_history": game_history,
            }
            self._persistence.save_cache(cache_payload)

    def _refresh_statuses_unlocked(
        self,
        installed_app_ids: str | None | object = _CACHE_MARKER_UNCHANGED,
        ludusavi_config_mtime_ns: int | None | object = _CACHE_MARKER_UNCHANGED,
    ) -> list[GameStatus]:
        raw_statuses = self._gateway.get_adapter().refresh_statuses()
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
            except (KeyError, TypeError, ValueError) as exc:
                raw_name = raw_game.get("name") if isinstance(raw_game, Mapping) else "<unknown>"
                self.log("error", f"Failed to parse status for game {raw_name}: {exc}", "refresh")

        with self._state_lock:
            if not (
                isinstance(ludusavi_config_mtime_ns, int)
                and self._ludusavi_config_mtime_ns == ludusavi_config_mtime_ns
            ):
                adapter = self._gateway.get_adapter()
                new_aliases = getattr(adapter, "get_aliases", lambda: {})()
                self._aliases.clear()
                self._aliases.update(new_aliases)

            self._games.clear()
            self._games.update({game.name: game for game in games})

            self._ids.clear()
            self._ids.update({game.steam_id: game.name for game in games if game.steam_id})

            if installed_app_ids is not _CACHE_MARKER_UNCHANGED:
                self._installed_app_ids = cast(str | None, installed_app_ids)
            if ludusavi_config_mtime_ns is not _CACHE_MARKER_UNCHANGED:
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
        return [game.to_dict() for game in self._games.values()]

    def _match_game(self, game_name: str, app_id: str | None = None) -> GameStatus | None:
        game_name = self._sanitize_name(game_name)
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

    def _conflict_metadata(self, game_name: str) -> dict[str, object]:
        try:
            metadata = self._gateway.get_adapter().get_conflict_metadata(game_name)
        # Intentionally broad: metadata/diagnostic preview fallback that must not block user-facing conflict prompts.
        except Exception as exc:
            self.log(
                "debug",
                f"Unable to collect conflict metadata for {game_name}: {exc}",
                "start",
                game_name,
            )
            metadata = {}
        return {
            "localModifiedAt": metadata.get("localModifiedAt"),
            "backupModifiedAt": metadata.get("backupModifiedAt"),
            "backupPath": metadata.get("backupPath"),
        }

    def _skip(self, operation: str, game_name: str, reason: str) -> dict[str, object]:
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
            self._history.record_history(game_name, operation, trigger, "skipped", reason=reason)
        return {"status": "skipped", "game": game_name, "reason": reason}

    def _current_ludusavi_config_mtime_ns(self) -> int | None | object:
        return self._gateway.current_config_mtime_ns()

    def _sanitize_name(self, name: str | None) -> str:
        if not name:
            return ""
        return " ".join(str(name).split())

    def _coerce_notification_settings(self, settings: object) -> dict[str, bool]:
        coerced = dict(DEFAULT_NOTIFICATION_SETTINGS)
        if not isinstance(settings, dict):
            return coerced
        typed_settings = cast(dict[str, object], settings)
        for key in DEFAULT_NOTIFICATION_SETTINGS:
            value = typed_settings.get(key)
            if isinstance(value, bool):
                coerced[key] = value
        return coerced


# Keep fuzzy matching module-level functions mapped to GameRegistryMatcher


def _normalize(game_name: str) -> str:
    from .matcher import GameRegistryMatcher

    return GameRegistryMatcher().normalize(game_name)


def _fuzzy_match_allowed(normalized_input: str, normalized_target: str, configured: bool) -> bool:
    from .matcher import GameRegistryMatcher

    return GameRegistryMatcher().fuzzy_match_allowed(
        normalized_input, normalized_target, configured
    )


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


def _default_adapter_factory() -> LudusaviAdapter:
    from .ludusavi import PyludusaviAdapter

    return PyludusaviAdapter()
