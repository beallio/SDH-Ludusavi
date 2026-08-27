from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .ludusavi_executor import LudusaviOperationCancelledError

LOGGER = logging.getLogger("sdh_ludusavi.service.coordinator")


class OperationLockedError(RuntimeError):
    """Raised when a global Ludusavi operation is already running."""


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


class OperationCoordinator:
    """Coordinates locks and status tracking for executing exclusive operations

    (such as backup, restore, check) on the Ludusavi adapter.
    """

    def __init__(self) -> None:
        self._operation = OperationState()
        self._operation_lock = threading.Lock()

    def run_locked(
        self,
        operation: str,
        game_name: str | None,
        callback: Callable[[], Any],
        log_callback: Callable[[str, str, str | None, str | None], None] | None = None,
        *,
        wait_timeout_seconds: float | None = None,
    ) -> Any:
        """Execute a callback while holding the operation lock, ensuring exclusive access.

        Calls remain fail-fast by default. Lifecycle checks may opt into a bounded
        wait so they can make a fresh decision after an active operation finishes.
        """

        def log(level: str, msg: str) -> None:
            if log_callback:
                log_callback(level, msg, operation, game_name)

        if wait_timeout_seconds is None:
            acquired = self._operation_lock.acquire(blocking=False)
        else:
            acquired = self._operation_lock.acquire(timeout=wait_timeout_seconds)
        if not acquired:
            raise OperationLockedError(f"{self._operation.name or 'operation'} is already running")

        log("info", f"Starting {operation}")
        self._operation.is_running = True
        self._operation.name = operation
        self._operation.game_name = game_name
        self._operation.last_error = None
        try:
            result = callback()
        except LudusaviOperationCancelledError:
            self._operation.last_result = "cancelled"
            self._operation.last_error = None
            log("debug", f"{operation} cancelled")
            raise
        # Intentionally broad: catch all exceptions to update operation status
        except Exception as exc:
            self._operation.last_error = str(exc)
            self._operation.last_result = "failed"
            log("error", f"{operation} failed: {exc}")
            raise
        else:
            self._operation.last_result = "ok"
            return result
        finally:
            self._operation.is_running = False
            self._operation.name = None
            self._operation.game_name = None
            self._operation_lock.release()

    def get_status(self) -> dict[str, object]:
        """Return information about the currently running or last completed operation."""
        return self._operation.to_dict()

    @property
    def is_running(self) -> bool:
        """Return True if an operation is currently active."""
        return self._operation.is_running
