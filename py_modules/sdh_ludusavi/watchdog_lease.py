from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .constants import WATCHDOG_ABSOLUTE_RESUME_SECONDS
from .launch_gate import ScopeTransitionResult, SteamAppScope
from .launch_gate_acquire import ScopeAcquisitionResult
from .launch_gate_process import (
    LaunchProcessIdentity,
    _coerce_signal_pid,
    _matches_process_identity,
    _thread_group_is_stopped,
)


class _ScopeController(Protocol):
    def discover(self, pid: int) -> SteamAppScope: ...
    def freeze(self, scope: SteamAppScope) -> ScopeTransitionResult: ...
    def thaw(self, scope: SteamAppScope) -> ScopeTransitionResult: ...
    def freeze_requested(self, scope: SteamAppScope) -> bool: ...
    def wait_for_frozen(self, scope: SteamAppScope, expected: bool) -> ScopeTransitionResult: ...


class _ScopeAcquirer(Protocol):
    def acquire(
        self,
        pid: int,
        existing_scope: SteamAppScope | None = None,
    ) -> ScopeAcquisitionResult: ...


@dataclass
class _PauseLease:
    scope: SteamAppScope | None
    paused_at: float
    lease_id: str
    lease_deadline: float
    identity: LaunchProcessIdentity | None = None
    recovery_scopes: tuple[SteamAppScope, ...] = ()
    guarded_generation: int = 0
    guarded_active: bool = False
    guarded_cancel: Callable[[], bool] | None = None
    guarded_completion: threading.Event | None = None
    release_requested: bool = False
    release_in_progress: bool = False
    release_completion: threading.Event | None = None
    release_reason: str | None = None

    @property
    def scopes(self) -> tuple[SteamAppScope, ...]:
        if self.scope is None:
            return ()
        return (self.scope, *self.recovery_scopes)


class _GuardedOperationManager:
    """Keep cancellable launch mutations scoped to their exact pause lease."""

    def __init__(self, watchdog: Any, completion_timeout_seconds: float) -> None:
        self._watchdog = watchdog
        self._completion_timeout_seconds = completion_timeout_seconds

    def run(
        self,
        pid: int,
        lease_id: str,
        *,
        callback: Callable[[], object],
        cancel_callback: Callable[[], bool],
    ) -> object | None:
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError:
            return None
        if not isinstance(lease_id, str) or not lease_id or not callable(callback):
            return None
        if not callable(cancel_callback):
            return None

        with self._watchdog._get_pid_lock(valid_pid):
            with self._watchdog._paused_pids_lock:
                lease = self._watchdog._paused_pids.get(valid_pid)
            if not self._can_pin(valid_pid, lease, lease_id):
                return None
            assert lease is not None
            lease.guarded_generation += 1
            generation = lease.guarded_generation
            lease.guarded_active = True
            lease.guarded_cancel = cancel_callback
            lease.guarded_completion = threading.Event()

        try:
            result = callback()
        except BaseException:
            self._complete(valid_pid, lease, generation)
            raise

        release_requested = self._complete(valid_pid, lease, generation)
        return None if release_requested else result

    def request_release(
        self,
        valid_pid: int,
        lease_id: str | None,
        reason: str,
    ) -> dict[str, object]:
        """Cancel a pinned operation, wait for it, then thaw the exact lease."""
        with self._watchdog._get_pid_lock(valid_pid):
            with self._watchdog._paused_pids_lock:
                lease = self._watchdog._paused_pids.get(valid_pid)
            if lease is None:
                return self._watchdog._lease_failure(valid_pid, "Process not paused")
            if lease_id is not None and lease.lease_id != lease_id:
                return self._watchdog._lease_failure(valid_pid, "Lease ID mismatch")
            if lease.release_in_progress:
                return self._watchdog._lease_failure(
                    valid_pid, "Launch gate release already in progress"
                )

            lease.release_requested = True
            lease.release_in_progress = True
            lease.release_completion = threading.Event()
            lease.release_reason = reason
            cancel_callback = lease.guarded_cancel if lease.guarded_active else None
            completion = lease.guarded_completion

        if cancel_callback is not None:
            try:
                cancelled = bool(cancel_callback())
            # Intentionally broad: a failed cancellation must retain the gate.
            except Exception as exc:
                cancelled = False
                self._watchdog._log(
                    "error",
                    f"Guarded cancellation failed for root PID {valid_pid}: {_bounded_reason(exc)}",
                    "launch_gate",
                    None,
                )
            if not cancelled:
                self._release_attempt_failed(valid_pid, lease)
                return self._watchdog._lease_failure(
                    valid_pid, "Guarded operation cancellation was not confirmed"
                )
            if completion is None or not completion.wait(self._completion_timeout_seconds):
                self._release_attempt_failed(valid_pid, lease)
                self._watchdog._log(
                    "error",
                    f"Retaining launch gate for root PID {valid_pid}: guarded operation did not finish "
                    "after cancellation acknowledgement",
                    "launch_gate",
                    None,
                )
                return self._watchdog._lease_failure(
                    valid_pid, "Guarded operation completion was not confirmed"
                )

        return self._thaw_claimed_lease(valid_pid, lease)

    def wait_for_pending_release(self, pid: int) -> bool:
        """Serialize a replacement pause behind an already-claimed release."""
        while True:
            with self._watchdog._get_pid_lock(pid):
                with self._watchdog._paused_pids_lock:
                    lease = self._watchdog._paused_pids.get(pid)
                if lease is None or not lease.release_in_progress:
                    return True
                completion = lease.release_completion
            if completion is None or not completion.wait(self._completion_timeout_seconds):
                return False

    def _can_pin(self, pid: int, lease: _PauseLease | None, lease_id: str) -> bool:
        if lease is None or lease.lease_id != lease_id:
            return False
        if lease.guarded_active or lease.release_requested or lease.release_in_progress:
            return False
        if _lease_expiry_reason(lease, self._watchdog._monotonic()) is not None:
            return False
        if lease.scope is None:
            return _stop_only_gate_failure(self._watchdog._proc_root, pid, lease) is None
        return self._watchdog._verified_frozen(lease.scope).success

    def _complete(self, pid: int, lease: _PauseLease, generation: int) -> bool:
        with self._watchdog._get_pid_lock(pid):
            with self._watchdog._paused_pids_lock:
                current = self._watchdog._paused_pids.get(pid)
            if current is not lease or current.guarded_generation != generation:
                return False
            current.guarded_active = False
            current.guarded_cancel = None
            completion = current.guarded_completion
            current.guarded_completion = None
            if completion is not None:
                completion.set()
            return current.release_requested

    def _release_attempt_failed(self, pid: int, lease: _PauseLease) -> None:
        with self._watchdog._get_pid_lock(pid):
            with self._watchdog._paused_pids_lock:
                if self._watchdog._paused_pids.get(pid) is lease:
                    lease.release_in_progress = False
                    if lease.release_completion is not None:
                        lease.release_completion.set()

    def _thaw_claimed_lease(self, valid_pid: int, lease: _PauseLease) -> dict[str, object]:
        released = _release_gate(
            self._watchdog._scope_controller,
            self._watchdog._signal,
            valid_pid,
            lease,
            self._watchdog._proc_root,
        )
        for thawed in released.thawed:
            self._watchdog._log_thawed(thawed)
        with self._watchdog._get_pid_lock(valid_pid):
            with self._watchdog._paused_pids_lock:
                current = self._watchdog._paused_pids.get(valid_pid)
            if current is not lease:
                return self._watchdog._lease_failure(valid_pid, "Lease changed during release")
            current.release_in_progress = False
            if current.release_completion is not None:
                current.release_completion.set()
        if released.success:
            self._watchdog._remove_lease(valid_pid, lease)
            if lease.scope is not None:
                return {"status": "resumed", "pid": valid_pid}
            self._watchdog._log(
                "info",
                f"Released SIGSTOP gate for launch PID {valid_pid}",
                "launch_gate",
                None,
            )
            return {"status": "resumed", "pid": valid_pid}

        if released.retained:
            with self._watchdog._paused_pids_lock:
                if self._watchdog._paused_pids.get(valid_pid) is lease:
                    lease.scope = released.retained[0][0]
                    lease.recovery_scopes = tuple(scope for scope, _ in released.retained[1:])
        return self._watchdog._lease_failure(valid_pid, released.reason)


@dataclass(frozen=True)
class _GateRelease:
    success: bool
    reason: str = ""
    thawed: tuple[SteamAppScope, ...] = ()
    retained: tuple[tuple[SteamAppScope, str], ...] = ()


def _stop_only_gate_failure(
    proc_root: str | Path,
    pid: int,
    lease: _PauseLease,
) -> str | None:
    if lease.identity is None or not _matches_process_identity(proc_root, lease.identity):
        return "Launch PID identity changed"
    if not _thread_group_is_stopped(proc_root, pid):
        return "Launch PID is no longer stopped"
    return None


def _release_stop_only_identity(
    signal_sender: Callable[[int, int], None],
    proc_root: str | Path,
    identity: LaunchProcessIdentity | None,
) -> ScopeTransitionResult:
    if identity is None:
        return ScopeTransitionResult(False, "Stop-only lease has no process identity")
    if not _matches_process_identity(proc_root, identity):
        return ScopeTransitionResult(True)
    try:
        signal_sender(identity.pid, signal.SIGCONT)
    # Intentionally broad: signal failures must retain the lease for retry.
    except Exception as exc:
        return ScopeTransitionResult(False, _bounded_reason(f"Unable to send SIGCONT: {exc}"))
    return ScopeTransitionResult(True)


def _release_gate(
    controller: _ScopeController,
    signal_sender: Callable[[int, int], None],
    pid: int,
    lease: _PauseLease,
    proc_root: str | Path = "/proc",
) -> _GateRelease:
    if lease.scope is None:
        released = _release_stop_only_identity(signal_sender, proc_root, lease.identity)
        return _GateRelease(released.success, released.reason)

    thawed: list[SteamAppScope] = []
    retained: list[tuple[SteamAppScope, str]] = []
    for owned_scope in lease.scopes:
        result = controller.thaw(owned_scope)
        if result.success:
            thawed.append(owned_scope)
        else:
            retained.append((owned_scope, result.reason))
    reason = _bounded_reason(
        "; ".join(
            f"{scope.unit}: {detail or 'Unable to thaw Steam app scope'}"
            for scope, detail in retained
        )
    )
    return _GateRelease(not retained, reason if retained else "", tuple(thawed), tuple(retained))


def _lease_expiry_reason(lease: _PauseLease, now: float) -> str | None:
    if now - lease.paused_at > WATCHDOG_ABSOLUTE_RESUME_SECONDS:
        return "absolute ceiling"
    if now > lease.lease_deadline:
        return "lease expired"
    return None


def _retained_summary(retained: tuple[_PauseLease, ...]) -> tuple[str, str]:
    retained_scopes = tuple(scope for lease in retained for scope in lease.scopes)
    stop_only_count = len(retained) - len(retained_scopes)
    units = _bounded_reason(
        ", ".join(scope.unit for scope in retained_scopes) or f"{stop_only_count} SIGSTOP gate(s)"
    )
    attempts = "thaw attempts" if stop_only_count == 0 else "release attempts"
    return units, attempts


def _scope_thawed_message(scope: SteamAppScope) -> str:
    return f"Thawed Steam app scope {scope.unit} for root PID {scope.root_pid}"


def _gate_held_message(scope: SteamAppScope | None, pid: int) -> str:
    if scope is None:
        return f"Held launch PID {pid} with SIGSTOP gate (pre-scope)"
    return f"Froze Steam app scope {scope.unit} for root PID {pid}"


def _bounded_reason(value: object) -> str:
    return " ".join(str(value).split())[:180] or "Launch-gate transition failed"
