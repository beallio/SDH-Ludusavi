import sys
import threading
import types
from unittest.mock import MagicMock


# Ensure decky is mocked before importing service or main
mock_decky = types.SimpleNamespace()
mock_decky.logger = MagicMock()
sys.modules["decky"] = mock_decky

from sdh_ludusavi.service import SDHLudusaviService, JsonSettingsStore  # noqa: E402


# Obsolete test_run_blocking_retrieves_exception_on_cancellation removed because _run_blocking is now delegated to asyncio.to_thread.


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
