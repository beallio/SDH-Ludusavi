from __future__ import annotations

import asyncio
import contextvars
import functools
import os
from concurrent.futures import Executor
from pathlib import Path
import threading
from typing import Any

import decky

from sdh_ludusavi.rpc_pool import DaemonThreadPool
from sdh_ludusavi.singleton import enforce_single_instance
from sdh_ludusavi.service import (
    DEFAULT_NOTIFICATION_SETTINGS,
    OperationLockedError,
    SDHLudusaviService,
)

CACHE_FILE_NAME = "cache.json"


class DeckySettingsStore:
    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def read(self) -> dict[str, object]:
        self._manager.read()
        return {
            "auto_sync_enabled": self._manager.getSetting("auto_sync_enabled", False),
            "selected_game": self._manager.getSetting("selected_game", ""),
            "notifications": self._manager.getSetting(
                "notifications", dict(DEFAULT_NOTIFICATION_SETTINGS)
            ),
            "update_channel": self._manager.getSetting("update_channel", "stable"),
            "automatic_update_checks": self._manager.getSetting("automatic_update_checks", True),
            "debug_logging": self._manager.getSetting("debug_logging", True),
        }

    def write(self, settings: dict[str, object]) -> None:
        for key, value in settings.items():
            self._manager.setSetting(key, value)
        self._manager.commit()


class Plugin:
    """
    The main entry point for the SDH-ludusavi Decky Loader plugin.

    This class handles the lifecycle events triggered by Decky Loader
    (like `_main`, `_unload`, and `_migration`) and provides an asynchronous
    RPC wrapper around the synchronous `SDHLudusaviService` for the frontend.
    """

    def __init__(self) -> None:
        self._backend: SDHLudusaviService | None = None
        self._backend_lock = threading.Lock()
        # Daemon workers: an in-flight RPC must never keep the old plugin
        # process alive after Decky's SystemExit during update/unload.
        self._executor = DaemonThreadPool(max_workers=4, thread_name_prefix="sdh-rpc")

    def _service(self) -> SDHLudusaviService:
        if self._backend is None:
            with self._backend_lock:
                if self._backend is None:
                    self._backend = SDHLudusaviService(
                        settings_store=_settings_store(),
                        cache_path=_cache_path(),
                    )
        return self._backend

    async def get_settings(self) -> dict[str, Any]:
        return await self._call("get_settings", lambda: self._service().get_settings())

    async def get_game_history(self) -> dict[str, dict[str, Any]]:
        return await self._call("get_game_history", lambda: self._service().get_game_history())

    async def set_auto_sync_enabled(self, enabled: bool) -> dict[str, Any]:
        return await self._call(
            "set_auto_sync_enabled", lambda: self._service().set_auto_sync_enabled(enabled)
        )

    async def set_selected_game(self, game_name: str) -> dict[str, Any]:
        return await self._call(
            "set_selected_game", lambda: self._service().set_selected_game(game_name)
        )

    async def set_notification_settings(self, settings: dict[str, object]) -> dict[str, Any]:
        return await self._call(
            "set_notification_settings",
            lambda: self._service().set_notification_settings(settings),
        )

    async def set_debug_logging(self, enabled: bool) -> dict[str, Any]:
        return await self._call(
            "set_debug_logging", lambda: self._service().set_debug_logging(enabled)
        )

    async def set_update_channel(self, channel: str) -> dict[str, Any]:
        return await self._call(
            "set_update_channel", lambda: self._service().set_update_channel(channel)
        )

    async def set_automatic_update_checks(self, enabled: bool) -> dict[str, Any]:
        return await self._call(
            "set_automatic_update_checks",
            lambda: self._service().set_automatic_update_checks(enabled),
        )

    async def get_update_check_context(self) -> dict[str, Any]:
        return await self._call(
            "get_update_check_context", lambda: self._service().get_update_check_context()
        )

    async def confirm_update_install_handoff(self, version: str) -> dict[str, Any]:
        return await self._call(
            "confirm_update_install_handoff",
            lambda: self._service().confirm_update_install_handoff(version),
        )

    async def start_syncthing_activity_watch(
        self, phase: str, game_name: str | None = None, app_id: str | None = None
    ) -> dict[str, Any]:
        return await self._call(
            "start_syncthing_activity_watch",
            lambda: self._service().start_syncthing_activity_watch(phase, game_name, app_id),
        )

    async def get_syncthing_activity(self, watch_id: str) -> dict[str, Any]:
        return await self._call(
            "get_syncthing_activity",
            lambda: self._service().get_syncthing_activity(watch_id),
        )

    async def stop_syncthing_activity_watch(self, watch_id: str) -> dict[str, Any]:
        return await self._call(
            "stop_syncthing_activity_watch",
            lambda: self._service().stop_syncthing_activity_watch(watch_id),
        )

    async def clear_pending_update_install(self, version: str | None = None) -> dict[str, Any]:
        return await self._call(
            "clear_pending_update_install",
            lambda: self._service().clear_pending_update_install(version),
        )

    async def check_for_plugin_update(
        self, current_version: str, force: bool = False
    ) -> dict[str, Any]:
        return await self._call(
            "check_for_plugin_update",
            lambda: self._service().check_for_plugin_update(current_version, force),
        )

    async def revalidate_plugin_update(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            "revalidate_plugin_update",
            lambda: self._service().revalidate_plugin_update(candidate),
        )

    async def record_update_install_requested(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            "record_update_install_requested",
            lambda: self._service().record_update_install_requested(candidate),
        )

    async def get_ludusavi_launcher_shortcut_id(self) -> int:
        result = await self._call(
            "get_ludusavi_launcher_shortcut_id",
            lambda: self._service().get_ludusavi_launcher_shortcut_id(),
        )
        # bool is an int subclass; exclude it explicitly. -1 == "no shortcut".
        if isinstance(result, int) and not isinstance(result, bool):
            return result
        return -1

    async def set_ludusavi_launcher_shortcut_id(self, app_id: int) -> bool:
        return await self._call(
            "set_ludusavi_launcher_shortcut_id",
            lambda: self._service().set_ludusavi_launcher_shortcut_id(app_id),
        )

    async def clear_ludusavi_launcher_shortcut_id(self) -> bool:
        return await self._call(
            "clear_ludusavi_launcher_shortcut_id",
            lambda: self._service().clear_ludusavi_launcher_shortcut_id(),
        )

    async def get_ludusavi_command(self) -> dict[str, Any] | None:
        return await self._call(
            "get_ludusavi_command", lambda: self._service().get_ludusavi_command()
        )

    async def pause_game_process(self, pid: int) -> dict[str, object]:
        return await self._call(
            "pause_game_process", lambda: self._service().pause_game_process(pid)
        )

    async def resume_game_process(self, pid: int) -> dict[str, object]:
        return await self._call(
            "resume_game_process", lambda: self._service().resume_game_process(pid)
        )

    async def log(
        self,
        level: str,
        message: str,
        operation: str | None = None,
        game_name: str | None = None,
    ) -> None:
        """
        Route frontend logs to the backend service.

        Stays on the event loop intentionally: this is the hottest RPC and the
        work is an in-memory ring-buffer append. It must therefore never be the
        call that *constructs* the service (disk I/O); before construction,
        fall back to decky's logger directly.
        """
        backend = self._backend
        if backend is None:
            decky.logger.info(f"[frontend:{level}] {operation or 'frontend'}: {message}")
            return
        backend.log(level, message, operation, game_name)

    async def refresh_games(
        self, force: bool = False, installed_app_ids: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "refresh_games", lambda: self._service().refresh_games(force, installed_app_ids)
        )

    async def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
        result = await self._call(
            "is_game_cache_current",
            lambda: self._service().is_game_cache_current(installed_app_ids),
        )
        # _call converts failures to status dicts; the frontend expects a bare
        # boolean. False is the safe default: it triggers a refresh.
        return result if isinstance(result, bool) else False

    async def handle_game_start(
        self, game_name: str, app_id: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "handle_game_start",
            lambda: self._service().handle_game_start(game_name, app_id),
        )

    async def check_game_start(
        self, game_name: str, app_id: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "check_game_start",
            lambda: self._service().check_game_start(game_name, app_id),
        )

    async def restore_game_on_start(
        self, game_name: str, app_id: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "restore_game_on_start",
            lambda: self._service().restore_game_on_start(game_name, app_id),
        )

    async def resolve_game_start_conflict(
        self, game_name: str, app_id: str | None = None, resolution: str = ""
    ) -> dict[str, object]:
        return await self._call(
            "resolve_game_start_conflict",
            lambda: self._service().resolve_game_start_conflict(game_name, app_id, resolution),
        )

    async def handle_game_exit(
        self, game_name: str, app_id: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "handle_game_exit",
            lambda: self._service().handle_game_exit(game_name, app_id),
        )

    async def check_game_exit(self, game_name: str, app_id: str | None = None) -> dict[str, object]:
        return await self._call(
            "check_game_exit",
            lambda: self._service().check_game_exit(game_name, app_id),
        )

    async def backup_game_on_exit(
        self, game_name: str, app_id: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "backup_game_on_exit",
            lambda: self._service().backup_game_on_exit(game_name, app_id),
        )

    async def force_backup(self, game_name: str) -> dict[str, object]:
        return await self._call("force_backup", lambda: self._service().force_backup(game_name))

    async def force_restore(self, game_name: str) -> dict[str, object]:
        return await self._call("force_restore", lambda: self._service().force_restore(game_name))

    async def list_backups(self, game_name: str) -> dict[str, Any]:
        return await self._call("list_backups", lambda: self._service().list_backups(game_name))

    async def restore_backup_version(self, game_name: str, backup_id: str) -> dict[str, Any]:
        return await self._call(
            "restore_backup_version",
            lambda: self._service().restore_backup_version(game_name, backup_id),
        )

    async def get_versions(self) -> dict[str, str] | dict[str, object]:
        return await self._call("get_versions", lambda: self._service().get_versions())

    async def get_operation_status(self) -> dict[str, object]:
        result = await self._call(
            "get_operation_status", lambda: self._service().get_operation_status()
        )
        if isinstance(result, dict) and "is_running" in result:
            return result
        # Failure/skip dicts from _call lack "is_running"; return an idle state
        # matching coordinator.OperationState() defaults.
        return {
            "is_running": False,
            "name": None,
            "game_name": None,
            "last_result": None,
            "last_error": None,
        }

    async def get_recent_logs(self) -> list[dict[str, object]]:
        result = await self._call("get_recent_logs", lambda: self._service().get_recent_logs())
        return result if isinstance(result, list) else []

    async def get_ludusavi_logs(self) -> str:
        return await self._call("get_ludusavi_logs", lambda: self._service().get_ludusavi_logs())

    async def _main(self) -> None:
        decky.logger.info("SDH-ludusavi backend loaded")

        # Decky's import race can leave an orphaned older backend running
        # after an update; the newest instance is the one Decky owns, so it
        # cleans up strictly-older siblings before touching shared state.
        await self._call("enforce_single_instance", lambda: enforce_single_instance(decky.logger))

        init_result = await self._call("startup_init", self._service)
        if isinstance(init_result, dict) and init_result.get("status") == "failed":
            decky.logger.error(
                "Service initialization failed during startup: %s",
                init_result.get("message"),
            )
            return

        try:
            from sdh_ludusavi._version import resolve_version
        except Exception:
            decky.logger.exception("Failed to import version resolver on startup")
            return

        reconcile_result = await self._call(
            "reconcile_pending_update_install",
            lambda: self._service().reconcile_pending_update_install(resolve_version()),
        )
        if isinstance(reconcile_result, dict) and reconcile_result.get("status") == "failed":
            decky.logger.error(
                "Failed to reconcile pending update install on startup: %s",
                reconcile_result.get("message"),
            )

    async def _unload(self) -> None:
        backend = self._backend
        has_pending = False
        if backend is not None:
            has_pending = getattr(backend, "has_pending_update_install", lambda: False)()

            log_fn = getattr(backend, "log", None)
            if log_fn is not None:
                backend.log("info", f"Unload started (pending_update={has_pending})")
            else:
                decky.logger.info(f"Unload started (pending_update={has_pending})")
        else:
            decky.logger.info("Unload started (no backend service)")

        try:
            if backend is not None:
                result = await self._call("unload_stop", backend.stop)
                if isinstance(result, dict) and result.get("status") == "failed":
                    decky.logger.warning(
                        "Offloaded unload stop failed; falling back to synchronous stop"
                    )
                    try:
                        backend.stop()
                    # Intentionally broad
                    except Exception:
                        decky.logger.exception("Synchronous unload stop fallback failed")
        except asyncio.CancelledError:
            if backend is not None:
                decky.logger.warning("Unload stop was cancelled; falling back to synchronous stop")
                try:
                    backend.stop()
                # Intentionally broad
                except Exception:
                    decky.logger.exception("Synchronous unload stop fallback failed")
            raise
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)
            log_fn = getattr(backend, "log", None) if backend is not None else None
            if log_fn is not None:
                backend.log("info", "Unload ended")
            else:
                decky.logger.info("Unload ended")
            decky.logger.info("SDH-ludusavi backend unloaded")

    async def _uninstall(self) -> None:
        decky.logger.info("SDH-ludusavi backend uninstalled")

    async def _migration(self) -> None:
        decky.logger.info("SDH-ludusavi migration skipped; no legacy paths to migrate")

    async def _call(self, operation: str, callback: Any) -> Any:
        """
        Execute a synchronous service method in a background thread to prevent
        blocking the Decky Loader async event loop.

        Args:
            operation: A descriptive name for the operation (used in logs).
            callback: The synchronous function to execute.

        Returns:
            The result of the callback, or a dictionary containing error details
            if the operation failed or was blocked by the service lock.
        """
        try:
            return await _run_blocking(self._executor, callback)
        except OperationLockedError as exc:
            decky.logger.info("%s skipped: %s", operation, exc)
            return {"status": "skipped", "reason": "operation_running", "message": str(exc)}
        except Exception as exc:
            decky.logger.exception("%s failed", operation)
            return {"status": "failed", "message": str(exc)}
        except asyncio.CancelledError:
            raise
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            decky.logger.exception("%s failed", operation)
            return {"status": "failed", "message": str(exc)}


def _decky_directory(name: str) -> Path:
    value = getattr(decky, name, None) or os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for SDH-ludusavi storage")
    path = Path(str(value))
    _ensure_private_directory(path)
    return path


def _settings_store() -> DeckySettingsStore:
    from settings import SettingsManager

    settings_dir = _decky_directory("DECKY_PLUGIN_SETTINGS_DIR")
    manager = SettingsManager(name="settings", settings_directory=str(settings_dir))
    return DeckySettingsStore(manager)


def _cache_path() -> Path:
    return _decky_directory("DECKY_PLUGIN_RUNTIME_DIR") / CACHE_FILE_NAME


def _ensure_private_directory(path: Path) -> None:
    """
    Create a directory with strict 0700 permissions to protect sensitive
    plugin data.
    """
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)


async def _run_blocking(executor: Executor, callback: Any) -> Any:
    """
    Run a synchronous callback on the shared RPC executor without blocking
    the event loop. Cancelling the awaiting coroutine cannot interrupt a
    callback that is already running; the work finishes in the background
    and its result is discarded.
    """
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    try:
        return await loop.run_in_executor(executor, functools.partial(context.run, callback))
    except asyncio.CancelledError:
        decky.logger.warning(
            "SDH-ludusavi operation was cancelled while worker may still be running"
        )
        raise
