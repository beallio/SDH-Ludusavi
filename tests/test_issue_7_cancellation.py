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
