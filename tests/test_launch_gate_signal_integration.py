from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from sdh_ludusavi.launch_gate_process import _wait_until_stopped


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="requires Linux /proc and POSIX job control",
)


def _release_and_reap(child: subprocess.Popen[str]) -> None:
    try:
        os.kill(child.pid, signal.SIGCONT)
    finally:
        try:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


def _stop_child(child: subprocess.Popen[str]) -> None:
    os.kill(child.pid, signal.SIGSTOP)
    # waitpid can confirm delivery deterministically only because this is our child;
    # the Steam reaper is not, so production must use the bounded /proc waiter.
    waited_pid, status = os.waitpid(child.pid, os.WUNTRACED)
    assert waited_pid == child.pid
    assert os.WIFSTOPPED(status)


def test_wait_until_stopped_observes_real_sigstop_delivery() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time\nwhile True: time.sleep(1)"],
        text=True,
    )
    try:
        _stop_child(child)

        observed = _wait_until_stopped(
            "/proc",
            child.pid,
            timeout_seconds=2.0,
            poll_seconds=0.0005,
            monotonic=time.monotonic,
            wait=time.sleep,
        )

        assert observed == "T"
    finally:
        _release_and_reap(child)


def test_wait_until_stopped_observes_real_multithreaded_group_stop() -> None:
    script = """
import threading

def spin():
    while True:
        pass

threads = [threading.Thread(target=spin, daemon=True) for _ in range(4)]
for thread in threads:
    thread.start()
print("ready", flush=True)
spin()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        _stop_child(child)

        observed = _wait_until_stopped(
            "/proc",
            child.pid,
            timeout_seconds=2.0,
            poll_seconds=0.0005,
            monotonic=time.monotonic,
            wait=time.sleep,
        )

        assert observed == "T"
    finally:
        _release_and_reap(child)
