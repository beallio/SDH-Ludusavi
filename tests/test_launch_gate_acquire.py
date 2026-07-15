from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest

from sdh_ludusavi.launch_gate import ScopeNotReadyError, SteamAppScope
from sdh_ludusavi.launch_gate_acquire import (
    LaunchScopeAcquirer,
    ScopeAcquisitionResult,
)
from sdh_ludusavi.launch_gate_process import LaunchProcessIdentity


PID = 12992


class _ScopeNotReadyController:
    def __init__(self) -> None:
        self.discover_calls = 0

    def discover(self, pid: int) -> SteamAppScope:
        self.discover_calls += 1
        raise ScopeNotReadyError("launch PID is still in steam-launcher.service")


def _write_stopped_process(proc_root: Path) -> None:
    proc_dir = proc_root / str(PID)
    task_dir = proc_dir / "task" / str(PID)
    task_dir.mkdir(parents=True)
    fields_after_command = ["T", *("0" for _ in range(18)), "987654"]
    (proc_dir / "stat").write_text(
        f"{PID} (game bootstrap) {' '.join(fields_after_command)}\n",
        encoding="utf-8",
    )
    (task_dir / "stat").write_text(
        f"{PID} (game bootstrap) {' '.join(fields_after_command)}\n",
        encoding="utf-8",
    )
    (task_dir / "children").write_text("", encoding="utf-8")


class _DelayedStopProc:
    def __init__(self, proc_root: Path, *, running_reads: int) -> None:
        self.proc_root = proc_root
        self.running_reads = running_reads
        self.stat_reads = 0
        self._write_state("R")

    def _write_state(self, state: str) -> None:
        proc_dir = self.proc_root / str(PID)
        task_dir = proc_dir / "task" / str(PID)
        task_dir.mkdir(parents=True, exist_ok=True)
        fields_after_command = [state, *("0" for _ in range(18)), "987654"]
        stat_text = f"{PID} (game bootstrap) {' '.join(fields_after_command)}\n"
        (proc_dir / "stat").write_text(stat_text, encoding="utf-8")
        (task_dir / "stat").write_text(stat_text, encoding="utf-8")
        (task_dir / "children").write_text("", encoding="utf-8")

    def read_text(self, path: Path, original_read_text: object) -> str:
        if path.name == "stat" and self.proc_root in path.parents:
            self.stat_reads += 1
            if self.stat_reads > self.running_reads:
                self._write_state("T")
        return original_read_text(path, encoding="utf-8")  # type: ignore[operator]


def test_successful_scope_acquisition_result_requires_a_gate() -> None:
    with pytest.raises(ValueError, match="requires a scope or stop-only gate"):
        ScopeAcquisitionResult(True)

    scope = SteamAppScope(
        unit="app-steam-app123-456.scope",
        cgroup_path=(
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-steam-app123-456.scope"
        ),
        device=1,
        inode=2,
        root_pid=456,
    )
    assert ScopeAcquisitionResult(True, scope=scope).scope is scope
    identity = LaunchProcessIdentity(PID, os.geteuid(), 987654)
    with pytest.raises(ValueError, match="stop-only acquisition requires process identity"):
        ScopeAcquisitionResult(True, stop_only=True)
    stop_only = ScopeAcquisitionResult(True, stop_only=True, identity=identity)
    assert stop_only.stop_only is True
    assert stop_only.identity is identity
    with pytest.raises(ValueError, match="both scope-based and stop-only"):
        ScopeAcquisitionResult(True, scope=scope, stop_only=True)


def test_scope_not_ready_returns_stop_only_gate_without_resuming(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_stopped_process(proc_root)
    signals: list[int] = []

    result = LaunchScopeAcquirer(
        _ScopeNotReadyController(),
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=proc_root,
        uid=os.geteuid(),
    ).acquire(PID)

    assert result.success is True
    assert result.scope is None
    assert result.stop_only is True
    assert signals == [signal.SIGSTOP]


def test_scope_not_ready_waits_for_sigstop_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delayed_proc = _DelayedStopProc(tmp_path / "proc", running_reads=3)
    original_read_text = Path.read_text

    def delayed_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "stat" and delayed_proc.proc_root in path.parents:
            return delayed_proc.read_text(path, original_read_text)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", delayed_read_text)

    result = LaunchScopeAcquirer(
        _ScopeNotReadyController(),
        signal_sender=lambda pid, sig: None,
        proc_root=delayed_proc.proc_root,
        uid=os.geteuid(),
    ).acquire(PID)

    assert result.success is True
    assert result.stop_only is True


def test_scope_not_ready_does_not_poll_while_pid_is_stopped(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_stopped_process(proc_root)
    controller = _ScopeNotReadyController()

    result = LaunchScopeAcquirer(
        controller,
        signal_sender=lambda pid, sig: None,
        proc_root=proc_root,
        uid=os.geteuid(),
    ).acquire(PID)

    assert result.success is True
    assert result.stop_only is True
    assert controller.discover_calls == 1


def test_acquirer_uses_injected_wait_until_sigstop_is_delivered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delayed_proc = _DelayedStopProc(tmp_path / "proc", running_reads=3)
    original_read_text = Path.read_text
    waits: list[float] = []

    def delayed_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "stat" and delayed_proc.proc_root in path.parents:
            return delayed_proc.read_text(path, original_read_text)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", delayed_read_text)

    result = LaunchScopeAcquirer(
        _ScopeNotReadyController(),
        signal_sender=lambda pid, sig: None,
        proc_root=delayed_proc.proc_root,
        uid=os.geteuid(),
        monotonic=lambda: 0.0,
        wait=waits.append,
    ).acquire(PID)

    assert result.success is True
    assert result.stop_only is True
    assert waits == [0.0005]


def test_scope_not_ready_does_not_sleep_while_pid_is_stopped(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    _write_stopped_process(proc_root)

    def fail_on_sleep(seconds: float) -> None:
        raise AssertionError(f"unexpected acquisition sleep: {seconds}")

    result = LaunchScopeAcquirer(
        _ScopeNotReadyController(),
        signal_sender=lambda pid, sig: None,
        proc_root=proc_root,
        uid=os.geteuid(),
        wait=fail_on_sleep,
    ).acquire(PID)

    assert result.success is True
    assert result.stop_only is True


def test_scope_not_ready_with_children_reports_unverified_prescope_gate(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    _write_stopped_process(proc_root)
    (proc_root / str(PID) / "task" / str(PID) / "children").write_text(
        "13001\n",
        encoding="utf-8",
    )
    controller = _ScopeNotReadyController()
    signals: list[int] = []

    result = LaunchScopeAcquirer(
        controller,
        signal_sender=lambda pid, sig: signals.append(sig),
        proc_root=proc_root,
        uid=os.geteuid(),
    ).acquire(PID)

    assert result.success is False
    assert result.reason == (
        "Launch PID already has children; refusing an unverified pre-scope gate"
    )
    assert controller.discover_calls == 1
    assert signals == [signal.SIGSTOP, signal.SIGCONT]


def test_scope_not_ready_timeout_reports_observed_state(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _DelayedStopProc(proc_root, running_reads=1000)
    now = 0.0

    def monotonic() -> float:
        return now

    def wait(seconds: float) -> None:
        nonlocal now
        now += seconds

    result = LaunchScopeAcquirer(
        _ScopeNotReadyController(),
        signal_sender=lambda pid, sig: None,
        proc_root=proc_root,
        uid=os.geteuid(),
        monotonic=monotonic,
        wait=wait,
    ).acquire(PID)

    assert result.success is False
    assert result.reason == (
        "Launch PID did not stop after SIGSTOP within 100ms (state=R); refusing an unverified gate"
    )
