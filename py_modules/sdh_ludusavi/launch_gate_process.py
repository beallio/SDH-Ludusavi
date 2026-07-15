from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .launch_gate import MAX_PID, MAX_REASON_LENGTH, ScopeDiscoveryError

# Steam Deck measurements put SIGSTOP delivery at 0.16-0.87ms, including under
# fsync I/O load. 100ms is a generous tunable default, not a proven ceiling.
SIGSTOP_DELIVERY_TIMEOUT_SECONDS = 0.1
SIGSTOP_DELIVERY_POLL_SECONDS = 0.0005


@dataclass(frozen=True)
class LaunchProcessIdentity:
    pid: int
    owner_uid: int
    start_ticks: int


def _parse_start_ticks(content: str, expected_pid: int) -> int:
    open_paren = content.find("(")
    close_paren = content.rfind(")")
    if open_paren <= 0 or close_paren <= open_paren:
        raise ScopeDiscoveryError("Launch PID stat identity is malformed")
    if content[:open_paren].strip() != str(expected_pid):
        raise ScopeDiscoveryError("Launch PID stat identity is malformed")
    fields = content[close_paren + 1 :].split()
    if len(fields) <= 19:
        raise ScopeDiscoveryError("Launch PID stat identity is malformed")
    try:
        start_ticks = int(fields[19])
    except ValueError as exc:
        raise ScopeDiscoveryError("Launch PID stat identity is malformed") from exc
    if start_ticks < 0:
        raise ScopeDiscoveryError("Launch PID stat identity is malformed")
    return start_ticks


def _read_process_identity(
    proc_root: str | Path,
    pid: int,
) -> LaunchProcessIdentity | None:
    proc_dir = Path(proc_root) / str(pid)
    try:
        owner_uid = proc_dir.stat().st_uid
        stat_text = (proc_dir / "stat").read_text(encoding="utf-8")
        start_ticks = _parse_start_ticks(stat_text, pid)
    except (OSError, UnicodeError, ScopeDiscoveryError):
        return None
    return LaunchProcessIdentity(pid, owner_uid, start_ticks)


def _matches_process_identity(
    proc_root: str | Path,
    expected: LaunchProcessIdentity,
) -> bool:
    return _read_process_identity(proc_root, expected.pid) == expected


def _read_stat_state(stat_path: Path) -> str | None:
    try:
        content = stat_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    close_paren = content.rfind(")")
    if close_paren < 0:
        return None
    fields = content[close_paren + 1 :].split()
    return fields[0] if fields else None


def _read_process_state(proc_root: str | Path, pid: int) -> str | None:
    return _read_stat_state(Path(proc_root) / str(pid) / "stat")


def _is_stopped(proc_root: str | Path, pid: int) -> bool:
    return _read_process_state(proc_root, pid) == "T"


def _read_thread_group_state(proc_root: str | Path, pid: int) -> str:
    task_stats = sorted((Path(proc_root) / str(pid) / "task").glob("*/stat"))
    if not task_stats:
        return "unreadable"
    states = tuple(_read_stat_state(path) for path in task_stats)
    for state in states:
        if state is None:
            return "unreadable"
        if state != "T":
            return state
    return "T"


def _thread_group_is_stopped(proc_root: str | Path, pid: int) -> bool:
    return _read_thread_group_state(proc_root, pid) == "T"


def _read_tracer_pid(proc_root: str | Path, pid: int) -> str:
    try:
        status = (Path(proc_root) / str(pid) / "status").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "unreadable"
    for line in status.splitlines():
        name, separator, value = line.partition(":")
        if separator and name == "TracerPid":
            return value.strip() or "unreadable"
    return "unreadable"


def _wait_until_stopped(
    proc_root: str | Path,
    pid: int,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    monotonic: Callable[[], float],
    wait: Callable[[float], None],
) -> str:
    if timeout_seconds < 0:
        raise ValueError("SIGSTOP delivery timeout cannot be negative")
    if poll_seconds <= 0:
        raise ValueError("SIGSTOP delivery poll interval must be positive")

    deadline = monotonic() + timeout_seconds
    observed = _read_thread_group_state(proc_root, pid)
    if observed == "T":
        return observed

    while monotonic() < deadline:
        remaining = deadline - monotonic()
        wait(min(poll_seconds, remaining))
        if monotonic() >= deadline:
            break
        observed = _read_thread_group_state(proc_root, pid)
        if observed == "T":
            return observed

    if observed == "t":
        return f"t; TracerPid={_read_tracer_pid(proc_root, pid)}"
    return observed


def _has_children(proc_root: str | Path, pid: int) -> bool:
    try:
        children_files = list((Path(proc_root) / str(pid) / "task").glob("*/children"))
        if not children_files:
            return True
        return any(path.read_text(encoding="utf-8").strip() for path in children_files)
    except (OSError, UnicodeError):
        return True


def _coerce_signal_pid(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("PID must be an integer, not a boolean")
    if isinstance(value, int):
        pid = value
    elif isinstance(value, str):
        try:
            pid = int(value.strip())
        except ValueError as exc:
            raise ValueError("PID must be a valid integer string") from exc
    elif isinstance(value, float):
        raise ValueError("PID must be an integer, not a float")
    else:
        raise ValueError("PID must be an integer or integer string")
    if pid <= 1:
        raise ValueError(f"Refusing unsafe PID value: {pid}")
    if pid > MAX_PID:
        raise ValueError("PID value exceeds maximum 32-bit integer limit")
    return pid


def _bounded_reason(value: object) -> str:
    return " ".join(str(value).split())[:MAX_REASON_LENGTH] or "Scope acquisition failed"
