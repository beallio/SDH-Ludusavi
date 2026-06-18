from __future__ import annotations
from sdh_ludusavi.persistence import JsonSettingsStore

import logging
from collections import deque
from unittest.mock import patch

from sdh_ludusavi.log_buffer import DiagnosticLogBuffer, DeckyLogHandler, LogEntry


class DummyService:
    def __init__(self, limit: int = 100) -> None:
        self._logs: deque[LogEntry] = deque(maxlen=limit)


def test_diagnostic_log_buffer_push_get() -> None:
    svc = DummyService(limit=5)
    buf = DiagnosticLogBuffer(svc)
    buf.push_log_record("info", "Initialized", "init", "Hades")
    buf.push_log_record("error", "Failed backup", "backup", "Hades")

    recent = buf.get_recent()
    assert len(recent) == 2
    assert recent[0]["level"] == "info"
    assert recent[0]["operation"] == "init"
    assert recent[1]["level"] == "error"


def test_decky_log_handler_emit() -> None:
    svc = DummyService(limit=5)
    buf = DiagnosticLogBuffer(svc)
    handler = DeckyLogHandler(buf)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger = logging.getLogger("test_srp_logger")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    with patch("sdh_ludusavi.log_buffer._decky_log_fallback") as mock_decky_log:
        logger.info("Hello SRP Log Handler")
        mock_decky_log.assert_called_once_with("info", "test_srp_logger: Hello SRP Log Handler")

    recent = buf.get_recent()
    assert len(recent) == 1
    assert "Hello SRP Log Handler" in recent[0]["message"]


def test_setup_logging_removes_old_handlers(tmp_path) -> None:
    from unittest.mock import MagicMock
    from sdh_ludusavi.service import SDHLudusaviService

    mock_adapter = MagicMock()
    mock_adapter.get_versions.return_value = {"ludusavi": "0.31.0"}
    mock_adapter.get_diagnostics.return_value = {"version": "0.31.0"}

    # Create first service
    svc1 = SDHLudusaviService(
        adapter=mock_adapter,
        settings_store=JsonSettingsStore(tmp_path / "settings1.json"),
        cache_path=tmp_path / "cache1.json",
    )
    # Create second service
    svc2 = SDHLudusaviService(
        adapter=mock_adapter,
        settings_store=JsonSettingsStore(tmp_path / "settings2.json"),
        cache_path=tmp_path / "cache2.json",
    )

    # Now get active handlers for "sdh_ludusavi" logger
    logger = logging.getLogger("sdh_ludusavi")
    handlers = [h for h in logger.handlers if isinstance(h, DeckyLogHandler)]
    # There should only be 1 handler, belonging to the newest service (svc2)
    assert len(handlers) == 1

    # Verify records logged to "sdh_ludusavi" go to svc2's log buffer
    logger.info("Test routing")

    recent1 = svc1.get_recent_logs()
    recent2 = svc2.get_recent_logs()

    # Check that it did NOT go to svc1
    assert not any("Test routing" in entry["message"] for entry in recent1)
    # Check that it DID go to svc2
    assert any("Test routing" in entry["message"] for entry in recent2)


def test_decky_log_fallback_debug_routes_to_logger_debug(monkeypatch, tmp_path):
    import sys
    from tests.test_main import fake_decky_module
    from sdh_ludusavi.log_buffer import _decky_log_fallback

    decky, logger = fake_decky_module(tmp_path)
    monkeypatch.setitem(sys.modules, "decky", decky)
    _decky_log_fallback("debug", "refresh: hello")

    assert logger.debugs == ["refresh: hello"]
    assert logger.infos == []
    assert all("[DEBUG]" not in m for m in logger.debugs)


def test_setup_logging_level(monkeypatch, tmp_path):
    import sys
    from tests.test_main import fake_decky_module
    from sdh_ludusavi.log_buffer import DiagnosticLogBuffer

    decky, logger = fake_decky_module(tmp_path)
    monkeypatch.setitem(sys.modules, "decky", decky)

    svc = DummyService()
    buf = DiagnosticLogBuffer(svc)
    buf.setup_logging()

    assert logging.DEBUG in logger.levels
