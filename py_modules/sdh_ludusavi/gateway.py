from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from ._version import resolve_version
from .types import LudusaviAdapter

LOGGER = logging.getLogger("sdh_ludusavi.service.gateway")


class LudusaviGateway:
    """Manages the lifecycle of the Ludusavi adapter, caching version info,

    discovering the launcher command, and reading log outputs.
    """

    def __init__(
        self,
        service: Any,
        adapter: LudusaviAdapter | None = None,
        adapter_factory: Callable[[], LudusaviAdapter] | None = None,
    ) -> None:
        self._service = service
        self._adapter = adapter or getattr(service, "_adapter", None)
        self._adapter_lock = getattr(service, "_adapter_lock", None) or threading.Lock()
        self._adapter_factory = (
            adapter_factory
            or getattr(service, "_adapter_factory", None)
            or _default_adapter_factory
        )
        self._versions: dict[str, str] | None = None
        self._ludusavi_command: dict[str, object] | None = None

    def get_adapter(self) -> LudusaviAdapter:
        """Lazily initialize and return the Ludusavi adapter."""
        if self._adapter is None:
            with self._adapter_lock:
                if self._adapter is None:
                    self._adapter = self._adapter_factory()
                    self._service._log_ludusavi_diagnostics(self._adapter)
        if not self._service._diagnostics_logged:
            with self._adapter_lock:
                if not self._service._diagnostics_logged:
                    self._service._log_ludusavi_diagnostics(self._adapter)
        if self._adapter is None:
            raise RuntimeError("Ludusavi adapter factory returned None")
        return self._adapter

    def get_versions(self) -> dict[str, str]:
        """Fetch and cache version information for Ludusavi and the plugin."""
        if self._versions is not None:
            return self._versions

        adapter = self.get_adapter()
        versions = dict(adapter.get_versions())
        versions["sdh_ludusavi"] = resolve_version()
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
            from .constants import CONFIG_MARKER_READ_FAILED

            return CONFIG_MARKER_READ_FAILED


def _decky_version() -> str:
    env_version = os.environ.get("DECKY_VERSION")
    if env_version:
        return env_version
    try:
        import decky
    except ImportError:
        return "unknown"
    return str(getattr(decky, "__version__", "unknown"))


def _default_adapter_factory() -> LudusaviAdapter:
    from .ludusavi import PyludusaviAdapter

    return PyludusaviAdapter()
