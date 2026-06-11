from __future__ import annotations

import asyncio
import sys
import time
import types
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

# Mock decky before importing main
mock_decky = types.SimpleNamespace()
mock_decky.logger = MagicMock()
sys.modules["decky"] = mock_decky

from main import _run_blocking  # noqa: E402


@pytest.fixture()
def pool() -> Iterator[ThreadPoolExecutor]:
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-rpc")
    yield executor
    executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_run_blocking_success(pool: ThreadPoolExecutor) -> None:
    result = await _run_blocking(pool, lambda: "success")

    assert result == "success"


@pytest.mark.asyncio
async def test_run_blocking_cancellation(pool: ThreadPoolExecutor) -> None:
    def slow_task() -> str:
        time.sleep(0.3)
        return "done"

    task = asyncio.create_task(_run_blocking(pool, slow_task))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_blocking_cancellation_logs_warning(pool: ThreadPoolExecutor) -> None:
    mock_decky.logger.warning.reset_mock()

    def slow_task() -> str:
        time.sleep(0.3)
        return "done"

    task = asyncio.create_task(_run_blocking(pool, slow_task))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    mock_decky.logger.warning.assert_called_once_with(
        "SDH-ludusavi operation was cancelled while worker may still be running"
    )


@pytest.mark.asyncio
async def test_run_blocking_worker_exception_propagates(pool: ThreadPoolExecutor) -> None:
    def failing_task() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await _run_blocking(pool, failing_task)


@pytest.mark.asyncio
async def test_run_blocking_worker_exception_after_cancellation_is_not_loop_error(
    pool: ThreadPoolExecutor,
) -> None:
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()

    def capture_loop_error(_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        loop_errors.append(context)

    def slow_failing_task() -> None:
        time.sleep(0.05)
        raise ValueError("late boom")

    loop.set_exception_handler(capture_loop_error)
    try:
        task = asyncio.create_task(_run_blocking(pool, slow_failing_task))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.1)
    finally:
        loop.set_exception_handler(previous_handler)

    assert loop_errors == []
