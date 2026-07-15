from __future__ import annotations

import signal
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .constants import WATCHDOG_ABSOLUTE_RESUME_SECONDS
from .launch_gate import ScopeTransitionResult, SteamAppScope
from .launch_gate_acquire import ScopeAcquisitionResult


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
    recovery_scopes: tuple[SteamAppScope, ...] = ()

    @property
    def scopes(self) -> tuple[SteamAppScope, ...]:
        if self.scope is None:
            return ()
        return (self.scope, *self.recovery_scopes)


@dataclass(frozen=True)
class _GateRelease:
    success: bool
    reason: str = ""
    thawed: tuple[SteamAppScope, ...] = ()
    retained: tuple[tuple[SteamAppScope, str], ...] = ()


def _release_gate(
    controller: _ScopeController,
    signal_sender: Callable[[int, int], None],
    pid: int,
    lease: _PauseLease,
) -> _GateRelease:
    if lease.scope is None:
        try:
            signal_sender(pid, signal.SIGCONT)
        # Intentionally broad: signal failures must retain the lease for retry.
        except Exception as exc:
            return _GateRelease(False, _bounded_reason(f"Unable to send SIGCONT: {exc}"))
        return _GateRelease(True)

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
