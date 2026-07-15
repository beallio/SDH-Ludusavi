from pathlib import Path

import pytest

from sdh_ludusavi.launch_gate_process import (
    SIGSTOP_DELIVERY_POLL_SECONDS,
    SIGSTOP_DELIVERY_TIMEOUT_SECONDS,
    _has_children,
    _is_stopped,
    _read_process_state,
    _wait_until_stopped,
)


PID = 12992


class FakeClock:
    def __init__(self, on_wait: object | None = None) -> None:
        self.now = 0.0
        self.waits: list[float] = []
        self.on_wait = on_wait

    def monotonic(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds
        if callable(self.on_wait):
            self.on_wait()


def _write_task_states(proc_root: Path, states: dict[int, str]) -> None:
    proc_dir = proc_root / str(PID)
    for task_id, state in states.items():
        task_dir = proc_dir / "task" / str(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "stat").write_text(
            f"{task_id} (bootstrap worker) {state} 0 0\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    ("state", "expected"),
    [("T", True), ("S", False), ("t", False)],
)
def test_is_stopped_reads_proc_stat_state(
    tmp_path: Path,
    state: str,
    expected: bool,
) -> None:
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / str(PID)
    proc_dir.mkdir(parents=True)
    (proc_dir / "stat").write_text(
        f"{PID} (bootstrap (nested) name) {state} 0 0\n",
        encoding="utf-8",
    )

    assert _is_stopped(proc_root, PID) is expected


def test_read_process_state_handles_parentheses_in_command(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / str(PID)
    proc_dir.mkdir(parents=True)
    (proc_dir / "stat").write_text(
        f"{PID} (bootstrap (nested) name) D 0 0\n",
        encoding="utf-8",
    )

    assert _read_process_state(proc_root, PID) == "D"


@pytest.mark.parametrize("content", ["", "malformed"])
def test_is_stopped_returns_false_when_state_cannot_be_read(
    tmp_path: Path,
    content: str,
) -> None:
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / str(PID)
    proc_dir.mkdir(parents=True)
    if content:
        (proc_dir / "stat").write_text(content, encoding="utf-8")

    assert _is_stopped(proc_root, PID) is False
    assert _read_process_state(proc_root, PID) is None


def test_has_children_reads_every_task_children_file(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    task_root = proc_root / str(PID) / "task"
    for task_id, content in ((PID, ""), (PID + 1, "13001 13002\n")):
        task_dir = task_root / str(task_id)
        task_dir.mkdir(parents=True)
        (task_dir / "children").write_text(content, encoding="utf-8")

    assert _has_children(proc_root, PID) is True


def test_has_children_returns_false_when_all_task_children_files_are_empty(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    task_dir = proc_root / str(PID) / "task" / str(PID)
    task_dir.mkdir(parents=True)
    (task_dir / "children").write_text("\n", encoding="utf-8")

    assert _has_children(proc_root, PID) is False


def test_has_children_fails_closed_when_children_cannot_be_read(tmp_path: Path) -> None:
    assert _has_children(tmp_path / "missing-proc", PID) is True


def test_sigstop_delivery_constants_match_device_evidence() -> None:
    assert SIGSTOP_DELIVERY_TIMEOUT_SECONDS == 0.1
    assert SIGSTOP_DELIVERY_POLL_SECONDS == 0.0005


def test_wait_until_stopped_returns_immediately_without_waiting(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_task_states(proc_root, {PID: "T"})

    def fail_wait(seconds: float) -> None:
        raise AssertionError(f"unexpected wait: {seconds}")

    assert (
        _wait_until_stopped(
            proc_root,
            PID,
            timeout_seconds=0.1,
            poll_seconds=0.0005,
            monotonic=lambda: 0.0,
            wait=fail_wait,
        )
        == "T"
    )


def test_wait_until_stopped_converges_from_running_to_stopped(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_task_states(proc_root, {PID: "R"})
    clock = FakeClock(lambda: _write_task_states(proc_root, {PID: "T"}))

    observed = _wait_until_stopped(
        proc_root,
        PID,
        timeout_seconds=0.1,
        poll_seconds=0.0005,
        monotonic=clock.monotonic,
        wait=clock.wait,
    )

    assert observed == "T"
    assert clock.waits == [0.0005]


def test_wait_until_stopped_times_out_at_strict_deadline(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_task_states(proc_root, {PID: "R"})
    clock = FakeClock()

    observed = _wait_until_stopped(
        proc_root,
        PID,
        timeout_seconds=0.001,
        poll_seconds=0.0005,
        monotonic=clock.monotonic,
        wait=clock.wait,
    )

    assert observed == "R"
    assert clock.now == pytest.approx(0.001)
    assert clock.waits == [0.0005, 0.0005]


@pytest.mark.parametrize("state", ["D", "Z"])
def test_wait_until_stopped_fails_closed_with_final_state(
    tmp_path: Path,
    state: str,
) -> None:
    proc_root = tmp_path / "proc"
    _write_task_states(proc_root, {PID: state})

    assert (
        _wait_until_stopped(
            proc_root,
            PID,
            timeout_seconds=0.0,
            poll_seconds=0.0005,
            monotonic=lambda: 0.0,
            wait=lambda seconds: None,
        )
        == state
    )


def test_wait_until_stopped_records_tracer_for_ptrace_stop(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_task_states(proc_root, {PID: "t"})
    (proc_root / str(PID) / "status").write_text(
        "Name:\tbootstrap\nTracerPid:\t73\n",
        encoding="utf-8",
    )

    assert (
        _wait_until_stopped(
            proc_root,
            PID,
            timeout_seconds=0.0,
            poll_seconds=0.0005,
            monotonic=lambda: 0.0,
            wait=lambda seconds: None,
        )
        == "t; TracerPid=73"
    )


@pytest.mark.parametrize("content", [None, "malformed"])
def test_wait_until_stopped_reports_unreadable_task_stat(
    tmp_path: Path,
    content: str | None,
) -> None:
    proc_root = tmp_path / "proc"
    task_dir = proc_root / str(PID) / "task" / str(PID)
    task_dir.mkdir(parents=True)
    if content is not None:
        (task_dir / "stat").write_text(content, encoding="utf-8")

    assert (
        _wait_until_stopped(
            proc_root,
            PID,
            timeout_seconds=0.0,
            poll_seconds=0.0005,
            monotonic=lambda: 0.0,
            wait=lambda seconds: None,
        )
        == "unreadable"
    )


def test_wait_until_stopped_reports_disappearing_task_stat(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_task_states(proc_root, {PID: "R"})
    stat_path = proc_root / str(PID) / "task" / str(PID) / "stat"
    clock = FakeClock(lambda: stat_path.unlink(missing_ok=True))

    observed = _wait_until_stopped(
        proc_root,
        PID,
        timeout_seconds=0.001,
        poll_seconds=0.0005,
        monotonic=clock.monotonic,
        wait=clock.wait,
    )

    assert observed == "unreadable"


def test_wait_until_stopped_requires_every_thread_to_stop(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _write_task_states(proc_root, {PID: "T", PID + 1: "R"})
    clock = FakeClock(lambda: _write_task_states(proc_root, {PID: "T", PID + 1: "T"}))

    observed = _wait_until_stopped(
        proc_root,
        PID,
        timeout_seconds=0.1,
        poll_seconds=0.0005,
        monotonic=clock.monotonic,
        wait=clock.wait,
    )

    assert observed == "T"
    assert clock.waits == [0.0005]


def test_wait_until_stopped_fails_closed_on_empty_task_list(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    (proc_root / str(PID) / "task").mkdir(parents=True)

    assert (
        _wait_until_stopped(
            proc_root,
            PID,
            timeout_seconds=0.0,
            poll_seconds=0.0005,
            monotonic=lambda: 0.0,
            wait=lambda seconds: None,
        )
        == "unreadable"
    )
