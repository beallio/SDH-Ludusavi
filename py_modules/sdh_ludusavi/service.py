from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, cast

from ._version import resolve_version
from .persistence import SettingsStore, PersistenceManager
from .coordinator import OperationLockedError, OperationCoordinator

from .constants import DEFAULT_NOTIFICATION_SETTINGS
from .updater import PluginUpdater
from .types import LudusaviAdapter
from sdh_ludusavi.game_names import sanitize_game_name

__all__ = ["SDHLudusaviService", "OperationLockedError", "DEFAULT_NOTIFICATION_SETTINGS"]

LOGGER = logging.getLogger(__name__)


class SDHLudusaviService:
    """The core synchronous backend service for SDH-ludusavi.

    Acts as a facade delegating tasks to dedicated sub-managers.
    """

    def __init__(
        self,
        adapter: LudusaviAdapter | None = None,
        adapter_factory: Callable[[], LudusaviAdapter] | None = None,
        settings_store: SettingsStore | None = None,
        cache_path: Path | None = None,
        log_limit: int = 100,
    ) -> None:
        if adapter is not None and adapter_factory is not None:
            raise ValueError("adapter and adapter_factory cannot both be provided")

        # 1. Local settings properties
        self._auto_sync_enabled = False
        self._selected_game = ""
        self._debug_logging = True
        self._notification_settings = _coerce_notification_settings(DEFAULT_NOTIFICATION_SETTINGS)
        self._ludusavi_launcher_shortcut_id = -1
        self._state_lock = threading.RLock()

        # Update Settings
        import datetime
        import time

        from sdh_ludusavi.updater_client import GitHubReleaseClient

        self._updater = PluginUpdater(
            state_lock=self._state_lock,
            save_callback=self._save_state,
            log_callback=lambda level, message: self.log(level, message),
            release_client=GitHubReleaseClient(),
            version_resolver=resolve_version,
            now=lambda: datetime.datetime.now(datetime.timezone.utc),
            monotonic=time.monotonic,
        )

        # 2. Sub-managers setup
        from .log_buffer import DiagnosticLogBuffer

        self._log_buffer = DiagnosticLogBuffer(log_limit=log_limit)

        from .gateway import LudusaviGateway

        self._gateway = LudusaviGateway(
            adapter=adapter, adapter_factory=adapter_factory, log_callback=self.log
        )

        self._coordinator = OperationCoordinator()

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
            settings_store=settings_store,
            cache_path=cache_path,
        )

        # 4. Load State payloads
        self._load_state()

        # 5. Process Watchdog
        from .watchdog import ProcessWatchdog

        self._watchdog = ProcessWatchdog(
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
                skip=lambda op, game, r: _skip(self, op, game, r),
                conflict_metadata=lambda game_name: _conflict_metadata(self, game_name),
            )
        )

        # 8. Syncthing Watch Manager
        from .syncthing import SyncthingWatchManager

        self._syncthing_watch_manager = SyncthingWatchManager()

        # Configure unified logging
        self._log_buffer.setup_logging()
        self.log("info", "SDH-ludusavi service initialized", "init")

        self.log("debug", f"Process identity: {_resolve_process_identity()}", "init")

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
        self._syncthing_watch_manager.stop_all()

    def start_syncthing_activity_watch(
        self, phase: str, game_name: str | None, app_id: str | None
    ) -> dict[str, Any]:
        backup_path = self._gateway.get_diagnostics().get("backupPath")
        if not isinstance(backup_path, str) or backup_path == "unknown" or not backup_path.strip():
            backup_path = None
        return self._syncthing_watch_manager.start_watch(phase, game_name, app_id, backup_path)

    def get_syncthing_activity(self, watch_id: str) -> dict[str, Any]:
        return self._syncthing_watch_manager.poll_watch(watch_id)

    def stop_syncthing_activity_watch(self, watch_id: str) -> dict[str, Any]:
        return self._syncthing_watch_manager.stop_watch(watch_id)

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
            "debug_logging": self._debug_logging,
            "notifications": dict(self._notification_settings),
            **self._updater.settings_payload(),
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
        self._selected_game = sanitize_game_name(game_name)
        self._save_state()
        self.log("debug", f"Selected game changed to {self._selected_game}")
        return self.get_settings()

    def set_notification_settings(self, settings: dict[str, object]) -> dict[str, Any]:
        """Update notification preferences and persist them to disk."""
        self._notification_settings = _coerce_notification_settings(settings)
        self._save_state()
        self.log("info", "Notification settings updated")
        return self.get_settings()

    def set_debug_logging(self, enabled: bool) -> dict[str, Any]:
        """Update the debug logging setting and persist it to disk."""
        self._debug_logging = bool(enabled)
        self._save_state()
        self._apply_log_level()
        self.log("info", f"Debug logging {'enabled' if enabled else 'disabled'}")
        return self.get_settings()

    def _apply_log_level(self) -> None:
        try:
            import decky

            logger = getattr(decky, "logger", None)
            if logger:
                level = logging.DEBUG if self._debug_logging else logging.INFO
                logger.setLevel(level)
        except ImportError:
            pass

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

    def list_backups(self, game_name: str) -> dict[str, object]:
        return self._lifecycle.list_backups(game_name)

    def restore_backup_version(self, game_name: str, backup_id: str) -> dict[str, object]:
        return self._lifecycle.restore_backup_version(game_name, backup_id)

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
        from .persistence import StateLockTimeoutError

        try:
            data = self._persistence.load_all()
        except StateLockTimeoutError as exc:
            self.log("warning", f"Failed to acquire state lock during startup: {exc}")
            data = {"settings": {}, "cache": {}}

        settings = data["settings"]
        cache = data["cache"]

        self._auto_sync_enabled = bool(settings.get("auto_sync_enabled", False))
        self._selected_game = str(settings.get("selected_game", ""))
        self._debug_logging = bool(settings.get("debug_logging", True))
        self._apply_log_level()
        self._notification_settings = _coerce_notification_settings(
            settings.get("notifications", {})
        )

        raw_shortcut_id = cache.get("ludusaviLauncherShortcutAppId", -1)
        try:
            self._ludusavi_launcher_shortcut_id = int(raw_shortcut_id)
        except (ValueError, TypeError):
            self._ludusavi_launcher_shortcut_id = -1

        self._registry.load_cache(cache)
        self._game_history_raw = cache.get("game_history", {})

        # Load update properties
        self._updater.load_state(settings, cache)

    def _save_state(self) -> None:
        """Persist current plugin settings and runtime cache."""
        with self._state_lock:
            settings_payload = {
                "auto_sync_enabled": self._auto_sync_enabled,
                "selected_game": self._selected_game,
                "debug_logging": self._debug_logging,
                "notifications": dict(self._notification_settings),
                **self._updater.settings_payload(),
            }
            self._persistence.save_settings(settings_payload)

            # Cache Payload
            history_data = getattr(self, "_history", None)
            game_history = history_data.get_history() if history_data else self._game_history_raw
            cache_payload = {
                "ludusaviLauncherShortcutAppId": self._ludusavi_launcher_shortcut_id,
                "game_history": game_history,
                **self._registry.cache_payload(),
                **self._updater.cache_payload(),
            }
            self._persistence.save_cache(cache_payload)

    # Updater helper methods
    def set_update_channel(self, channel: str) -> dict[str, Any]:
        """Update the update channel setting and persist it to disk."""
        self._updater.set_channel(channel)
        return self.get_settings()

    def set_automatic_update_checks(self, enabled: bool) -> dict[str, Any]:
        """Update the automatic update checks setting and persist it to disk."""
        self._updater.set_automatic_checks(enabled)
        return self.get_settings()

    def get_update_check_context(self) -> dict[str, Any]:
        return self._updater.get_context()

    def check_for_plugin_update(
        self,
        current_version: str,
        force: bool = False,
    ) -> dict[str, object]:
        return self._updater.check_for_update(current_version, force)

    def record_update_install_requested(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return self._updater.record_install_requested(candidate)

    def confirm_update_install_handoff(self, version: str) -> dict[str, Any]:
        return self._updater.confirm_install_handoff(version)

    def clear_pending_update_install(self, version: str | None = None) -> dict[str, Any]:
        return self._updater.clear_pending_install(version)

    def reconcile_pending_update_install(self, current_version: str) -> None:
        # Atomic claim: re-read persisted state under the inter-process lock
        # so a reconcile racing another plugin instance (Decky's update reload
        # storm) never promotes from, or writes back, a stale snapshot.
        # Lock order matches _save_state: state lock, then persistence lock.
        from .persistence import StateLockTimeoutError

        try:
            with self._state_lock:
                with self._persistence.locked():
                    fresh = self._persistence.load_all()
                    self._updater.adopt_persisted_cache(fresh["cache"])
                    self._updater.reconcile_pending_install(current_version)
        except StateLockTimeoutError as exc:
            self.log("warning", f"Skipping pending install reconcile due to lock timeout: {exc}")

    def revalidate_plugin_update(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return self._updater.revalidate(candidate)

    def has_pending_update_install(self) -> bool:
        return self._updater.has_pending_install()


def _conflict_metadata(service: SDHLudusaviService, game_name: str) -> dict[str, object]:
    try:
        metadata = service._gateway.get_adapter().get_conflict_metadata(game_name)
    # Intentionally broad
    except Exception as exc:
        service.log(
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


def _skip(
    service: SDHLudusaviService, operation: str, game_name: str, reason: str
) -> dict[str, object]:
    service.log("info", f"Skipped {operation} for {game_name}: {reason}", operation, game_name)
    if reason not in ("auto_sync_disabled", "operation_running", "unmatched_game"):
        if operation in ("backup", "restore"):
            trigger = f"manual_{operation}"
        elif operation == "start":
            trigger = "auto_start"
        elif operation == "exit":
            trigger = "auto_exit"
        else:
            trigger = "unknown"
        service._history.record_history(game_name, operation, trigger, "skipped", reason=reason)
    return {"status": "skipped", "game": game_name, "reason": reason}


def _resolve_process_identity() -> str:
    uid = os.getuid()
    euid = os.geteuid()
    try:
        import pwd

        user = pwd.getpwuid(uid).pw_name
    except (KeyError, ImportError):
        import getpass

        try:
            user = getpass.getuser()
        # Intentionally broad
        except Exception:
            user = "unknown"
    return f"uid={uid}, euid={euid}, user={user}"


def _coerce_notification_settings(settings: object) -> dict[str, bool]:
    coerced = dict(DEFAULT_NOTIFICATION_SETTINGS)
    if not isinstance(settings, dict):
        return coerced
    typed_settings = cast(dict[str, object], settings)
    for key in DEFAULT_NOTIFICATION_SETTINGS:
        value = typed_settings.get(key)
        if isinstance(value, bool):
            coerced[key] = value
    return coerced
