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
            "update_channel": self._manager.getSetting("update_channel", "stable"),
            "automatic_update_checks": self._manager.getSetting("automatic_update_checks", True),
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

    async def clear_pending_update_install(self, version: str | None = None) -> dict[str, Any]:
        return await self._call(
            "clear_pending_update_install",
            lambda: self._service().clear_pending_update_install(version),
        )

    async def check_for_plugin_update(
        self, current_version: str, force: bool = False
    ) -> dict[str, Any]:
        def do_check() -> dict[str, Any]:
            service = self._service()
            import datetime
            import time

            t0 = time.monotonic()
            service.log("info", f"Update check started (version={current_version}, force={force})")

            if service._update_rate_limited_until:
                if (
                    datetime.datetime.now(datetime.timezone.utc)
                    < service._update_rate_limited_until
                ):
                    elapsed_ms = round((time.monotonic() - t0) * 1000)
                    service.log(
                        "warning",
                        f"Update check blocked by rate-limit cooldown until {service._update_rate_limited_until.isoformat()}, elapsed_ms={elapsed_ms}",
                    )
                    return {
                        "status": "failed",
                        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "message": "Rate limit cooldown active",
                        "retry_after": service._update_rate_limited_until.isoformat(),
                    }
                else:
                    service._update_rate_limited_until = None

            if not force:
                last_checked_at_str = service._update_check_cache.get("last_checked_at")
                last_checked_channel = service._update_check_cache.get("last_checked_channel")
                last_checked_version = service._update_check_cache.get("last_checked_version")
                if last_checked_at_str:
                    try:
                        last_checked_at = datetime.datetime.fromisoformat(last_checked_at_str)
                        age_ok = datetime.datetime.now(
                            datetime.timezone.utc
                        ) - last_checked_at < datetime.timedelta(hours=24)
                        channel_ok = last_checked_channel == service._update_channel
                        version_ok = last_checked_version == current_version
                        if age_ok and channel_ok and version_ok:
                            last_result = service._update_check_cache.get("last_result")
                            if last_result:
                                elapsed_ms = round((time.monotonic() - t0) * 1000)
                                service.log(
                                    "info",
                                    f"Update check cache hit (within 24h, channel={last_checked_channel}, version={last_checked_version}), elapsed_ms={elapsed_ms}",
                                )
                                return last_result

                        bypassed_reasons = []
                        if not age_ok:
                            bypassed_reasons.append("expired")
                        if not channel_ok:
                            bypassed_reasons.append(
                                f"channel mismatch (requested={service._update_channel}, cached={last_checked_channel})"
                            )
                        if not version_ok:
                            bypassed_reasons.append(
                                f"version mismatch (requested={current_version}, cached={last_checked_version})"
                            )
                        service.log(
                            "info", f"Update check cache bypassed: {', '.join(bypassed_reasons)}"
                        )
                    except Exception as e:
                        service.log("warning", f"Failed to parse or validate update cache: {e}")

            from sdh_ludusavi.updater import check_for_update

            res = check_for_update(current_version, service._update_channel, service=service)
            if res.get("status") in ("available", "current"):
                res["checked_version"] = current_version
            service.record_update_check_result(res)
            if res.get("status") in ("available", "current"):
                service._update_check_cache["last_result"] = res
                service._save_state()
            return res

        return await self._call("check_for_plugin_update", do_check)

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
        service = self._service()
        try:
            from sdh_ludusavi._version import resolve_version

            service.reconcile_pending_update_install(resolve_version())
        except Exception:
            decky.logger.exception("Failed to reconcile pending update install on startup")

    async def _unload(self) -> None:
        backend = self._backend
        has_pending = False
        if backend is not None:
            state_lock = getattr(backend, "_state_lock", None)
            cache = getattr(backend, "_update_check_cache", None)
            if state_lock is not None and cache is not None:
                with state_lock:
                    has_pending = cache.get("pending_update_install") is not None

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
    future: asyncio.Future[Any] = loop.create_future()
    context = contextvars.copy_context()
    read_fd, write_fd = os.pipe()
    completion: tuple[str, Any] | None = None
    completion_lock = threading.Lock()
    reader_registered = False
    thread_started = False
    read_fd_closed = False

    def close_fd(fd: int) -> None:
        try:
            os.close(fd)
        except OSError:
            return

    def close_read_fd() -> None:
        nonlocal read_fd_closed
        if read_fd_closed:
            return
        read_fd_closed = True
        close_fd(read_fd)

    def remove_reader_if_active() -> None:
        if loop.is_closed() or not loop.is_running():
            return
        try:
            loop.remove_reader(read_fd)
        except (OSError, RuntimeError):
            return

    def read_completion_signal() -> None:
        remove_reader_if_active()
        if not read_fd_closed:
            try:
                os.read(read_fd, 1)
            except OSError:
                pass
            close_read_fd()
        with completion_lock:
            completed = completion
        if future.done() or completed is None:
            return
        kind, payload = completed
        if kind == "error":
            future.set_exception(payload)
            return
        future.set_result(payload)

    def worker() -> None:
        nonlocal completion
        try:
            result = context.run(callback)
        except BaseException as error:
            completed = ("error", error)
        else:
            completed = ("result", result)
        with completion_lock:
            completion = completed
        try:
            os.write(write_fd, b"x")
        except OSError:
            pass
        finally:
            close_fd(write_fd)

    try:
        loop.add_reader(read_fd, read_completion_signal)
        reader_registered = True
        thread = threading.Thread(target=worker, name="sdh-ludusavi-worker", daemon=True)
        thread.start()
        thread_started = True
    except BaseException:
        if reader_registered:
            remove_reader_if_active()
        close_read_fd()
        if not thread_started:
            close_fd(write_fd)
        future.cancel()
        raise

    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        decky.logger.warning(
            "SDH-ludusavi operation was cancelled while worker may still be running"
        )
        remove_reader_if_active()
        close_read_fd()
        future.cancel()
        raise
