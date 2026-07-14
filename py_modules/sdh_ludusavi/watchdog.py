from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .constants import LAUNCH_GATE_LEASE_TTL_SECONDS, WATCHDOG_ABSOLUTE_RESUME_SECONDS
from .launch_gate import ScopeTransitionResult, SteamAppScope, SystemdScopeController


LOGGER = logging.getLogger("sdh_ludusavi.service.watchdog")
MAX_PID = 2_147_483_647
SHUTDOWN_THAW_ATTEMPTS = 3
SHUTDOWN_THAW_RETRY_SECONDS = 0.05


class _ScopeController(Protocol):
    def discover(self, pid: int) -> SteamAppScope: ...

    def freeze(self, scope: SteamAppScope) -> ScopeTransitionResult: ...

    def thaw(self, scope: SteamAppScope) -> ScopeTransitionResult: ...

    def freeze_requested(self, scope: SteamAppScope) -> bool: ...

    def wait_for_frozen(self, scope: SteamAppScope, expected: bool) -> ScopeTransitionResult: ...


@dataclass
class _PauseLease:
    scope: SteamAppScope
    paused_at: float
    lease_id: str
    lease_deadline: float


class ProcessWatchdog:
    """Own renewable leases on verified frozen Steam application scopes."""

    def __init__(
        self,
        log_callback: Callable[[str, str, str | None, str | None], None],
        scope_controller: _ScopeController | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._log = log_callback
        self._scope_controller = scope_controller or SystemdScopeController()
        self._monotonic = monotonic
        self._paused_pids: dict[int, _PauseLease] = {}
        self._paused_pids_lock = threading.Lock()
        self._watchdog_active = False
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        # Scope transitions and lease generations are serialized per launch PID.
        # The state lock is never held while invoking systemd or waiting on cgroup state.
        self._pid_locks: dict[int, threading.Lock] = {}
        self._pid_locks_lock = threading.Lock()

    def _get_pid_lock(self, pid: int) -> threading.Lock:
        with self._pid_locks_lock:
            if pid not in self._pid_locks:
                self._pid_locks[pid] = threading.Lock()
            return self._pid_locks[pid]

    def pause(self, pid: int) -> dict[str, object]:
        """Freeze the launch PID's complete Steam app scope."""
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError as exc:
            self._log("warning", f"Invalid PID passed to pause: {exc}", "launch_gate", None)
            return {"status": "failed", "message": str(exc)}

        with self._get_pid_lock(valid_pid):
            try:
                scope = self._scope_controller.discover(valid_pid)
            # Intentionally broad: fail closed on any injected/runtime discovery failure.
            except Exception as exc:
                reason = _bounded_reason(exc)
                self._log(
                    "warning",
                    f"Unable to discover Steam app scope for root PID {valid_pid}: {reason}",
                    "launch_gate",
                    None,
                )
                return {"status": "failed", "pid": valid_pid, "message": reason}

            with self._paused_pids_lock:
                existing = self._paused_pids.get(valid_pid)

            if existing is not None and existing.scope == scope:
                verified = self._verified_frozen(scope)
                if not verified.success:
                    return self._pause_failure(valid_pid, verified.reason)
            else:
                if existing is not None:
                    released = self._scope_controller.thaw(existing.scope)
                    if not released.success:
                        return self._pause_failure(
                            valid_pid, f"Unable to thaw previous scope: {released.reason}"
                        )
                    self._remove_lease(valid_pid, existing)
                    self._log_thawed(existing.scope)

                frozen = self._scope_controller.freeze(scope)
                if not frozen.success:
                    return self._pause_failure(valid_pid, frozen.reason)

            lease_id = secrets.token_urlsafe(16)
            now = self._monotonic()
            paused_at = (
                existing.paused_at if existing is not None and existing.scope == scope else now
            )
            with self._paused_pids_lock:
                self._paused_pids[valid_pid] = _PauseLease(
                    scope=scope,
                    paused_at=paused_at,
                    lease_id=lease_id,
                    lease_deadline=now + LAUNCH_GATE_LEASE_TTL_SECONDS,
                )
            self._ensure_watchdog_running()
            self._log(
                "info",
                f"Froze Steam app scope {scope.unit} for root PID {valid_pid}",
                "launch_gate",
                None,
            )
            return {
                "status": "paused",
                "pid": valid_pid,
                "lease_id": lease_id,
                "lease_ttl_seconds": LAUNCH_GATE_LEASE_TTL_SECONDS,
            }

    def renew_pause(self, pid: int, lease_id: str) -> dict[str, object]:
        """Renew a matching lease while its stored scope remains frozen."""
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError as exc:
            self._log("warning", f"Invalid PID passed to renew: {exc}", "launch_gate", None)
            return {"status": "failed", "message": str(exc)}

        with self._get_pid_lock(valid_pid):
            with self._paused_pids_lock:
                lease = self._paused_pids.get(valid_pid)
            if lease is None:
                return self._lease_failure(valid_pid, "Process not paused")
            if lease.lease_id != lease_id:
                return self._lease_failure(valid_pid, "Lease ID mismatch")

            verified = self._verified_frozen(lease.scope)
            if not verified.success:
                return self._lease_failure(valid_pid, verified.reason)

            now = self._monotonic()
            with self._paused_pids_lock:
                current = self._paused_pids.get(valid_pid)
                if current is not lease or current.lease_id != lease_id:
                    return self._lease_failure(valid_pid, "Lease changed during renewal")
                current.lease_deadline = now + LAUNCH_GATE_LEASE_TTL_SECONDS
            return {
                "status": "renewed",
                "pid": valid_pid,
                "lease_ttl_seconds": LAUNCH_GATE_LEASE_TTL_SECONDS,
            }

    def resume(self, pid: int, lease_id: str | None = None) -> dict[str, object]:
        """Thaw the exact scope stored by a matching pause lease."""
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError as exc:
            self._log("warning", f"Invalid PID passed to resume: {exc}", "launch_gate", None)
            return {"status": "failed", "message": str(exc)}
        with self._get_pid_lock(valid_pid):
            return self._resume_locked(valid_pid, lease_id)

    def _resume_locked(self, valid_pid: int, lease_id: str | None = None) -> dict[str, object]:
        with self._paused_pids_lock:
            lease = self._paused_pids.get(valid_pid)
        if lease is None:
            return self._lease_failure(valid_pid, "Process not paused")
        if lease_id is not None and lease.lease_id != lease_id:
            return self._lease_failure(valid_pid, "Lease ID mismatch")

        thawed = self._scope_controller.thaw(lease.scope)
        if not thawed.success:
            reason = _bounded_reason(thawed.reason or "Unable to thaw Steam app scope")
            self._log(
                "warning",
                f"Unable to thaw Steam app scope {lease.scope.unit} for root PID "
                f"{valid_pid}: {reason}",
                "launch_gate",
                None,
            )
            return {"status": "failed", "pid": valid_pid, "message": reason}

        self._remove_lease(valid_pid, lease)
        self._log_thawed(lease.scope)
        return {"status": "resumed", "pid": valid_pid}

    def resume_all(self) -> None:
        """Best-effort thaw for plugin unload or launch-gate failures."""
        with self._paused_pids_lock:
            paused_pids = sorted(self._paused_pids)
        for pid in paused_pids:
            try:
                self.resume(pid)
            # Intentionally broad: one unload cleanup failure must not block other scopes.
            except Exception as exc:
                self._log(
                    "warning",
                    f"Unable to thaw scope for root PID {pid}: {_bounded_reason(exc)}",
                    "launch_gate",
                    None,
                )

    def stop(self) -> None:
        """Shut down the watchdog thread and thaw every tracked scope."""
        self._watchdog_stop.set()
        thread = self._watchdog_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        for attempt in range(1, SHUTDOWN_THAW_ATTEMPTS + 1):
            self.resume_all()
            with self._paused_pids_lock:
                retained = tuple(self._paused_pids.values())
            if not retained:
                return
            if attempt < SHUTDOWN_THAW_ATTEMPTS:
                time.sleep(SHUTDOWN_THAW_RETRY_SECONDS)
        units = _bounded_reason(", ".join(lease.scope.unit for lease in retained))
        self._log(
            "error",
            f"Shutdown left {len(retained)} Steam app scope lease(s) unconfirmed after "
            f"{SHUTDOWN_THAW_ATTEMPTS} thaw attempts: {units}",
            "launch_gate",
            None,
        )

    def _verified_frozen(self, scope: SteamAppScope) -> ScopeTransitionResult:
        if not self._scope_controller.freeze_requested(scope):
            return ScopeTransitionResult(False, "Steam app scope is no longer frozen")
        return self._scope_controller.wait_for_frozen(scope, expected=True)

    def _pause_failure(self, pid: int, reason: str) -> dict[str, object]:
        bounded = _bounded_reason(reason or "Unable to freeze Steam app scope")
        self._log(
            "warning",
            f"Unable to freeze Steam app scope for root PID {pid}: {bounded}",
            "launch_gate",
            None,
        )
        return {"status": "failed", "pid": pid, "message": bounded}

    def _lease_failure(self, pid: int, reason: str) -> dict[str, object]:
        self._log("warning", f"{reason} for root PID {pid}", "launch_gate", None)
        return {"status": "failed", "pid": pid, "message": reason}

    def _remove_lease(self, pid: int, lease: _PauseLease) -> None:
        with self._paused_pids_lock:
            if self._paused_pids.get(pid) is lease:
                self._paused_pids.pop(pid, None)

    def _log_thawed(self, scope: SteamAppScope) -> None:
        self._log(
            "info",
            f"Thawed Steam app scope {scope.unit} for root PID {scope.root_pid}",
            "launch_gate",
            None,
        )

    def _ensure_watchdog_running(self) -> None:
        with self._paused_pids_lock:
            if self._watchdog_active:
                return
            self._watchdog_active = True
            self._watchdog_stop.clear()
        thread = threading.Thread(
            target=self._watchdog_loop,
            name="sdh-ludusavi-watchdog",
            daemon=True,
        )
        self._watchdog_thread = thread
        thread.start()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(timeout=1.0):
            with self._paused_pids_lock:
                if not self._paused_pids:
                    self._watchdog_active = False
                    return
            self._check_and_resume_stuck_pids()
        with self._paused_pids_lock:
            self._watchdog_active = False

    def _check_and_resume_stuck_pids(self) -> None:
        now = self._monotonic()
        with self._paused_pids_lock:
            candidates = [
                (pid, lease.lease_id)
                for pid, lease in self._paused_pids.items()
                if _lease_expiry_reason(lease, now) is not None
            ]

        for pid, expected_lease_id in candidates:
            try:
                with self._get_pid_lock(pid):
                    now = self._monotonic()
                    with self._paused_pids_lock:
                        lease = self._paused_pids.get(pid)
                    if lease is None or lease.lease_id != expected_lease_id:
                        continue
                    reason = _lease_expiry_reason(lease, now)
                    if reason is None:
                        continue
                    frozen_for = now - lease.paused_at
                    self._log(
                        "warning",
                        f"Watchdog detected Steam app scope {lease.scope.unit} for root PID "
                        f"{pid} frozen for {frozen_for:.0f}s ({reason}). Thawing automatically.",
                        "watchdog",
                        None,
                    )
                    self._resume_locked(pid, expected_lease_id)
            # Intentionally broad: keep the background watchdog alive after one scope failure.
            except Exception as exc:
                self._log(
                    "error",
                    f"Watchdog failed to thaw scope for root PID {pid}: {_bounded_reason(exc)}",
                    "watchdog",
                    None,
                )


def _lease_expiry_reason(lease: _PauseLease, now: float) -> str | None:
    if now - lease.paused_at > WATCHDOG_ABSOLUTE_RESUME_SECONDS:
        return "absolute ceiling"
    if now > lease.lease_deadline:
        return "lease expired"
    return None


def _coerce_signal_pid(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("PID must be an integer, not a boolean")
    if isinstance(value, int):
        pid = value
    elif isinstance(value, str):
        try:
            pid = int(value.strip())
        except ValueError as exc:
            raise ValueError("PID must be a valid integer string") from exc
    elif isinstance(value, float):
        raise ValueError("PID must be an integer, not a float")
    else:
        raise ValueError("PID must be an integer or integer string")
    if pid <= 1:
        raise ValueError(f"Refusing unsafe PID value: {pid}")
    if pid > MAX_PID:
        raise ValueError("PID value exceeds maximum 32-bit integer limit")
    return pid


def _bounded_reason(value: object) -> str:
    return " ".join(str(value).split())[:180] or "Launch-gate transition failed"
