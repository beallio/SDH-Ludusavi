"""Terminate stale sibling backend instances left behind by Decky races.

Decky v3.2.4's ``import_plugin`` awaits between its duplicate check and
``self.plugins[name] = plugin.start()``; during the post-install reload storm
two callers can both start a backend process and the second dict insert
orphans the first — it stays alive forever with no owner. The youngest
instance is always the one Decky ends up owning (last insert wins), so on
startup the new instance terminates any strictly-older process that has the
same uid and a byte-identical ``/proc/<pid>/cmdline`` (Decky's setproctitle
gives every instance of one plugin the same title).
"""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

KillFn = Callable[[int, int], None]
SleepFn = Callable[[float], None]

_MAX_STALE_SIBLINGS = 8
_TERM_TIMEOUT_SECONDS = 3.0
_KILL_TIMEOUT_SECONDS = 1.0
_POLL_INTERVAL_SECONDS = 0.1


@dataclass(frozen=True)
class SiblingProcess:
    pid: int
    uid: int
    start_ticks: int
    cmdline: bytes


def _read_start_ticks(proc_root: Path, pid: int) -> int | None:
    try:
        data = (proc_root / str(pid) / "stat").read_bytes()
        _, _, after_comm = data.rpartition(b")")
        fields = after_comm.split()
        return int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


def _read_state(proc_root: Path, pid: int) -> str | None:
    try:
        data = (proc_root / str(pid) / "stat").read_bytes()
        _, _, after_comm = data.rpartition(b")")
        fields = after_comm.split()
        return fields[0].decode("ascii", "replace")
    except (OSError, IndexError):
        return None


def _read_uid(proc_root: Path, pid: int) -> int | None:
    try:
        for line in (proc_root / str(pid) / "status").read_text(encoding="ascii").splitlines():
            if line.startswith("Uid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _capture_identity(proc_root: Path, pid: int) -> SiblingProcess | None:
    ticks_before = _read_start_ticks(proc_root, pid)
    if ticks_before is None:
        return None
    uid = _read_uid(proc_root, pid)
    if uid is None:
        return None
    try:
        cmdline = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    if not cmdline:
        return None
    state = _read_state(proc_root, pid)
    if state is None or state == "Z":
        return None
    ticks_after = _read_start_ticks(proc_root, pid)
    if ticks_after != ticks_before:
        return None

    return SiblingProcess(pid=pid, uid=uid, start_ticks=ticks_before, cmdline=cmdline)


def _check_identity_status(proc_root: Path, sibling: SiblingProcess) -> str:
    if not (proc_root / str(sibling.pid)).exists():
        return "gone"
    state = _read_state(proc_root, sibling.pid)
    if state == "Z":
        return "gone"

    current = _capture_identity(proc_root, sibling.pid)
    if current is None:
        return "changed"
    if current != sibling:
        return "changed"
    return "running"


def find_stale_siblings(
    *, proc_root: Path = Path("/proc"), pid: int | None = None
) -> list[SiblingProcess]:
    own_pid = os.getpid() if pid is None else pid
    own_identity = _capture_identity(proc_root, own_pid)
    if own_identity is None:
        return []

    stale: list[SiblingProcess] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        other_pid = int(entry.name)
        if other_pid == own_pid:
            continue
        other_identity = _capture_identity(proc_root, other_pid)
        if other_identity is None:
            continue
        if other_identity.cmdline != own_identity.cmdline:
            continue
        if other_identity.uid != own_identity.uid:
            continue
        if (other_identity.start_ticks, other_identity.pid) < (
            own_identity.start_ticks,
            own_identity.pid,
        ):
            stale.append(other_identity)
    return stale


def _wait_until_gone(
    siblings: list[SiblingProcess],
    *,
    proc_root: Path,
    sleep_fn: SleepFn,
    timeout_seconds: float,
) -> tuple[list[SiblingProcess], list[SiblingProcess], list[SiblingProcess]]:
    remaining = siblings[:]
    gone: list[SiblingProcess] = []
    changed: list[SiblingProcess] = []
    waited = 0.0
    while remaining and waited < timeout_seconds:
        sleep_fn(_POLL_INTERVAL_SECONDS)
        waited += _POLL_INTERVAL_SECONDS

        still_running = []
        for sibling in remaining:
            status = _check_identity_status(proc_root, sibling)
            if status == "gone":
                gone.append(sibling)
            elif status == "changed":
                changed.append(sibling)
            else:
                still_running.append(sibling)
        remaining = still_running
    return remaining, gone, changed


def _record_pid(report: dict[str, list[int]], key: str, pid: int) -> None:
    if pid not in report[key]:
        report[key].append(pid)


def _is_complete_identity(sibling: SiblingProcess) -> bool:
    if type(sibling.pid) is not int or sibling.pid <= 1:
        return False
    if type(sibling.uid) is not int or sibling.uid < 0:
        return False
    if type(sibling.start_ticks) is not int or sibling.start_ticks < 0:
        return False
    if not isinstance(sibling.cmdline, bytes) or not sibling.cmdline:
        return False
    return True


def terminate_stale_siblings(
    siblings: list[SiblingProcess],
    *,
    kill_fn: KillFn = os.kill,
    sleep_fn: SleepFn = time.sleep,
    proc_root: Path = Path("/proc"),
    term_timeout_seconds: float = _TERM_TIMEOUT_SECONDS,
) -> dict[str, list[int]]:
    report: dict[str, list[int]] = {
        "terminated": [],
        "killed": [],
        "skipped": [],
        "failed": [],
        "refused": [],
    }

    seen: set[tuple[int, int]] = set()
    unique_candidates: list[SiblingProcess] = []

    for sibling in siblings:
        if not _is_complete_identity(sibling):
            if type(sibling.pid) is int and sibling.pid > 0:
                _record_pid(report, "skipped", sibling.pid)
            continue

        key = (sibling.pid, sibling.start_ticks)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(sibling)

    unique_candidates.sort(key=lambda s: s.pid)

    if len(unique_candidates) > _MAX_STALE_SIBLINGS:
        for s in unique_candidates:
            _record_pid(report, "refused", s.pid)
        return report

    signalled: list[SiblingProcess] = []
    for sibling in unique_candidates:
        status = _check_identity_status(proc_root, sibling)
        if status == "gone":
            _record_pid(report, "terminated", sibling.pid)
            continue
        if status == "changed":
            _record_pid(report, "skipped", sibling.pid)
            continue

        try:
            kill_fn(sibling.pid, signal.SIGTERM)
            signalled.append(sibling)
        except ProcessLookupError:
            _record_pid(report, "terminated", sibling.pid)
        except OSError:
            _record_pid(report, "failed", sibling.pid)

    survivors, gone_after_term, changed_after_term = _wait_until_gone(
        signalled, proc_root=proc_root, sleep_fn=sleep_fn, timeout_seconds=term_timeout_seconds
    )
    for s in gone_after_term:
        _record_pid(report, "terminated", s.pid)
    for s in changed_after_term:
        _record_pid(report, "skipped", s.pid)

    killed: list[SiblingProcess] = []
    for sibling in survivors:
        status = _check_identity_status(proc_root, sibling)
        if status == "gone":
            _record_pid(report, "terminated", sibling.pid)
            continue
        if status == "changed":
            _record_pid(report, "skipped", sibling.pid)
            continue

        try:
            kill_fn(sibling.pid, signal.SIGKILL)
            killed.append(sibling)
        except ProcessLookupError:
            _record_pid(report, "terminated", sibling.pid)
        except OSError:
            _record_pid(report, "failed", sibling.pid)

    still_alive, gone_after_kill, changed_after_kill = _wait_until_gone(
        killed, proc_root=proc_root, sleep_fn=sleep_fn, timeout_seconds=_KILL_TIMEOUT_SECONDS
    )
    for s in gone_after_kill:
        _record_pid(report, "killed", s.pid)
    for s in changed_after_kill:
        _record_pid(report, "skipped", s.pid)
    for s in still_alive:
        _record_pid(report, "failed", s.pid)
    return report


def enforce_single_instance(
    logger: logging.Logger | Any,
    *,
    proc_root: Path = Path("/proc"),
    pid: int | None = None,
    kill_fn: KillFn = os.kill,
    sleep_fn: SleepFn = time.sleep,
) -> dict[str, Any]:
    try:
        siblings = find_stale_siblings(proc_root=proc_root, pid=pid)
        if not siblings:
            return {"status": "ok", "stale_pids": []}

        stale_pids = sorted(s.pid for s in siblings)

        logger.warning(
            "Stale sibling backend instance(s) detected: %s; terminating "
            "(Decky import race leaves orphaned processes after updates)",
            stale_pids,
        )
        report = terminate_stale_siblings(
            siblings, kill_fn=kill_fn, sleep_fn=sleep_fn, proc_root=proc_root
        )

        if report.get("refused"):
            logger.error(
                "Too many stale siblings detected (count=%d). Refusing to kill: %s",
                len(report["refused"]),
                report["refused"],
            )
            return {
                "status": "failed",
                "reason": "too_many_stale_siblings",
                "stale_pids": stale_pids,
                **report,
            }

        if report["failed"]:
            logger.error("Failed to terminate stale sibling instance(s): %s", report["failed"])
        else:
            logger.warning(
                "Stale sibling cleanup finished: terminated=%s killed=%s skipped=%s",
                report["terminated"],
                report["killed"],
                report["skipped"],
            )
        return {"status": "ok", "stale_pids": stale_pids, **report}
    # Intentionally broad to protect plugin startup
    except Exception as exc:
        try:
            logger.error("Singleton guard failed: %s", exc)
        # Intentionally broad inside fallback
        except Exception:
            pass
        return {"status": "failed", "message": str(exc), "stale_pids": []}
