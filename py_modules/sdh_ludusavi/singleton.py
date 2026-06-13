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
from pathlib import Path
from typing import Any, Callable

KillFn = Callable[[int, int], None]
SleepFn = Callable[[float], None]

# A storm should only ever leak a handful of instances; anything beyond this
# suggests the identity match is wrong, so refuse to signal.
_MAX_STALE_SIBLINGS = 8
_TERM_TIMEOUT_SECONDS = 3.0
_KILL_TIMEOUT_SECONDS = 1.0
_POLL_INTERVAL_SECONDS = 0.1


def _read_start_ticks(proc_root: Path, pid: int) -> int | None:
    """Field 22 of /proc/<pid>/stat (starttime in clock ticks)."""
    try:
        data = (proc_root / str(pid) / "stat").read_bytes()
        _, _, after_comm = data.rpartition(b")")
        fields = after_comm.split()
        # after_comm holds fields 3..52; starttime (field 22) is index 19.
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


def _is_running(proc_root: Path, pid: int) -> bool:
    """A vanished or zombie process no longer needs signalling."""
    state = _read_state(proc_root, pid)
    return state is not None and state != "Z"


def find_stale_sibling_pids(
    *, proc_root: Path = Path("/proc"), pid: int | None = None
) -> list[int]:
    """Pids of strictly-older processes with our exact cmdline and uid."""
    own_pid = os.getpid() if pid is None else pid
    try:
        own_cmdline = (proc_root / str(own_pid) / "cmdline").read_bytes()
        own_uid = _read_uid(proc_root, own_pid)
        own_ticks = _read_start_ticks(proc_root, own_pid)
    except OSError:
        return []
    if not own_cmdline or own_uid is None or own_ticks is None:
        return []

    stale: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        other_pid = int(entry.name)
        if other_pid == own_pid:
            continue
        try:
            if (entry / "cmdline").read_bytes() != own_cmdline:
                continue
        except OSError:
            continue
        if _read_uid(proc_root, other_pid) != own_uid:
            continue
        other_ticks = _read_start_ticks(proc_root, other_pid)
        if other_ticks is None:
            continue
        # Strictly older only: in a mutual scan, exactly one instance (the
        # youngest — Decky's dict winner) survives.
        if (other_ticks, other_pid) < (own_ticks, own_pid):
            stale.append(other_pid)
    return sorted(stale)


def _wait_until_gone(
    pids: list[int],
    *,
    proc_root: Path,
    sleep_fn: SleepFn,
    timeout_seconds: float,
) -> list[int]:
    remaining = [pid for pid in pids if _is_running(proc_root, pid)]
    waited = 0.0
    while remaining and waited < timeout_seconds:
        sleep_fn(_POLL_INTERVAL_SECONDS)
        waited += _POLL_INTERVAL_SECONDS
        remaining = [pid for pid in remaining if _is_running(proc_root, pid)]
    return remaining


def terminate_stale_siblings(
    pids: list[int],
    *,
    kill_fn: KillFn = os.kill,
    sleep_fn: SleepFn = time.sleep,
    proc_root: Path = Path("/proc"),
    term_timeout_seconds: float = _TERM_TIMEOUT_SECONDS,
) -> dict[str, list[int]]:
    """SIGTERM the given pids, escalate survivors to SIGKILL."""
    candidates = [pid for pid in pids if pid > 1][:_MAX_STALE_SIBLINGS]
    report: dict[str, list[int]] = {"terminated": [], "killed": [], "failed": []}

    signalled: list[int] = []
    for pid in candidates:
        try:
            kill_fn(pid, signal.SIGTERM)
            signalled.append(pid)
        except ProcessLookupError:
            report["terminated"].append(pid)
        except OSError:
            report["failed"].append(pid)

    survivors = _wait_until_gone(
        signalled, proc_root=proc_root, sleep_fn=sleep_fn, timeout_seconds=term_timeout_seconds
    )
    report["terminated"].extend(pid for pid in signalled if pid not in survivors)

    killed: list[int] = []
    for pid in survivors:
        try:
            kill_fn(pid, signal.SIGKILL)
            killed.append(pid)
        except ProcessLookupError:
            report["terminated"].append(pid)
        except OSError:
            report["failed"].append(pid)

    still_alive = _wait_until_gone(
        killed, proc_root=proc_root, sleep_fn=sleep_fn, timeout_seconds=_KILL_TIMEOUT_SECONDS
    )
    report["killed"].extend(pid for pid in killed if pid not in still_alive)
    report["failed"].extend(still_alive)
    return report


def enforce_single_instance(
    logger: logging.Logger | Any,
    *,
    proc_root: Path = Path("/proc"),
    pid: int | None = None,
    kill_fn: KillFn = os.kill,
    sleep_fn: SleepFn = time.sleep,
) -> dict[str, Any]:
    """Find and terminate stale siblings; never raises."""
    try:
        stale = find_stale_sibling_pids(proc_root=proc_root, pid=pid)
        if not stale:
            return {"status": "ok", "stale_pids": []}
        logger.warning(
            "Stale sibling backend instance(s) detected: %s; terminating "
            "(Decky import race leaves orphaned processes after updates)",
            stale,
        )
        report = terminate_stale_siblings(
            stale, kill_fn=kill_fn, sleep_fn=sleep_fn, proc_root=proc_root
        )
        if report["failed"]:
            logger.error("Failed to terminate stale sibling instance(s): %s", report["failed"])
        else:
            logger.warning(
                "Stale sibling cleanup finished: terminated=%s killed=%s",
                report["terminated"],
                report["killed"],
            )
        return {"status": "ok", "stale_pids": stale, **report}
    # Intentionally broad: the guard must never block plugin startup.
    except Exception as exc:
        try:
            logger.error("Singleton guard failed: %s", exc)
        # Intentionally broad: even logging the failure must not raise.
        except Exception:
            pass
        return {"status": "failed", "message": str(exc), "stale_pids": []}
