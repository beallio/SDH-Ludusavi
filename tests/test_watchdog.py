from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sdh_ludusavi.constants import WATCHDOG_ABSOLUTE_RESUME_SECONDS
from sdh_ludusavi.watchdog import ProcessWatchdog, _PauseLease


def scope(pid: int = 4567, *, inode: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        unit=f"app-steam-app123-{pid}.scope",
        cgroup_path=f"/user.slice/app.slice/app-steam-app123-{pid}.scope",
        device=1,
        inode=inode,
        root_pid=pid,
    )


def result(success: bool, reason: str = "", *, disappeared: bool = False) -> SimpleNamespace:
    return SimpleNamespace(success=success, reason=reason, disappeared=disappeared)


class FakeScopeController:
    def __init__(self) -> None:
        self.scopes: dict[int, object] = {}
        self.freeze_results: list[object] = []
        self.thaw_results: list[object] = []
        self.requested = True
        self.frozen = True
        self.discover_calls: list[int] = []
        self.freeze_calls: list[object] = []
        self.thaw_calls: list[object] = []

    def discover(self, pid: int) -> object:
        self.discover_calls.append(pid)
        discovered = self.scopes.get(pid)
        if isinstance(discovered, BaseException):
            raise discovered
        return discovered or scope(pid)

    def freeze(self, target: object) -> object:
        self.freeze_calls.append(target)
        return self.freeze_results.pop(0) if self.freeze_results else result(True)

    def thaw(self, target: object) -> object:
        self.thaw_calls.append(target)
        return self.thaw_results.pop(0) if self.thaw_results else result(True)

    def freeze_requested(self, target: object) -> bool:
        return self.requested

    def wait_for_frozen(self, target: object, expected: bool) -> object:
        return result(self.frozen is expected, "unexpected freezer state")


class FakeScopeAcquirer:
    def __init__(self, controller: FakeScopeController) -> None:
        self.controller = controller
        self.calls: list[tuple[int, object | None]] = []
        self.results: list[object] = []

    def acquire(self, pid: int, existing_scope: object | None = None) -> object:
        self.calls.append((pid, existing_scope))
        if self.results:
            return self.results.pop(0)
        try:
            discovered = self.controller.discover(pid)
        except Exception as exc:
            return result(False, str(exc))
        if existing_scope == discovered:
            if not self.controller.freeze_requested(discovered):
                return result(False, "Steam app scope is no longer frozen")
            verified = self.controller.wait_for_frozen(discovered, expected=True)
            if not verified.success:
                return verified
        else:
            frozen = self.controller.freeze(discovered)
            if not frozen.success:
                return frozen
        return SimpleNamespace(success=True, scope=discovered, reason="")


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now


def watchdog(controller: FakeScopeController | None = None) -> tuple[ProcessWatchdog, MagicMock]:
    logger = MagicMock()
    target_controller = controller or FakeScopeController()
    instance = ProcessWatchdog(
        log_callback=logger,
        scope_controller=target_controller,
        scope_acquirer=FakeScopeAcquirer(target_controller),
    )
    return instance, logger


def test_pause_renew_resume_uses_scope_and_preserves_rpc_shape() -> None:
    controller = FakeScopeController()
    wd, logger = watchdog(controller)

    paused = wd.pause(4567)
    lease_id = paused["lease_id"]

    assert paused == {
        "status": "paused",
        "pid": 4567,
        "lease_id": lease_id,
        "lease_ttl_seconds": 30.0,
    }
    assert wd.renew_pause(4567, lease_id) == {
        "status": "renewed",
        "pid": 4567,
        "lease_ttl_seconds": 30.0,
    }
    assert wd.resume(4567, lease_id) == {"status": "resumed", "pid": 4567}
    assert len(controller.freeze_calls) == 1
    assert controller.thaw_calls == controller.freeze_calls
    assert any("Froze Steam app scope" in call.args[1] for call in logger.call_args_list)
    assert any("Thawed Steam app scope" in call.args[1] for call in logger.call_args_list)
    wd.stop()


def test_pause_fails_closed_when_scope_discovery_or_freeze_fails() -> None:
    controller = FakeScopeController()
    controller.scopes[4567] = RuntimeError("scope unavailable")
    wd, _ = watchdog(controller)

    discovered = wd.pause(4567)
    assert discovered["status"] == "failed"
    assert "scope unavailable" in discovered["message"]
    assert wd._paused_pids == {}

    controller.scopes[4567] = scope()
    controller.freeze_results.append(result(False, "freeze verification timed out"))
    frozen = wd.pause(4567)
    assert frozen["status"] == "failed"
    assert "freeze verification timed out" in frozen["message"]
    assert wd._paused_pids == {}
    wd.stop()


def test_renew_survives_launcher_exit_without_rediscovery() -> None:
    controller = FakeScopeController()
    wd, _ = watchdog(controller)
    lease_id = wd.pause(4567)["lease_id"]
    controller.scopes[4567] = FileNotFoundError("launcher exited")

    renewed = wd.renew_pause(4567, lease_id)

    assert renewed["status"] == "renewed"
    assert controller.discover_calls == [4567]
    wd.resume(4567, lease_id)
    wd.stop()


def test_renew_rejects_wrong_lease_changed_identity_and_unexpected_thaw() -> None:
    controller = FakeScopeController()
    wd, _ = watchdog(controller)
    lease_id = wd.pause(4567)["lease_id"]

    assert wd.renew_pause(4567, "wrong")["message"] == "Lease ID mismatch"

    controller.requested = False
    unexpected = wd.renew_pause(4567, lease_id)
    assert unexpected["status"] == "failed"
    assert "no longer frozen" in unexpected["message"]

    controller.requested = True
    controller.frozen = False
    incomplete = wd.renew_pause(4567, lease_id)
    assert incomplete["status"] == "failed"
    assert "unexpected freezer state" in incomplete["message"]
    assert 4567 in wd._paused_pids
    controller.frozen = True
    wd.resume(4567, lease_id)
    wd.stop()


def test_same_scope_pause_rotates_lease_without_thaw_window() -> None:
    controller = FakeScopeController()
    wd, _ = watchdog(controller)
    first = wd.pause(4567)
    second = wd.pause(4567)

    assert second["status"] == "paused"
    assert second["lease_id"] != first["lease_id"]
    assert len(controller.freeze_calls) == 1
    assert controller.thaw_calls == []
    wd.resume(4567, second["lease_id"])
    wd.stop()


def test_same_scope_rotation_preserves_absolute_ceiling_origin() -> None:
    controller = FakeScopeController()
    clock = FakeClock()
    logger = MagicMock()
    wd = ProcessWatchdog(
        logger,
        scope_controller=controller,
        scope_acquirer=FakeScopeAcquirer(controller),
        monotonic=clock.monotonic,
    )
    wd._ensure_watchdog_running = lambda: None  # type: ignore[method-assign]

    wd.pause(4567)
    first_paused_at = wd._paused_pids[4567].paused_at
    clock.now += WATCHDOG_ABSOLUTE_RESUME_SECONDS - 1
    rotated = wd.pause(4567)

    assert wd._paused_pids[4567].paused_at == first_paused_at
    clock.now += 2
    wd._check_and_resume_stuck_pids()
    assert 4567 not in wd._paused_pids
    assert any("absolute ceiling" in call.args[1] for call in logger.call_args_list)
    assert controller.thaw_calls == [controller.freeze_calls[0]]
    assert rotated["status"] == "paused"


def test_different_scope_identity_thaws_old_before_freezing_new() -> None:
    controller = FakeScopeController()
    wd, _ = watchdog(controller)
    first = wd.pause(4567)
    old_scope = controller.freeze_calls[0]
    controller.scopes[4567] = scope(inode=99)

    second = wd.pause(4567)

    assert second["status"] == "paused"
    assert second["lease_id"] != first["lease_id"]
    assert controller.thaw_calls == [old_scope]
    assert controller.freeze_calls[-1].inode == 99
    wd.resume(4567, second["lease_id"])
    wd.stop()


def test_concurrent_resume_and_pause_are_serialized_without_thawing_new_lease() -> None:
    controller = FakeScopeController()
    wd, _ = watchdog(controller)
    first_lease = wd.pause(4567)["lease_id"]
    thaw_started = threading.Event()
    allow_thaw = threading.Event()
    original_thaw = controller.thaw

    def blocking_thaw(target: object) -> object:
        thaw_started.set()
        assert allow_thaw.wait(timeout=1)
        return original_thaw(target)

    controller.thaw = blocking_thaw  # type: ignore[method-assign]
    resume_result: dict[str, object] = {}
    pause_result: dict[str, object] = {}
    resume_thread = threading.Thread(
        target=lambda: resume_result.update(wd.resume(4567, first_lease))
    )
    pause_thread = threading.Thread(target=lambda: pause_result.update(wd.pause(4567)))

    resume_thread.start()
    assert thaw_started.wait(timeout=1)
    pause_thread.start()
    time.sleep(0.02)
    assert controller.discover_calls == [4567]
    allow_thaw.set()
    resume_thread.join(timeout=1)
    pause_thread.join(timeout=1)

    assert resume_result["status"] == "resumed"
    assert pause_result["status"] == "paused"
    assert 4567 in wd._paused_pids
    assert wd._paused_pids[4567].lease_id == pause_result["lease_id"]
    assert len(controller.thaw_calls) == 1
    assert len(controller.freeze_calls) == 2
    wd.resume(4567, pause_result["lease_id"])
    assert len(controller.thaw_calls) == 2
    wd.stop()


def test_failed_thaw_retains_lease_for_retry() -> None:
    controller = FakeScopeController()
    controller.thaw_results.extend([result(False, "manager busy"), result(True)])
    wd, _ = watchdog(controller)
    lease_id = wd.pause(4567)["lease_id"]

    failed = wd.resume(4567, lease_id)
    assert failed["status"] == "failed"
    assert "manager busy" in failed["message"]
    assert 4567 in wd._paused_pids

    assert wd.resume(4567, lease_id)["status"] == "resumed"
    assert 4567 not in wd._paused_pids
    wd.stop()


def test_disappeared_scope_is_safe_idempotent_resume() -> None:
    controller = FakeScopeController()
    controller.thaw_results.append(result(True, disappeared=True))
    wd, _ = watchdog(controller)
    lease_id = wd.pause(4567)["lease_id"]

    assert wd.resume(4567, lease_id) == {"status": "resumed", "pid": 4567}
    assert wd._paused_pids == {}
    wd.stop()


@pytest.mark.parametrize("reason", ["lease expired", "absolute ceiling"])
def test_watchdog_automatically_thaws_expired_scope(reason: str) -> None:
    controller = FakeScopeController()
    wd, logger = watchdog(controller)
    now = time.monotonic()
    paused_at = (
        now - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1) if reason == "absolute ceiling" else now
    )
    deadline = now + 30 if reason == "absolute ceiling" else now - 1
    wd._paused_pids[4567] = _PauseLease(scope(), paused_at, "lease", deadline)

    wd._check_and_resume_stuck_pids()

    assert 4567 not in wd._paused_pids
    assert len(controller.thaw_calls) == 1
    assert any(reason in call.args[1] for call in logger.call_args_list)
    wd.stop()


def test_watchdog_rechecks_expiry_after_late_renewal() -> None:
    controller = FakeScopeController()
    wd, _ = watchdog(controller)
    wd._paused_pids[4567] = _PauseLease(scope(), time.monotonic(), "lease", time.monotonic() - 1)
    pid_lock = wd._get_pid_lock(4567)

    def renew_before_transition(_pid: int) -> threading.Lock:
        wd._paused_pids[4567].lease_deadline = time.monotonic() + 30
        return pid_lock

    wd._get_pid_lock = renew_before_transition  # type: ignore[method-assign]
    wd._check_and_resume_stuck_pids()

    assert controller.thaw_calls == []
    assert 4567 in wd._paused_pids


def test_stop_retries_retained_scope_until_thaw_succeeds() -> None:
    controller = FakeScopeController()
    controller.thaw_results.extend([result(False, "busy"), result(True)])
    wd, _ = watchdog(controller)
    wd._paused_pids[100] = _PauseLease(scope(100), 1.0, "a", 2.0)
    wd._paused_pids[200] = _PauseLease(scope(200), 1.0, "b", 2.0)

    wd.stop()

    assert wd._paused_pids == {}
    assert controller.thaw_calls == [scope(100), scope(200), scope(100)]


def test_stop_bounds_retries_and_logs_retained_frozen_scope() -> None:
    controller = FakeScopeController()
    controller.thaw_results.extend([result(False, "busy")] * 3)
    wd, logger = watchdog(controller)
    wd._paused_pids[100] = _PauseLease(scope(100), 1.0, "a", 2.0)

    wd.stop()

    assert 100 in wd._paused_pids
    assert controller.thaw_calls == [scope(100)] * 3
    assert any(
        call.args[0] == "error" and "3 thaw attempts" in call.args[1]
        for call in logger.call_args_list
    )


@pytest.mark.parametrize("pid", [True, False, 1, 0, -1, 2.5, "abc", 2_147_483_648])
def test_invalid_pid_fails_without_scope_discovery(pid: object) -> None:
    controller = FakeScopeController()
    wd, _ = watchdog(controller)

    assert wd.pause(pid)["status"] == "failed"  # type: ignore[arg-type]
    assert wd.resume(pid)["status"] == "failed"  # type: ignore[arg-type]
    assert controller.discover_calls == []


def test_no_pid_signal_fallback_remains() -> None:
    source = Path("py_modules/sdh_ludusavi/watchdog.py").read_text()

    assert "os.kill" not in source
    assert "SIGSTOP" not in source
    assert "SIGCONT" not in source
    assert "_process_tree" not in source


def test_pause_creates_lease_only_from_successful_acquisition() -> None:
    controller = FakeScopeController()
    acquirer = FakeScopeAcquirer(controller)
    acquired_scope = scope()
    acquirer.results.extend(
        [
            SimpleNamespace(success=False, scope=None, reason="scope acquisition timed out"),
            SimpleNamespace(success=True, scope=acquired_scope, reason=""),
        ]
    )
    logger = MagicMock()
    wd = ProcessWatchdog(
        logger,
        scope_controller=controller,
        scope_acquirer=acquirer,
    )
    wd._ensure_watchdog_running = lambda: None  # type: ignore[method-assign]

    failed = wd.pause(4567)
    assert failed == {
        "status": "failed",
        "pid": 4567,
        "message": "scope acquisition timed out",
    }
    assert wd._paused_pids == {}
    assert wd._watchdog_thread is None

    paused = wd.pause(4567)
    assert paused["status"] == "paused"
    assert wd._paused_pids[4567].scope is acquired_scope
    assert controller.discover_calls == []
    assert controller.freeze_calls == []
    assert (
        len(
            [
                call
                for call in logger.call_args_list
                if "scope acquisition timed out" in call.args[1]
            ]
        )
        == 1
    )


def test_same_scope_acquisition_rotation_receives_existing_verified_scope() -> None:
    controller = FakeScopeController()
    acquirer = FakeScopeAcquirer(controller)
    logger = MagicMock()
    wd = ProcessWatchdog(logger, scope_controller=controller, scope_acquirer=acquirer)
    wd._ensure_watchdog_running = lambda: None  # type: ignore[method-assign]

    first = wd.pause(4567)
    original_paused_at = wd._paused_pids[4567].paused_at
    second = wd.pause(4567)

    assert first["lease_id"] != second["lease_id"]
    assert acquirer.calls[0] == (4567, None)
    assert acquirer.calls[1] == (4567, wd._paused_pids[4567].scope)
    assert wd._paused_pids[4567].paused_at == original_paused_at
    assert len(controller.freeze_calls) == 1
    assert controller.thaw_calls == []
