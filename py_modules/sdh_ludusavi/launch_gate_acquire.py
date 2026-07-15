from __future__ import annotations

import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .launch_gate import (
    ScopeDiscoveryError,
    ScopeNotReadyError,
    ScopeTransitionResult,
    SteamAppScope,
    _coerce_pid,
)
from .launch_gate_process import (
    LaunchProcessIdentity,
    _bounded_reason,
    _has_children,
    _is_stopped,
    _parse_start_ticks,
)


class _ScopeController(Protocol):
    def discover(self, pid: int) -> SteamAppScope: ...

    def freeze(self, scope: SteamAppScope) -> ScopeTransitionResult: ...

    def thaw(self, scope: SteamAppScope) -> ScopeTransitionResult: ...

    def freeze_requested(self, scope: SteamAppScope) -> bool: ...

    def wait_for_frozen(self, scope: SteamAppScope, expected: bool) -> ScopeTransitionResult: ...


@dataclass(frozen=True)
class ScopeAcquisitionResult:
    success: bool
    scope: SteamAppScope | None = None
    stop_only: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if self.scope is not None and self.stop_only:
            raise ValueError("scope acquisition cannot be both scope-based and stop-only")
        if self.success and self.scope is None and not self.stop_only:
            raise ValueError("successful scope acquisition requires a scope or stop-only gate")


class LaunchScopeAcquirer:
    """Bridge one stopped bootstrap PID into a verified frozen Steam app scope."""

    def __init__(
        self,
        controller: _ScopeController,
        *,
        signal_sender: Callable[[int, int], None] = os.kill,
        proc_root: str | Path = "/proc",
        uid: int | None = None,
    ) -> None:
        self._controller = controller
        self._signal = signal_sender
        self._proc_root = Path(proc_root)
        self._uid = os.geteuid() if uid is None else uid

    def acquire(
        self,
        pid: int,
        existing_scope: SteamAppScope | None = None,
    ) -> ScopeAcquisitionResult:
        identity: LaunchProcessIdentity | None = None
        scope: SteamAppScope | None = None
        result: ScopeAcquisitionResult | None = None
        stop_sent = False
        owns_frozen_scope = False
        try:
            identity = self._capture_identity(pid)
            self._signal(identity.pid, signal.SIGSTOP)
            stop_sent = True
            try:
                scope = self._controller.discover(identity.pid)
            except ScopeNotReadyError as exc:
                self._require_same_identity(identity)
                if not _is_stopped(self._proc_root, identity.pid):
                    raise ScopeDiscoveryError(
                        "Launch PID is not stopped after SIGSTOP; refusing an unverified gate"
                    ) from exc
                if _has_children(self._proc_root, identity.pid):
                    raise ScopeDiscoveryError(
                        "Launch PID already has children; refusing an unverified pre-scope gate"
                    ) from exc
                self._require_same_identity(identity)
                result = ScopeAcquisitionResult(True, stop_only=True)

            if result is None:
                if scope is None:
                    raise ScopeDiscoveryError("Steam app scope discovery returned no scope")
                self._require_same_identity(identity)

                if scope == existing_scope:
                    verified = self._verify_frozen(scope, handoff=False)
                else:
                    verified = self._controller.freeze(scope)
                if not verified.success:
                    raise RuntimeError(verified.reason or "Unable to freeze Steam app scope")
                owns_frozen_scope = scope != existing_scope

                self._require_same_scope(identity, scope)
                self._signal(identity.pid, signal.SIGCONT)
                stop_sent = False

                verified = self._verify_frozen(scope, handoff=True)
                if not verified.success:
                    raise RuntimeError(verified.reason)
                result = ScopeAcquisitionResult(True, scope=scope)
        # Intentionally broad: every runtime acquisition failure must fail closed and unwind.
        except Exception as exc:
            result = ScopeAcquisitionResult(False, reason=_bounded_reason(exc))
        finally:
            failed = result is None or not result.success
            if failed and stop_sent and identity is not None:
                cleanup_error = self._release_if_same(identity)
                if cleanup_error and result is not None:
                    result = ScopeAcquisitionResult(
                        False,
                        reason=_bounded_reason(f"{cleanup_error}; {result.reason}"),
                    )
            if failed and owns_frozen_scope and scope is not None:
                try:
                    self._controller.thaw(scope)
                # Intentionally broad: cleanup is best effort and must not hide the root failure.
                except Exception:
                    pass
        if result is None:
            raise RuntimeError("Scope acquisition interrupted")
        return result

    def _verify_frozen(
        self,
        scope: SteamAppScope,
        *,
        handoff: bool,
    ) -> ScopeTransitionResult:
        if not self._controller.freeze_requested(scope):
            phase = " after bootstrap handoff" if handoff else ""
            return ScopeTransitionResult(False, f"Scope freeze was not preserved{phase}")
        verified = self._controller.wait_for_frozen(scope, expected=True)
        if verified.success:
            return verified
        if handoff:
            return ScopeTransitionResult(
                False,
                f"Scope freeze verification failed after bootstrap handoff: {verified.reason}",
            )
        return verified

    def _capture_identity(self, pid: object) -> LaunchProcessIdentity:
        valid_pid = _coerce_pid(pid)
        proc_dir = self._proc_root / str(valid_pid)
        try:
            owner_uid = proc_dir.stat().st_uid
        except OSError as exc:
            raise ScopeDiscoveryError("Launch PID exited before scope acquisition") from exc
        if owner_uid != self._uid:
            raise ScopeDiscoveryError("Launch PID owner does not match the plugin user")
        try:
            stat_text = (proc_dir / "stat").read_text(encoding="utf-8")
            start_ticks = _parse_start_ticks(stat_text, valid_pid)
        except ScopeDiscoveryError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ScopeDiscoveryError("Launch PID exited before scope acquisition") from exc
        return LaunchProcessIdentity(valid_pid, owner_uid, start_ticks)

    def _require_same_identity(self, expected: LaunchProcessIdentity) -> None:
        try:
            current = self._capture_identity(expected.pid)
        except ScopeDiscoveryError as exc:
            raise ScopeDiscoveryError("Launch PID exited during scope acquisition") from exc
        if current != expected:
            raise ScopeDiscoveryError("Launch PID identity changed during scope acquisition")

    def _require_same_scope(
        self,
        identity: LaunchProcessIdentity,
        expected_scope: SteamAppScope,
    ) -> None:
        self._require_same_identity(identity)
        if self._controller.discover(identity.pid) != expected_scope:
            raise ScopeDiscoveryError("Launch PID scope changed during scope acquisition")

    def _release_if_same(self, identity: LaunchProcessIdentity) -> str:
        try:
            self._require_same_identity(identity)
        except ScopeDiscoveryError:
            return ""
        try:
            self._signal(identity.pid, signal.SIGCONT)
        # Intentionally broad: injected/runtime signal errors become bounded cleanup failures.
        except Exception as exc:
            return f"Unable to release bootstrap signal: {_bounded_reason(exc)}"
        return ""
