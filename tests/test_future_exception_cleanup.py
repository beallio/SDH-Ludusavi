import asyncio
import sys
import threading
import time
import types
from unittest.mock import MagicMock

import pytest

# Ensure decky is mocked before importing service or main
mock_decky = types.SimpleNamespace()
mock_decky.logger = MagicMock()
sys.modules["decky"] = mock_decky

from main import _run_blocking  # noqa: E402
from sdh_ludusavi.service import SDHLudusaviService, JsonSettingsStore  # noqa: E402


@pytest.mark.asyncio
async def test_run_blocking_retrieves_exception_on_cancellation():
    loop = asyncio.get_running_loop()
    future_instances = []
    original_create_future = loop.create_future

    def mock_create_future():
        nonlocal future_instances
        fut = original_create_future()
        future_instances.append(fut)
        return fut

    loop.create_future = mock_create_future

    def raising_task():
        time.sleep(0.1)
        raise ValueError("Simulated background error")

    task = asyncio.create_task(_run_blocking(raising_task))
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Wait for the background thread to finish and trigger the completion signal
    await asyncio.sleep(0.15)

    # Restore create_future
    loop.create_future = original_create_future

    # Find the specific future used for the raising_task by accessing the private attribute _exception
    fut = None
    for f in future_instances:
        if (
            hasattr(f, "_exception")
            and isinstance(f._exception, ValueError)
            and str(f._exception) == "Simulated background error"
        ):
            fut = f
            break

    assert fut is not None
    assert fut.done()
    # If the done callback hasn't run to consume the exception, _log_traceback will be True.
    # Our fix should set it to False by calling f.exception() or f.result() inside the callback.
    assert hasattr(fut, "_log_traceback")
    assert fut._log_traceback is False


def test_diagnostics_logging_is_thread_safe_and_runs_once(tmp_path):
    called_count = 0

    def mock_diagnostics_logger(adapter):
        nonlocal called_count
        called_count += 1
        service._diagnostics_logged = True

    service = SDHLudusaviService(
        adapter=MagicMock(),
        settings_store=JsonSettingsStore(tmp_path / "mock_settings.json"),
        cache_path=tmp_path / "mock_cache.json",
    )
    service._log_ludusavi_diagnostics = mock_diagnostics_logger

    # Simulate concurrent calls to _ludusavi()
    threads = []

    def call_ludusavi():
        service._ludusavi()

    for _ in range(10):
        t = threading.Thread(target=call_ludusavi)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # The diagnostics logging should run exactly once
    assert called_count == 1
