from __future__ import annotations

import asyncio
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

from main import _run_blocking  # noqa: E402


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
