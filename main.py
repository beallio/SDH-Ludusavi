from __future__ import annotations

import asyncio
import contextvars
import os
from pathlib import Path
import threading
from typing import Any

import decky

from sdh_ludusavi.service import OperationLockedError, SDHLudusaviService

STATE_FILE_NAME = "sdh_ludusavi.json"


class Plugin:
    def __init__(self) -> None:
        self._backend: SDHLudusaviService | None = None
        self._backend_lock = threading.Lock()

    def _service(self) -> SDHLudusaviService:
        if self._backend is None:
            with self._backend_lock:
                if self._backend is None:
                    self._backend = SDHLudusaviService(state_path=_state_path())
        return self._backend

    async def get_settings(self) -> dict[str, bool]:
        return self._service().get_settings()

    async def set_auto_sync_enabled(self, enabled: bool) -> dict[str, bool]:
        return self._service().set_auto_sync_enabled(enabled)

    async def refresh_games(self, force: bool = False) -> dict[str, object]:
        return await self._call("refresh_games", lambda: self._service().refresh_games(force))

    async def handle_game_start(
        self, game_name: str, app_id: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "handle_game_start",
            lambda: self._service().handle_game_start(game_name, app_id),
        )

    async def handle_game_exit(
        self, game_name: str, app_id: str | None = None
    ) -> dict[str, object]:
        return await self._call(
            "handle_game_exit",
            lambda: self._service().handle_game_exit(game_name, app_id),
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

    async def _main(self) -> None:
        decky.logger.info("SDH-ludusavi backend loaded")
        self._service()

    async def _unload(self) -> None:
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


def _state_path() -> Path:
    settings_dir = getattr(
        decky, "DECKY_PLUGIN_SETTINGS_DIR", getattr(decky, "DECKY_SETTINGS_DIR", None)
    )
    if not settings_dir:
        settings_dir = os.environ.get("DECKY_PLUGIN_SETTINGS_DIR") or os.environ.get(
            "DECKY_SETTINGS_DIR"
        )

    if settings_dir:
        return Path(settings_dir) / STATE_FILE_NAME

    fallback_path = _fallback_state_path()
    decky.logger.warning(
        "DECKY_PLUGIN_SETTINGS_DIR is unavailable; storing SDH-ludusavi settings at %s",
        fallback_path,
    )
    return fallback_path


def _fallback_state_path() -> Path:
    candidates: list[Path] = []
    decky_user_home = getattr(decky, "DECKY_USER_HOME", None) or os.environ.get("DECKY_USER_HOME")
    if decky_user_home:
        candidates.append(Path(decky_user_home))

    home = Path.home()
    if home not in candidates:
        candidates.append(home)

    for user_home in candidates:
        config_dir = user_home / ".config" / "sdh-ludusavi"
        try:
            _ensure_private_directory(config_dir)
        except OSError as exc:
            decky.logger.warning(
                "Unable to use SDH-ludusavi settings fallback %s: %s",
                config_dir,
                exc,
            )
            continue
        return config_dir / STATE_FILE_NAME

    raise RuntimeError("Unable to resolve an SDH-ludusavi settings path")


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)


async def _run_blocking(callback: Any) -> Any:
    context = contextvars.copy_context()
    complete = threading.Event()
    value: Any = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal error, value
        try:
            value = context.run(callback)
        except BaseException as exc:
            error = exc
        finally:
            complete.set()

    thread = threading.Thread(target=runner, name="sdh-ludusavi-worker", daemon=True)
    thread.start()
    while not complete.is_set():
        await asyncio.sleep(0.01)
    thread.join()
    if error is not None:
        raise error
    return value
