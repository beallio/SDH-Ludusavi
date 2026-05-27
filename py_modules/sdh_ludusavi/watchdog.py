from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger("sdh_ludusavi.service.watchdog")
MAX_SIGNAL_PID = 2_147_483_647


class ProcessWatchdog:
    """Manages pausing and resuming process trees, and checks for stuck suspended

    game processes using a daemon thread.
    """

    def __init__(
        self,
        service: Any,
        log_callback: Callable[[str, str, str | None, str | None], None],
        is_operation_running: Callable[[], bool],
    ) -> None:
        self._service = service
        self._log = log_callback
        self._is_operation_running = is_operation_running
        self._paused_pids: dict[int, float] = {}
        self._paused_pids_lock = threading.Lock()
        self._watchdog_active = False
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()

    def pause(self, pid: int) -> dict[str, object]:
        """Suspend a launched game process tree while start sync runs."""
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError as exc:
            self._log("warning", f"Invalid PID passed to pause: {exc}", "launch_gate", None)
            return {"status": "failed", "message": str(exc)}

        if not _send_signal_tree(valid_pid, signal.SIGSTOP):
            self._log(
                "warning",
                f"Unable to pause game process tree rooted at PID {valid_pid}",
                "launch_gate",
                None,
            )
            return {"status": "failed", "pid": valid_pid, "message": "Unable to pause game process"}

        with self._paused_pids_lock:
            self._paused_pids[valid_pid] = time.time()
            self._ensure_watchdog_running()
        self._log(
            "info", f"Paused game process tree rooted at PID {valid_pid}", "launch_gate", None
        )
        return {"status": "paused", "pid": valid_pid}

    def resume(self, pid: int) -> dict[str, object]:
        """Resume a previously suspended game process tree."""
        try:
            valid_pid = _coerce_signal_pid(pid)
        except ValueError as exc:
            self._log("warning", f"Invalid PID passed to resume: {exc}", "launch_gate", None)
            return {"status": "failed", "message": str(exc)}

        if not _send_signal_tree(valid_pid, signal.SIGCONT):
            self._log(
                "warning",
                f"Failed to send SIGCONT to process tree rooted at PID {valid_pid}",
                "launch_gate",
                None,
            )
            return {
                "status": "failed",
                "pid": valid_pid,
                "message": "Unable to resume game process",
            }

        with self._paused_pids_lock:
            self._paused_pids.pop(valid_pid, None)
        self._log(
            "info", f"Resumed game process tree rooted at PID {valid_pid}", "launch_gate", None
        )
        return {"status": "resumed", "pid": valid_pid}

    def resume_all(self) -> None:
        """Best-effort cleanup for plugin unload or launch-gate failures."""
        with self._paused_pids_lock:
            paused_pids = sorted(self._paused_pids.keys())
        for pid in paused_pids:
            try:
                self.resume(pid)
            # Intentionally broad: catch resume exceptions during cleanup/unload
            except Exception as exc:
                self._log(
                    "warning", f"Unable to resume paused PID {pid}: {exc}", "launch_gate", None
                )

    def stop(self) -> None:
        """Shut down the watchdog thread and resume all paused processes."""
        self._watchdog_stop.set()
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=1.0)
        self.resume_all()

    def _ensure_watchdog_running(self) -> None:
        if not self._watchdog_active:
            self._watchdog_active = True
            self._watchdog_stop.clear()
            thread = threading.Thread(
                target=self._watchdog_loop,
                name="sdh-ludusavi-watchdog",
                daemon=True,
            )
            self._watchdog_thread = thread
            thread.start()

    def _watchdog_loop(self) -> None:
        while True:
            if self._watchdog_stop.wait(timeout=1.0):
                with self._paused_pids_lock:
                    self._watchdog_active = False
                break

            with self._paused_pids_lock:
                if not self._paused_pids:
                    self._watchdog_active = False
                    break

            self._check_and_resume_stuck_pids()

    def _check_and_resume_stuck_pids(self) -> None:
        now = time.time()
        stuck_pids = []
        with self._paused_pids_lock:
            if not self._paused_pids:
                self._watchdog_active = False
                return
            # If a Ludusavi operation is actively running (e.g., slow cloud sync),
            # do not auto-resume any processes yet.
            if self._is_operation_running():
                return
            for pid, paused_at in list(self._paused_pids.items()):
                if now - paused_at > 15.0:
                    stuck_pids.append(pid)

        for pid in stuck_pids:
            self._log(
                "warning",
                f"Watchdog detected PID {pid} suspended for too long. Resuming automatically.",
                "watchdog",
                None,
            )
            try:
                self.resume(pid)
            # Intentionally broad: catch automatic resume errors in background watchdog thread
            except Exception as exc:
                self._log(
                    "error",
                    f"Watchdog failed to resume stuck PID {pid}: {exc}",
                    "watchdog",
                    None,
                )


def _coerce_signal_pid(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("PID must be an integer, not a boolean")
    if isinstance(value, int):
        pid = value
    elif isinstance(value, str):
        cleaned = value.strip()
        try:
            pid = int(cleaned)
        except ValueError as exc:
            raise ValueError("PID must be a valid integer string") from exc
    elif isinstance(value, float):
        raise ValueError("PID must be an integer, not a float")
    else:
        raise ValueError("PID must be an integer or integer string")

    if pid <= 1:
        raise ValueError(f"Refusing to signal unsafe PID value: {pid}")
    if pid > MAX_SIGNAL_PID:
        raise ValueError("PID value exceeds maximum 32-bit integer limit")
    return pid


def _send_signal_tree(pid: int, sig: signal.Signals) -> bool:
    sent = False
    for target_pid in _process_tree(pid):
        try:
            os.kill(target_pid, sig)
            sent = True
        except OSError:
            if target_pid == pid:
                return False
    return sent


def _read_ppid(pid_str: str, *, proc_root: str = "/proc") -> int | None:
    try:
        with open(f"{proc_root}/{pid_str}/stat", encoding="utf-8") as fh:
            stat = fh.readline()
        comm_end = stat.rfind(")")
        if comm_end == -1:
            return None
        fields = stat[comm_end + 2 :].split()
        if len(fields) < 2:
            return None
        return int(fields[1])
    except (OSError, ValueError, IndexError):
        return None


def _process_tree(pid: int) -> list[int]:
    try:
        entries = os.listdir("/proc")
    except OSError:
        return [pid]

    children_by_parent: dict[int, list[int]] = {}
    for entry in entries:
        if not entry.isdigit():
            continue
        ppid = _read_ppid(entry)
        if ppid is None:
            continue
        children_by_parent.setdefault(ppid, []).append(int(entry))

    ordered: list[int] = []
    visited: set[int] = set()
    stack = [pid]
    while stack:
        target_pid = stack.pop()
        if target_pid in visited:
            continue
        visited.add(target_pid)
        ordered.append(target_pid)
        stack.extend(sorted(children_by_parent.get(target_pid, []), reverse=True))
    return ordered


def _child_pids(pid: int) -> list[int]:
    return _process_tree(pid)[1:]
