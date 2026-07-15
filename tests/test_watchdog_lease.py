import os
import signal
from types import SimpleNamespace
from pathlib import Path

from sdh_ludusavi.launch_gate_process import LaunchProcessIdentity
from sdh_ludusavi.watchdog_lease import _PauseLease, _lease_expiry_reason, _release_gate


PID = 4567


def _identity(start_ticks: int = 987654) -> LaunchProcessIdentity:
    return LaunchProcessIdentity(PID, os.geteuid(), start_ticks)


def _write_process(proc_root: Path, start_ticks: int) -> None:
    proc_dir = proc_root / str(PID)
    proc_dir.mkdir(parents=True, exist_ok=True)
    fields_after_command = ["T", *("0" for _ in range(18)), str(start_ticks)]
    (proc_dir / "stat").write_text(
        f"{PID} (bootstrap) {' '.join(fields_after_command)}\n",
        encoding="utf-8",
    )


def test_pause_lease_has_no_scope_iteration_for_stop_only_gate() -> None:
    lease = _PauseLease(
        None,
        paused_at=10.0,
        lease_id="lease",
        lease_deadline=40.0,
        identity=_identity(),
    )

    assert lease.scopes == ()
    assert _lease_expiry_reason(lease, 39.0) is None
    assert _lease_expiry_reason(lease, 41.0) == "lease expired"


def test_pause_lease_iterates_primary_and_recovery_scopes() -> None:
    primary = SimpleNamespace(unit="primary")
    recovery = SimpleNamespace(unit="recovery")
    lease = _PauseLease(
        primary,
        paused_at=10.0,
        lease_id="lease",
        lease_deadline=40.0,
        recovery_scopes=(recovery,),
    )

    assert lease.scopes == (primary, recovery)


def test_release_stop_only_gate_sends_sigcont_for_matching_identity(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_process(proc_root, start_ticks=111)
    signals: list[tuple[int, int]] = []
    lease = _PauseLease(None, 10.0, "lease", 40.0, identity=_identity(111))

    released = _release_gate(
        SimpleNamespace(),
        lambda pid, sig: signals.append((pid, sig)),
        PID,
        lease,
        proc_root=proc_root,
    )

    assert released.success is True
    assert signals == [(PID, signal.SIGCONT)]


def test_release_stop_only_gate_skips_sigcont_for_reused_pid(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_process(proc_root, start_ticks=222)
    signals: list[tuple[int, int]] = []
    lease = _PauseLease(None, 10.0, "lease", 40.0, identity=_identity(111))

    released = _release_gate(
        SimpleNamespace(),
        lambda pid, sig: signals.append((pid, sig)),
        PID,
        lease,
        proc_root=proc_root,
    )

    assert released.success is True
    assert signals == []
