"""Tests for the daemon RPC thread pool.

The pool exists so that an in-flight RPC can never keep a dying plugin process
alive: Decky Loader stops plugins with SystemExit, and concurrent.futures'
ThreadPoolExecutor registers an atexit join that blocks interpreter shutdown
until running callbacks finish. DaemonThreadPool must therefore use daemon
threads that are not joined at interpreter exit, while still returning real
concurrent.futures.Future objects so asyncio's loop.run_in_executor works.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import CancelledError, Future
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sdh_ludusavi.rpc_pool import DaemonThreadPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def pool():
    pool = DaemonThreadPool(max_workers=2, thread_name_prefix="test-pool")
    yield pool
    pool.shutdown(wait=False, cancel_futures=True)


def test_submit_returns_concurrent_future_with_result(pool: DaemonThreadPool) -> None:
    future = pool.submit(lambda: "ok")

    assert isinstance(future, Future)
    assert future.result(timeout=5) == "ok"


def test_submit_passes_args_and_kwargs(pool: DaemonThreadPool) -> None:
    future = pool.submit(lambda a, b=0: a + b, 2, b=3)

    assert future.result(timeout=5) == 5


def test_worker_exception_propagates_through_future(pool: DaemonThreadPool) -> None:
    def boom() -> None:
        raise ValueError("boom")

    future = pool.submit(boom)

    with pytest.raises(ValueError, match="boom"):
        future.result(timeout=5)


def test_worker_threads_are_daemon(pool: DaemonThreadPool) -> None:
    barrier = threading.Event()
    release = threading.Event()

    def task() -> None:
        barrier.set()
        release.wait(timeout=5)

    pool.submit(task)
    assert barrier.wait(timeout=5)
    try:
        workers = [
            thread for thread in threading.enumerate() if thread.name.startswith("test-pool")
        ]
        assert workers, "expected at least one running pool worker thread"
        assert all(thread.daemon for thread in workers)
    finally:
        release.set()


def test_shutdown_cancels_queued_futures(pool: DaemonThreadPool) -> None:
    release = threading.Event()
    started = threading.Event()

    def blocker() -> None:
        started.set()
        release.wait(timeout=5)

    # Saturate both workers, then queue one more task that must never start.
    pool.submit(blocker)
    pool.submit(blocker)
    assert started.wait(timeout=5)
    queued = pool.submit(lambda: "never runs")

    pool.shutdown(wait=False, cancel_futures=True)
    release.set()

    assert queued.cancelled()
    with pytest.raises(CancelledError):
        queued.result(timeout=1)


def test_submit_after_shutdown_raises_runtime_error(pool: DaemonThreadPool) -> None:
    pool.shutdown(wait=False, cancel_futures=True)

    with pytest.raises(RuntimeError):
        pool.submit(lambda: "nope")


def test_shutdown_wait_joins_idle_workers() -> None:
    pool = DaemonThreadPool(max_workers=2, thread_name_prefix="test-pool-join")
    futures = [pool.submit(lambda: 1) for _ in range(4)]
    for future in futures:
        assert future.result(timeout=5) == 1

    pool.shutdown(wait=True, cancel_futures=True)

    workers = [
        thread for thread in threading.enumerate() if thread.name.startswith("test-pool-join")
    ]
    assert workers == []


def test_run_blocking_integration_with_daemon_pool() -> None:
    mock_decky = types.SimpleNamespace(logger=MagicMock())
    sys.modules.setdefault("decky", mock_decky)
    from main import _run_blocking

    pool = DaemonThreadPool(max_workers=2, thread_name_prefix="test-pool-rb")
    try:

        async def scenario() -> str:
            return await _run_blocking(pool, lambda: "via-loop")

        assert asyncio.run(scenario()) == "via-loop"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def test_interpreter_exit_is_not_blocked_by_running_task() -> None:
    """Regression test for the lingering-unload bug.

    A process whose pool worker is mid-task must still exit promptly when the
    main thread finishes; ThreadPoolExecutor would block here for the full
    sleep duration via its atexit join.
    """
    script = (
        "import threading, time\n"
        "from sdh_ludusavi.rpc_pool import DaemonThreadPool\n"
        "pool = DaemonThreadPool(max_workers=2, thread_name_prefix='exit-test')\n"
        "started = threading.Event()\n"
        "def task():\n"
        "    started.set()\n"
        "    time.sleep(30)\n"
        "pool.submit(task)\n"
        "started.wait(timeout=5)\n"
        "print('main-thread-done', flush=True)\n"
    )
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env={"PYTHONPATH": "py_modules", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, result.stderr
    assert "main-thread-done" in result.stdout
    assert elapsed < 5, f"process lingered {elapsed:.1f}s after main thread finished"
