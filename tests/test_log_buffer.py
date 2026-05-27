from __future__ import annotations

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
