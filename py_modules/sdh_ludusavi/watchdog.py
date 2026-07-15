from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .constants import LAUNCH_GATE_LEASE_TTL_SECONDS
from .launch_gate import ScopeTransitionResult, SteamAppScope, SystemdScopeController
from .launch_gate_acquire import LaunchScopeAcquirer
from .launch_gate_process import _coerce_signal_pid
from .watchdog_lease import (
    _PauseLease,
    _ScopeAcquirer,
    _ScopeController,
    _bounded_reason,
    _gate_held_message,
    _lease_expiry_reason,
    _release_gate,
    _release_stop_only_identity,
    _retained_summary,
    _scope_thawed_message,
    _stop_only_gate_failure,
)

SHUTDOWN_THAW_ATTEMPTS = 3
SHUTDOWN_THAW_RETRY_SECONDS = 0.05


class ProcessWatchdog:
    """Own renewable leases on verified frozen Steam application scopes."""

    def __init__(
        self,
        log_callback: Callable[[str, str, str | None, str | None], None],
        scope_controller: _ScopeController | None = None,
        scope_acquirer: _ScopeAcquirer | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        signal_sender: Callable[[int, int], None] = os.kill,
        proc_root: str | Path = "/proc",
    ) -> None:
        self._log = log_callback
        self._scope_controller = scope_controller or SystemdScopeController()
        self._scope_acquirer = scope_acquirer or LaunchScopeAcquirer(self._scope_controller)
        self._monotonic = monotonic
        self._signal = signal_sender
        self._proc_root = Path(proc_root)
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
        """Hold the launch with SIGSTOP or freeze its complete Steam app scope."""
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError as exc:
            self._log("warning", f"Invalid PID passed to pause: {exc}", "launch_gate", None)
            return {"status": "failed", "message": str(exc)}

        with self._get_pid_lock(valid_pid):
            with self._paused_pids_lock:
                existing = self._paused_pids.get(valid_pid)
            if existing is not None and existing.recovery_scopes:
                return self._acquisition_failure(valid_pid, "Scope recovery is still pending")
            try:
                acquired = self._scope_acquirer.acquire(
                    valid_pid,
                    existing.scope if existing is not None else None,
                )
            # Intentionally broad: fail closed on any injected/runtime acquisition failure.
            except Exception as exc:
                return self._acquisition_failure(valid_pid, str(exc))
            if not acquired.success or (acquired.scope is None and not acquired.stop_only):
                return self._acquisition_failure(valid_pid, acquired.reason)
            scope = acquired.scope
            identity = acquired.identity if scope is None else None
            if existing is not None and existing.scope != scope:
                released = (
                    self._scope_controller.thaw(existing.scope)
                    if existing.scope is not None
                    else ScopeTransitionResult(True)
                )
                if not released.success:
                    if scope is None:
                        cleanup = _release_stop_only_identity(
                            self._signal,
                            self._proc_root,
                            identity,
                        )
                    else:
                        cleanup = self._scope_controller.thaw(scope)
                    reason = f"Unable to thaw previous scope: {released.reason}"
                    if not cleanup.success:
                        reason += f"; unable to release acquired gate: {cleanup.reason}"
                        if scope is not None:
                            with self._paused_pids_lock:
                                if (
                                    self._paused_pids.get(valid_pid) is existing
                                    and scope not in existing.scopes
                                ):
                                    existing.recovery_scopes += (scope,)
                    return self._acquisition_failure(valid_pid, reason)
                self._remove_lease(valid_pid, existing)
                if existing.scope is not None:
                    self._log_thawed(existing.scope)
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
                    identity=identity,
                )
            self._ensure_watchdog_running()
            self._log("info", _gate_held_message(scope, valid_pid), "launch_gate", None)
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
            stop_failure = _stop_only_gate_failure(self._proc_root, valid_pid, lease)
            if lease.scope is None and stop_failure is not None:
                return self._lease_failure(valid_pid, stop_failure)
            for owned_scope in lease.scopes:
                verified = self._verified_frozen(owned_scope)
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

    def verify_gate(self, pid: int, lease_id: str) -> bool:
        """Confirm that the exact unexpired launch gate is still held."""
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError:
            return False
        if not isinstance(lease_id, str) or not lease_id:
            return False

        with self._get_pid_lock(valid_pid):
            with self._paused_pids_lock:
                lease = self._paused_pids.get(valid_pid)
            if lease is None or lease.lease_id != lease_id:
                return False
            if _lease_expiry_reason(lease, self._monotonic()) is not None:
                return False
            if lease.scope is None:
                return _stop_only_gate_failure(self._proc_root, valid_pid, lease) is None
            return self._verified_frozen(lease.scope).success

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

        released = _release_gate(
            self._scope_controller, self._signal, valid_pid, lease, self._proc_root
        )
        for thawed in released.thawed:
            self._log_thawed(thawed)
        if released.success:
            self._remove_lease(valid_pid, lease)
            if lease.scope is not None:
                return {"status": "resumed", "pid": valid_pid}
            self._log(
                "info",
                f"Released SIGSTOP gate for launch PID {valid_pid}",
                "launch_gate",
                None,
            )
            return {"status": "resumed", "pid": valid_pid}

        if released.retained:
            with self._paused_pids_lock:
                if self._paused_pids.get(valid_pid) is lease:
                    lease.scope = released.retained[0][0]
                    lease.recovery_scopes = tuple(scope for scope, _ in released.retained[1:])
        return self._lease_failure(valid_pid, released.reason)

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
        units, attempts = _retained_summary(retained)
        self._log(
            "error",
            f"Shutdown left {len(retained)} launch-gate lease(s) unconfirmed after "
            f"{SHUTDOWN_THAW_ATTEMPTS} {attempts}: {units}",
            "launch_gate",
            None,
        )

    def _verified_frozen(self, scope: SteamAppScope) -> ScopeTransitionResult:
        if not self._scope_controller.freeze_requested(scope):
            return ScopeTransitionResult(False, "Steam app scope is no longer frozen")
        return self._scope_controller.wait_for_frozen(scope, expected=True)

    def _acquisition_failure(self, pid: int, reason: str) -> dict[str, object]:
        bounded = _bounded_reason(reason or "Unable to acquire frozen Steam app scope")
        self._log(
            "warning",
            f"Unable to acquire frozen Steam app scope for root PID {pid}: {bounded}",
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
        self._log("info", _scope_thawed_message(scope), "launch_gate", None)

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
                    gate = (
                        f"Steam app scope {lease.scope.unit}"
                        if lease.scope is not None
                        else "SIGSTOP gate"
                    )
                    self._log(
                        "warning",
                        f"Watchdog detected {gate} for root PID {pid} held for "
                        f"{frozen_for:.0f}s ({reason}). Releasing automatically.",
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
