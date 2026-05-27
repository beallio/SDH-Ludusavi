from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from ._version import resolve_version
from .service import LudusaviAdapter

LOGGER = logging.getLogger("sdh_ludusavi.service.gateway")


class LudusaviGateway:
    """Manages the lifecycle of the Ludusavi adapter, caching version info,

    discovering the launcher command, and reading log outputs.
    """

    def __init__(self, service: Any) -> None:
        self._service = service
        self._versions: dict[str, str] | None = None
        self._ludusavi_command: dict[str, object] | None = None

    @property
    def _adapter(self) -> LudusaviAdapter | None:
        return self._service._adapter

    @_adapter.setter
    def _adapter(self, val: LudusaviAdapter | None) -> None:
        self._service._adapter = val

    @property
    def _adapter_lock(self) -> threading.Lock:
        return self._service._adapter_lock

    @property
    def _adapter_factory(self) -> Callable[[], LudusaviAdapter]:
        return self._service._adapter_factory

    @_adapter_factory.setter
    def _adapter_factory(self, val: Callable[[], LudusaviAdapter]) -> None:
        self._service._adapter_factory = val

    @property
    def _diagnostics_logged(self) -> bool:
        return self._service._diagnostics_logged

    @_diagnostics_logged.setter
    def _diagnostics_logged(self, val: bool) -> None:
        self._service._diagnostics_logged = val

    def get_adapter(self) -> LudusaviAdapter:
        """Lazily initialize and return the Ludusavi adapter."""
        if self._adapter is None:
            with self._adapter_lock:
                if self._adapter is None:
                    self._adapter = self._adapter_factory()
                    self._service._log_ludusavi_diagnostics(self._adapter)
        if not self._diagnostics_logged:
            with self._adapter_lock:
                if not self._diagnostics_logged:
                    self._service._log_ludusavi_diagnostics(self._adapter)
        assert self._adapter is not None
        return self._adapter

    def get_versions(self) -> dict[str, str]:
        """Fetch and cache version information for Ludusavi and the plugin."""
        if self._versions is not None:
            return self._versions

        adapter = self.get_adapter()
        versions = dict(adapter.get_versions())
        import sys

        svc = sys.modules.get("sdh_ludusavi.service")
        resolve_fn = getattr(svc, "resolve_version", resolve_version)
        versions["sdh_ludusavi"] = resolve_fn()
        versions["decky"] = _decky_version()

        if "pyludusavi" not in versions:
            try:
                import pyludusavi

                versions["pyludusavi"] = getattr(pyludusavi, "__version__", "unknown")
            except ImportError:
                versions["pyludusavi"] = "unknown"

        self._versions = versions
        return versions

    def get_logs(self) -> str:
        """Read and return the contents of the Ludusavi log file."""
        return self.get_adapter().get_log_contents()

    def get_diagnostics(self) -> dict[str, object]:
        """Get diagnostics dict from the adapter."""
        return self.get_adapter().get_diagnostics()

    def get_ludusavi_command(self) -> dict[str, object] | None:
        """Return the command path and args used by the plugin for GUI launching."""
        if self._ludusavi_command is not None:
            args = self._ludusavi_command.get("args", [])
            return {
                "commandPath": str(self._ludusavi_command["commandPath"]),
                "args": list(args) if isinstance(args, list) else [],
                "compatTool": str(self._ludusavi_command["compatTool"]),
            }

        from pyludusavi.discovery import LudusaviNotFoundError, find_ludusavi
        from .ludusavi import FLATPAK_ID, _ludusavi_env

        try:
            prefix = find_ludusavi(explicit_flatpak_id=FLATPAK_ID, env=_ludusavi_env())
        except LudusaviNotFoundError:
            return None

        if not prefix:
            return None

        command: dict[str, object] = {
            "commandPath": prefix[0],
            "args": list(prefix[1:]),
            "compatTool": "",
        }
        self._ludusavi_command = command
        args = command["args"]
        return {
            "commandPath": str(command["commandPath"]),
            "args": list(args) if isinstance(args, list) else [],
            "compatTool": str(command["compatTool"]),
        }

    def current_config_mtime_ns(self) -> int | None | object:
        """Return the current modification time of Ludusavi config or marker."""
        try:
            return self.get_adapter().get_config_mtime_ns()
        except Exception as exc:
            self._service.log(
                "debug",
                f"Unable to read Ludusavi config marker; forcing refresh: {exc}",
                "refresh",
            )
            from .service import _CONFIG_MARKER_READ_FAILED

            return _CONFIG_MARKER_READ_FAILED

    def _log_ludusavi_diagnostics(self, adapter: LudusaviAdapter) -> None:
        if self._diagnostics_logged:
            return
        self._diagnostics_logged = True

        def run() -> None:
            try:
                diagnostics = adapter.get_diagnostics()
            except Exception as exc:
                self._service.log("debug", f"Ludusavi diagnostics unavailable: {exc}", "init")
                return

            version = diagnostics.get("version", "unknown")
            ludusavi_type = diagnostics.get("type", "unknown")
            path = diagnostics.get("path", "unknown")
            config_path = diagnostics.get("configPath", "unknown")
            backup_path = diagnostics.get("backupPath", "unknown")
            self._service.log("info", f"Ludusavi version: {version}", "init")
            self._service.log("info", f"Ludusavi type/path: {ludusavi_type} {path}", "init")
            self._service.log("info", f"Ludusavi config path: {config_path}", "init")
            self._service.log("info", f"Ludusavi backup path: {backup_path}", "init")

        threading.Thread(target=run, daemon=True).start()


def _decky_version() -> str:
    env_version = os.environ.get("DECKY_VERSION")
    if env_version:
        return env_version
    try:
        import decky
    except ImportError:
        return "unknown"
    return str(getattr(decky, "__version__", "unknown"))
