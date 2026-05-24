from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import types
from unittest.mock import MagicMock

import pytest

# Mock decky before importing main
mock_decky = types.SimpleNamespace()
mock_decky.logger = MagicMock()
sys.modules["decky"] = mock_decky

import main as main_module  # noqa: E402
from main import _run_blocking  # noqa: E402


def _is_fd_closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


def _close_if_open(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        return


@pytest.mark.asyncio
async def test_run_blocking_cancellation():
    def slow_task():
        time.sleep(1)
        return "done"

    task = asyncio.create_task(_run_blocking(slow_task))

    # Wait a bit to let the thread start
    await asyncio.sleep(0.05)

    # Cancel the task
    task.cancel()

    # Verify that it raises CancelledError
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_blocking_cancellation_logs_warning():
    mock_decky.logger.warning.reset_mock()

    def slow_task():
        time.sleep(1)
        return "done"

    task = asyncio.create_task(_run_blocking(slow_task))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    mock_decky.logger.warning.assert_called_once_with(
        "SDH-ludusavi operation was cancelled while worker may still be running"
    )


@pytest.mark.asyncio
async def test_run_blocking_worker_exception_propagates():
    def failing_task():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await _run_blocking(failing_task)


@pytest.mark.asyncio
async def test_run_blocking_worker_exception_after_cancellation_is_not_loop_error():
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()

    def capture_loop_error(_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        loop_errors.append(context)

    def slow_failing_task():
        time.sleep(0.05)
        raise ValueError("late boom")

    loop.set_exception_handler(capture_loop_error)
    try:
        task = asyncio.create_task(_run_blocking(slow_failing_task))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.1)
    finally:
        loop.set_exception_handler(previous_handler)

    assert loop_errors == []


def test_run_blocking_closes_pipe_fds_when_add_reader_fails(monkeypatch: pytest.MonkeyPatch):
    loop = asyncio.new_event_loop()
    read_fd, write_fd = os.pipe()

    def fail_add_reader(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("add_reader failed")

    def fake_pipe() -> tuple[int, int]:
        return read_fd, write_fd

    async def scenario() -> None:
        monkeypatch.setattr(main_module.os, "pipe", fake_pipe)
        monkeypatch.setattr(loop, "add_reader", fail_add_reader)
        with pytest.raises(RuntimeError, match="add_reader failed"):
            await _run_blocking(lambda: "done")

    try:
        loop.run_until_complete(scenario())
        assert _is_fd_closed(read_fd)
        assert _is_fd_closed(write_fd)
    finally:
        _close_if_open(read_fd)
        _close_if_open(write_fd)
        loop.close()


def test_run_blocking_closes_pipe_fds_when_thread_start_fails(monkeypatch: pytest.MonkeyPatch):
    loop = asyncio.new_event_loop()
    read_fd, write_fd = os.pipe()

    def fail_thread_start(_self: threading.Thread) -> None:
        raise RuntimeError("thread start failed")

    def fake_pipe() -> tuple[int, int]:
        return read_fd, write_fd

    async def scenario() -> None:
        monkeypatch.setattr(main_module.os, "pipe", fake_pipe)
        monkeypatch.setattr(threading.Thread, "start", fail_thread_start)
        with pytest.raises(RuntimeError, match="thread start failed"):
            await _run_blocking(lambda: "done")

    try:
        loop.run_until_complete(scenario())
        assert _is_fd_closed(read_fd)
        assert _is_fd_closed(write_fd)
    finally:
        _close_if_open(read_fd)
        _close_if_open(write_fd)
        loop.close()


def test_run_blocking_worker_completion_after_loop_close_has_no_thread_exception():
    thread_errors: list[threading.ExceptHookArgs] = []
    previous_hook = threading.excepthook
    loop = asyncio.new_event_loop()

    def capture_thread_error(args: threading.ExceptHookArgs) -> None:
        thread_errors.append(args)

    def slow_task():
        time.sleep(0.05)
        return "done"

    async def scenario() -> None:
        task = asyncio.create_task(_run_blocking(slow_task))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        threading.excepthook = capture_thread_error
        loop.run_until_complete(scenario())
        loop.close()
        time.sleep(0.1)
    finally:
        threading.excepthook = previous_hook
        if not loop.is_closed():
            loop.close()

    assert thread_errors == []


@pytest.mark.asyncio
async def test_run_blocking_success():
    def quick_task():
        return "success"

    result = await _run_blocking(quick_task)
    assert result == "success"
