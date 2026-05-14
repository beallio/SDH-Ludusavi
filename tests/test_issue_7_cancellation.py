from __future__ import annotations

import asyncio
import sys
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
async def test_run_blocking_success():
    def quick_task():
        return "success"

    result = await _run_blocking(quick_task)
    assert result == "success"
