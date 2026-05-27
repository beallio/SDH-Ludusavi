from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, cast

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
    CONFIG_MARKER_READ_FAILED,
    CACHE_MARKER_UNCHANGED,
)
from .types import LudusaviAdapter, GameStatus

LOGGER = logging.getLogger(__name__)

# For backward compatibility
_CONFIG_MARKER_READ_FAILED = CONFIG_MARKER_READ_FAILED
_CACHE_MARKER_UNCHANGED = CACHE_MARKER_UNCHANGED


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
        "warning": getattr(_DECKY_LOGGER, "warning", _DECKY_LOGGER.info),
        "error": getattr(
            _DECKY_LOGGER, "error", getattr(_DECKY_LOGGER, "exception", _DECKY_LOGGER.info)
        ),
        "debug": getattr(_DECKY_LOGGER, "info", None),
        "info": getattr(_DECKY_LOGGER, "info", None),
    }
    logger_level = logger_level_map.get(level, getattr(_DECKY_LOGGER, "info", None))
    if logger_level:
        logger_level(f"[DEBUG] {message}" if level == "debug" else message)


class SDHLudusaviService:
    """The core synchronous backend service for SDH-ludusavi.

    Acts as a facade delegating tasks to dedicated sub-managers.
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

        # 1. Local settings properties
        self._auto_sync_enabled = False
        self._selected_game = ""
        self._notification_settings = dict(DEFAULT_NOTIFICATION_SETTINGS)
        self._ludusavi_launcher_shortcut_id = -1
        self._state_lock = threading.RLock()

        # 2. Sub-managers setup
        from .log_buffer import DiagnosticLogBuffer

        self._log_buffer = DiagnosticLogBuffer(self, log_limit=log_limit)

        from .gateway import LudusaviGateway

        self._gateway = LudusaviGateway(
            adapter=adapter, adapter_factory=adapter_factory, log_callback=self.log
        )

        self._coordinator = OperationCoordinator(self)

        from .registry import GameRegistry

        self._registry = GameRegistry(
            gateway=self._gateway,
            run_locked=self._run_locked,
            log_callback=self.log,
            save_callback=self._save_state,
            get_history_callback=self.get_game_history,
        )

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

        # 7. Game Lifecycle Manager
        from .lifecycle import GameLifecycleManager, LifecycleDependencies

        self._lifecycle = GameLifecycleManager(
            LifecycleDependencies(
                registry=self._registry,
                gateway=self._gateway,
                history=self._history,
                is_coordinator_running=lambda: self._coordinator.is_running,
                run_locked=self._run_locked,
                is_auto_sync_enabled=lambda: self._auto_sync_enabled,
                log=self.log,
                skip=self._skip,
                conflict_metadata=self._conflict_metadata,
            )
        )

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

    def _ludusavi(self) -> LudusaviAdapter:
        return self._gateway.get_adapter()

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
        return self._registry.is_game_cache_current(installed_app_ids)

    def refresh_games(
        self, force: bool = False, installed_app_ids: str | None = None
    ) -> dict[str, object]:
        """Refresh the list of games and their backup status from Ludusavi."""
        return self._registry.refresh_games(force, installed_app_ids)

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

    _logs = property(lambda self: self._log_buffer._logs)
    _operation = property(lambda self: self._coordinator._operation)
    _games = property(
        lambda self: self._registry._games,
        lambda self, v: setattr(self._registry, "_games", v),
    )
    _aliases = property(lambda self: self._registry._aliases)
    _installed_app_ids = property(
        lambda self: self._registry._installed_app_ids,
        lambda self, v: setattr(self._registry, "_installed_app_ids", v),
    )
    _ludusavi_config_mtime_ns = property(
        lambda self: self._registry._ludusavi_config_mtime_ns,
        lambda self, v: setattr(self._registry, "_ludusavi_config_mtime_ns", v),
    )
    _watchdog_active = property(lambda self: self._watchdog._watchdog_active)
    _watchdog_thread = property(lambda self: self._watchdog._watchdog_thread)
    _paused_pids = property(lambda self: self._watchdog._paused_pids)
    _paused_pids_lock = property(lambda self: self._watchdog._paused_pids_lock)

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

        self._registry.load_cache(cache)
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
                "game_history": game_history,
                **self._registry.cache_payload(),
            }
            self._persistence.save_cache(cache_payload)

    def _match_game(self, game_name: str, app_id: str | None = None) -> GameStatus | None:
        return self._registry.match_game(game_name, app_id)

    def _conflict_metadata(self, game_name: str) -> dict[str, object]:
        try:
            metadata = self._gateway.get_adapter().get_conflict_metadata(game_name)
        # Intentionally broad
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
    from .registry import _normalize_installed_app_ids as norm

    return norm(raw)
