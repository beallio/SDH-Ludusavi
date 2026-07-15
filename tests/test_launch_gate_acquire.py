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


PID = 12992


class _ScopeNotReadyController:
    def discover(self, pid: int) -> SteamAppScope:
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
    (task_dir / "children").write_text("", encoding="utf-8")


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
    assert ScopeAcquisitionResult(True, stop_only=True).stop_only is True
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


def test_scope_not_ready_does_not_poll_while_pid_is_stopped(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_stopped_process(proc_root)
    waits: list[float] = []

    result = LaunchScopeAcquirer(
        _ScopeNotReadyController(),
        signal_sender=lambda pid, sig: None,
        proc_root=proc_root,
        uid=os.geteuid(),
        monotonic=lambda: 0.0,
        wait=waits.append,
    ).acquire(PID)

    assert result.success is True
    assert result.stop_only is True
    assert waits == []
