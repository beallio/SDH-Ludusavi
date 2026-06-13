"""Singleton guard: a new backend instance terminates strictly-older siblings."""

from __future__ import annotations

import shutil
import signal
from pathlib import Path

from sdh_ludusavi.singleton import (
    SiblingProcess,
    enforce_single_instance,
    find_stale_sibling_pids,
    find_stale_siblings,
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
    entry.mkdir(parents=True, exist_ok=True)
    if cmdline is not None:
        (entry / "cmdline").write_bytes(cmdline)
    # Fields 3..22 of /proc/<pid>/stat; field 22 is starttime in clock ticks.
    post_comm = f"{state} 1330 1330 1330 0 -1 4194304 0 0 0 0 0 0 0 0 20 0 4 0 {start_ticks}"
    (entry / "stat").write_text(f"{pid} ({comm}) {post_comm}\n", encoding="utf-8")
    if uid is None:
        pass
    else:
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

    siblings = find_stale_siblings(proc_root=tmp_path, pid=6278)
    assert len(siblings) == 1
    assert siblings[0].pid == 6270
    assert siblings[0].start_ticks == 500
    assert siblings[0].uid == 1000
    assert siblings[0].cmdline == PLUGIN_TITLE

    # Wrapper compatibility
    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == [6270]


def test_ignores_newer_siblings_self_and_other_processes(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    write_proc_entry(tmp_path, 6278, start_ticks=600)
    write_proc_entry(tmp_path, 6300, start_ticks=700)
    write_proc_entry(tmp_path, 1513, cmdline=OTHER_TITLE, start_ticks=100)
    write_proc_entry(tmp_path, 1600, start_ticks=100, uid=0)
    (tmp_path / "self").mkdir()

    assert find_stale_siblings(proc_root=tmp_path, pid=6270) == []
    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == [6270]


def test_equal_start_ticks_breaks_tie_by_pid(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    write_proc_entry(tmp_path, 6278, start_ticks=500)

    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == [6270]
    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6270) == []


def test_tolerates_vanished_and_malformed_entries(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6278, start_ticks=600)
    (tmp_path / "9999").mkdir()
    write_proc_entry(tmp_path, 8888, start_ticks=500)
    (tmp_path / "8888" / "stat").write_text("garbage", encoding="utf-8")

    assert find_stale_sibling_pids(proc_root=tmp_path, pid=6278) == []


def test_pid_reused_before_sigterm(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)

    # Change identity before the signal
    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
    write_proc_entry(tmp_path, 6270, start_ticks=900)  # reused

    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert report["skipped"] == [6270]
    assert report["terminated"] == []
    assert report["killed"] == []
    assert not kill.calls


def test_pid_reused_between_sigterm_and_sigkill(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)

    # Process exits on SIGTERM, and while we wait, PID is reused.
    def sleep_and_reuse(_s: float) -> None:
        kill._reap(6270)
        write_proc_entry(tmp_path, 6270, start_ticks=900)

    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=sleep_and_reuse, proc_root=tmp_path
    )

    assert report["terminated"] == [6270]
    assert report["killed"] == []
    assert report["skipped"] == []
    # SIGTERM sent to original, but SIGKILL not sent because it changed during wait
    assert kill.calls == [(6270, signal.SIGTERM)]


def test_uid_changes_while_waiting(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)

    def sleep_and_change_uid(_s: float) -> None:
        write_proc_entry(tmp_path, 6270, uid=0, start_ticks=500)

    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=sleep_and_change_uid, proc_root=tmp_path
    )

    assert kill.calls == [
        (6270, signal.SIGTERM)
    ]  # Sends term, wait loop notices change and treats it as gone?
    # Wait, if UID changes between TERM and KILL, we should treat it as gone, so it goes in "terminated" ?
    # Let's verify report expectations. "terminated: original identity disappeared after SIGTERM"
    assert report["terminated"] == [6270]


def test_cmdline_changes_while_waiting(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)

    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
    write_proc_entry(tmp_path, 6270, cmdline=OTHER_TITLE, start_ticks=500)  # changed before SIGTERM

    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )
    assert report["skipped"] == [6270]
    assert kill.calls == []


def test_malformed_identity_data_while_waiting(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)
    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)

    # Corrupt the stat file before sigterm
    (tmp_path / "6270" / "stat").write_text("garbage", encoding="utf-8")

    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )
    assert report["skipped"] == [6270]
    assert kill.calls == []


def test_terminate_uses_sigterm_first(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)
    kill.exit_on_term.add(6270)
    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)

    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert report["terminated"] == [6270]
    assert report["killed"] == []
    assert (6270, signal.SIGKILL) not in kill.calls


def test_terminate_escalates_to_sigkill(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500)
    kill = FakeKill(tmp_path)
    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)

    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert (6270, signal.SIGTERM) in kill.calls
    assert (6270, signal.SIGKILL) in kill.calls
    assert report["killed"] == [6270]


def test_terminate_treats_zombie_as_exited(tmp_path: Path) -> None:
    write_proc_entry(tmp_path, 6270, start_ticks=500, state="Z")
    kill = FakeKill(tmp_path)
    sibling = SiblingProcess(pid=6270, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)

    report = terminate_stale_siblings(
        [sibling], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )

    assert report["terminated"] == [6270]
    assert (6270, signal.SIGTERM) not in kill.calls
    assert (6270, signal.SIGKILL) not in kill.calls


def test_terminate_never_signals_init_or_negative_pids(tmp_path: Path) -> None:
    kill = FakeKill()
    s1 = SiblingProcess(pid=0, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
    s2 = SiblingProcess(pid=1, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
    s3 = SiblingProcess(pid=-5, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)

    report = terminate_stale_siblings(
        [s1, s2, s3], kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
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


def test_refuse_oversized_match_sets_limit_is_respected(tmp_path: Path) -> None:
    # 8 identities should be allowed, 9 should be refused.
    kill = FakeKill(tmp_path)
    logger = FakeLogger()

    # Write 8 identities
    for i in range(1000, 1008):
        write_proc_entry(tmp_path, i, start_ticks=500)
    write_proc_entry(tmp_path, 2000, start_ticks=600)
    report = enforce_single_instance(
        logger, proc_root=tmp_path, pid=2000, kill_fn=kill, sleep_fn=lambda _s: None
    )
    assert report["status"] == "ok"
    assert len(report["killed"] + report["terminated"]) == 8

    # Write 9 identities
    for i in range(1000, 1009):
        write_proc_entry(tmp_path, i, start_ticks=500)
    write_proc_entry(tmp_path, 2000, start_ticks=600)

    kill = FakeKill(tmp_path)
    logger = FakeLogger()
    report = enforce_single_instance(
        logger, proc_root=tmp_path, pid=2000, kill_fn=kill, sleep_fn=lambda _s: None
    )
    assert report["status"] == "failed"
    assert "too_many_stale_siblings" in report.get("reason", "")
    assert len(report.get("refused", [])) == 9
    assert not kill.calls


def test_invalid_pids_do_not_consume_limit(tmp_path: Path) -> None:
    kill = FakeKill(tmp_path)
    logger = FakeLogger()
    for i in range(1000, 1008):
        write_proc_entry(tmp_path, i, start_ticks=500)
    # Write some invalid ones <= 1
    write_proc_entry(tmp_path, 0, start_ticks=500)
    write_proc_entry(tmp_path, 1, start_ticks=500)

    write_proc_entry(tmp_path, 2000, start_ticks=600)
    report = enforce_single_instance(
        logger, proc_root=tmp_path, pid=2000, kill_fn=kill, sleep_fn=lambda _s: None
    )
    assert report["status"] == "ok"
    assert len(report["killed"] + report["terminated"]) == 8


def test_duplicate_identities_do_not_consume_limit_twice(tmp_path: Path) -> None:
    kill = FakeKill(tmp_path)
    # Write 8 identities
    for i in range(1000, 1008):
        write_proc_entry(tmp_path, i, start_ticks=500)

    # In singleton logic, we deduplicate by (pid, start_ticks) if duplicate find occurs.
    # We can test by passing duplicates directly to terminate_stale_siblings

    siblings = [
        SiblingProcess(pid=i, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
        for i in range(1000, 1008)
    ]
    siblings.append(
        SiblingProcess(pid=1000, uid=1000, start_ticks=500, cmdline=PLUGIN_TITLE)
    )  # duplicate

    report = terminate_stale_siblings(
        siblings, kill_fn=kill, sleep_fn=lambda _s: None, proc_root=tmp_path
    )
    assert not report.get("refused")
    assert len(report["killed"] + report["terminated"]) == 8
