from __future__ import annotations

import asyncio
import contextvars
import os
from pathlib import Path
import threading
from typing import Any

import decky

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

    async def get_ludusavi_launcher_shortcut_id(self) -> int:
        return self._service().get_ludusavi_launcher_shortcut_id()

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
        """
        self._service().log(level, message, operation, game_name)

    async def refresh_games(
        self, force: bool = False, installed_app_ids: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "refresh_games", lambda: self._service().refresh_games(force, installed_app_ids)
        )

    async def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
        return self._service().is_game_cache_current(installed_app_ids)

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

    async def get_versions(self) -> dict[str, str] | dict[str, object]:
        return await self._call("get_versions", self._service().get_versions)

    async def get_operation_status(self) -> dict[str, object]:
        return self._service().get_operation_status()

    async def get_recent_logs(self) -> list[dict[str, object]]:
        return self._service().get_recent_logs()

    async def get_ludusavi_logs(self) -> str:
        return await self._call("get_ludusavi_logs", lambda: self._service().get_ludusavi_logs())

    async def _main(self) -> None:
        decky.logger.info("SDH-ludusavi backend loaded")
        self._service()

    async def _unload(self) -> None:
        if self._backend is not None:
            self._backend.resume_all_paused_processes()
        decky.logger.info("SDH-ludusavi backend unloaded")

    async def _uninstall(self) -> None:
        decky.logger.info("SDH-ludusavi backend uninstalled")

    async def _migration(self) -> None:
        decky.logger.info("Migrating SDH-ludusavi legacy paths")
        decky.migrate_logs(
            os.path.join(decky.DECKY_USER_HOME, ".config", "decky-template", "template.log"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "sdh-ludusavi", "plugin.log"),
        )
        decky.migrate_settings(
            os.path.join(decky.DECKY_HOME, "settings", "template.json"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "decky-template"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "sdh-ludusavi"),
        )
        decky.migrate_runtime(
            os.path.join(decky.DECKY_HOME, "template"),
            os.path.join(decky.DECKY_USER_HOME, ".local", "share", "decky-template"),
            os.path.join(decky.DECKY_USER_HOME, ".local", "share", "sdh-ludusavi"),
        )

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
            return await _run_blocking(callback)
        except OperationLockedError as exc:
            decky.logger.info("%s skipped: %s", operation, exc)
            return {"status": "skipped", "reason": "operation_running", "message": str(exc)}
        except Exception as exc:
            decky.logger.exception("%s failed", operation)
            return {"status": "failed", "message": str(exc)}
        except asyncio.CancelledError:
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


async def _run_blocking(callback: Any) -> Any:
    """
    Helper to run a synchronous callback in a dedicated thread while
    maintaining the async event loop's responsiveness.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    context = contextvars.copy_context()

    def set_result(payload: Any) -> None:
        if not future.cancelled():
            future.set_result(payload)

    def set_exception(exc: BaseException) -> None:
        if not future.cancelled():
            future.set_exception(exc)

    def signal_completion(callback: Any, payload: Any) -> None:
        if loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(callback, payload)
        except RuntimeError:
            return

    def worker() -> None:
        try:
            result = context.run(callback)
        except BaseException as exc:
            signal_completion(set_exception, exc)
            return
        signal_completion(set_result, result)

    threading.Thread(target=worker, name="sdh-ludusavi-worker", daemon=True).start()

    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        decky.logger.warning(
            "SDH-ludusavi operation was cancelled while worker may still be running"
        )
        raise
