"""Singleton guard: a new backend instance terminates strictly-older siblings.

Decky v3.2.4's import_plugin can race during the post-install reload storm and
orphan a previously started backend process (observed 2026-06-12: PIDs 6270 and
6278 both alive, both children of Decky). The guard runs at _main and kills any
strictly-older process with the same uid and byte-identical /proc cmdline.
"""

from __future__ import annotations

import shutil
import signal
from pathlib import Path

from sdh_ludusavi.singleton import (
    enforce_single_instance,
    find_stale_sibling_pids,
    terminate_stale_siblings,
)

PLUGIN_TITLE = b"SDH-Ludusavi (/home/deck/homebrew/plugins/SDH-Ludusavi/main.py)\x00"
OTHER_TITLE = b"CSS Loader (/home/deck/homebrew/plugins/SDH-CssLoader/main.py)\x00"


def write_proc_entry(
    proc_root: Path,
    pid: int,
    *,
    cmdline: bytes = PLUGIN_TITLE,
    start_ticks: int = 1000,
    uid: int = 1000,
    comm: str = "SDH-Ludusavi",
    state: str = "S",
) -> None:
    entry = proc_root / str(pid)
    entry.mkdir(parents=True)
    (entry / "cmdline").write_bytes(cmdline)
    # Fields 3..22 of /proc/<pid>/stat; field 22 is starttime in clock ticks.
    post_comm = f"{state} 1330 1330 1330 0 -1 4194304 0 0 0 0 0 0 0 0 20 0 4 0 {start_ticks}"
    (entry / "stat").write_text(f"{pid} ({comm}) {post_comm}\n", encoding="utf-8")
    (entry / "status").write_text(
        f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="utf-8"
    )


class FakeKill:
    """Records signals; removes the fake /proc entry when a signal is fatal."""

    def __init__(self, proc_root: Path | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self.gone: set[int] = set()
        self.exit_on_term: set[int] = set()
        self.proc_root = proc_root

    def _reap(self, pid: int) -> None:
        self.gone.add(pid)
        if self.proc_root is not None:
            entry = self.proc_root / str(pid)
            if entry.exists():
                shutil.rmtree(entry)

    def __call__(self, pid: int, sig: int) -> None:
        if pid in self.gone:
            raise ProcessLookupError(pid)
        self.calls.append((pid, sig))
        if sig == signal.SIGKILL or (sig == signal.SIGTERM and pid in self.exit_on_term):
            self._reap(pid)


def test_finds_strictly_older_identical_sibling(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    write_proc_entry(tmp_path, 6278, start_ticks=600)

    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == [6270]


def test_ignores_newer_siblings_self_and_other_processes(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    write_proc_entry(tmp_path, 6278, start_ticks=600)
    write_proc_entry(tmp_path, 6300, start_ticks=700)
    write_proc_entry(tmp_path, 1513, cmdline=OTHER_TITLE, start_ticks=100)
    write_proc_entry(tmp_path, 1600, start_ticks=100, uid=0)
    (tmp_path / "self").mkdir()

    # The older instance must not target the newer one: only the newest
    # instance (Decky's dict winner) survives a mutual standoff.
    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6270) == []
    # Different cmdline (other plugin) and different uid are never matched.
    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == [6270]


def test_equal_start_ticks_breaks_tie_by_pid(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    write_proc_entry(tmp_path, 6278, start_ticks=500)

    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == [6270]
    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6270) == []


def test_tolerates_vanished_and_malformed_entries(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6278, start_ticks=600)
    # Entry without cmdline/stat (process exited mid-scan).
    (tmp_path / "9999").mkdir()
    # Malformed stat content.
    write_proc_entry(tmp_path, 8888, start_ticks=500)
    (tmp_path / "8888" / "stat").write_text("garbage", encoding="utf-8")

    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == []


def test_terminate_uses_sigterm_first(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)
    kill.exit_on_term.add(6270)

    report = terminate_stale_siblings(
        [6270], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert report["terminated"] == [6270]
    assert report["killed"] == []
    assert (6270, signal.SIGKILL) not in kill.calls


def test_terminate_escalates_to_sigkill(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)

    report = terminate_stale_siblings(
        [6270], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert (6270, signal.SIGTERM) in kill.calls
    assert (6270, signal.SIGKILL) in kill.calls
    assert report["killed"] == [6270]


def test_terminate_treats_zombie_as_exited(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500, state="Z")
    kill = FakeKill(tmp_path)

    report = terminate_stale_siblings(
        [6270], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert report["terminated"] == [6270]
    assert (6270, signal.SIGKILL) not in kill.calls


def test_terminate_never_signals_init_or_negative_pids(tmp_path: Path) -> None:
    kill = FakeKill()

    report = terminate_stale_siblings(
        [0, 1, -5], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert kill.calls == []
    assert report["terminated"] == []
    assert report["killed"] == []


class FakeLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def info(self, message: str, *args: object) -> None:
        self.infos.append(message % args if args else message)

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(message % args if args else message)

    def error(self, message: str, *args: object) -> None:
        self.errors.append(message % args if args else message)


def test_enforce_single_instance_terminates_and_logs(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    write_proc_entry(tmp_path, 6278, start_ticks=600)
    kill = FakeKill(tmp_path)
    kill.exit_on_term.add(6270)
    logger = FakeLogger()

    report = enforce_single_instance(
        logger, proc_root=tmp_path, pid=6278, kill_fn=kill, sleep_fn=lambda _s: None
    )

    assert report["status"] == "ok"
    assert report["stale_pids"] == [6270]
    assert any("6270" in line for line in logger.warnings)


def test_enforce_single_instance_is_quiet_without_siblings(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6278, start_ticks=600)
    logger = FakeLogger()

    report = enforce_single_instance(
        logger, proc_root=tmp_path, pid=6278, kill_fn=FakeKill(tmp_path), sleep_fn=lambda _s: None
    )

    assert report["status"] == "ok"
    assert report["stale_pids"] == []
    assert logger.warnings == []


def test_enforce_single_instance_never_raises(tmp_path: Path) -> None:
    logger = FakeLogger()

    def exploding_kill(_pid: int, _sig: int) -> None:
        raise RuntimeError("boom")

    write_proc_entry(tmp_path, 6270, start_ticks=500)
    write_proc_entry(tmp_path, 6278, start_ticks=600)

    report = enforce_single_instance(
        logger, proc_root=tmp_path, pid=6278, kill_fn=exploding_kill, sleep_fn=lambda _s: None
    )

    assert report["status"] in ("ok", "failed")
