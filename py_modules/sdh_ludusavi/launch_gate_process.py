from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .launch_gate import MAX_PID, MAX_REASON_LENGTH, ScopeDiscoveryError


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


def _is_stopped(proc_root: str | Path, pid: int) -> bool:
    try:
        content = (Path(proc_root) / str(pid) / "stat").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    close_paren = content.rfind(")")
    if close_paren < 0:
        return False
    fields = content[close_paren + 1 :].split()
    return bool(fields) and fields[0] == "T"


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
