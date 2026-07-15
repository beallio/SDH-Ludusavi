from pathlib import Path

import pytest

from sdh_ludusavi.launch_gate_process import _has_children, _is_stopped


PID = 12992


@pytest.mark.parametrize(("state", "expected"), [("T", True), ("S", False)])
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
