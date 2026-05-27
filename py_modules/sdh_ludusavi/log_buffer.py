from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

LOGGER = logging.getLogger("sdh_ludusavi.service.log_buffer")


@dataclass
class LogEntry:
    """A single diagnostic log entry held in the backend ring buffer."""

    level: str
    message: str
    timestamp: str
    operation: str | None = None
    game_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DeckyLogHandler(logging.Handler):
    """A logging handler that routes standard Python logs into the plugin's

    internal DiagnosticLogBuffer and the Decky Loader logger.
    """

    def __init__(self, log_buffer: DiagnosticLogBuffer) -> None:
        super().__init__()
        self._log_buffer = log_buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            log_modal_map = {
                "warning": "warning",
                "error": "error",
                "critical": "error",
                "debug": "debug",
                "info": "info",
            }
            level = log_modal_map.get(level, "info")

            # Push to DiagnosticLogBuffer
            self._log_buffer.push_log_record(level, msg)

            # Also push to decky.logger if available
            _decky_log_fallback(level, msg)
        # Intentionally broad: prevent logging handler failures from crashing the program
        except Exception:
            self.handleError(record)


def _decky_log_fallback(level: str, message: str) -> None:
    try:
        import decky

        logger = getattr(decky, "logger", None)
        if logger:
            logger_level_map = {
                "warning": getattr(logger, "warning", logger.info),
                "error": getattr(logger, "error", getattr(logger, "exception", logger.info)),
                "debug": getattr(logger, "info", None),
                "info": getattr(logger, "info", None),
            }
            logger_level = logger_level_map.get(level, getattr(logger, "info", None))
            if logger_level:
                logger_level(f"[DEBUG] {message}" if level == "debug" else message)
    except ImportError:
        pass


class DiagnosticLogBuffer:
    """Diagnostic log buffer managing the memory ring buffer of log entries

    and configuring the custom standard Python logging handler.
    """

    def __init__(self, service: Any, log_limit: int = 100) -> None:
        self._service = service
        self._logs: deque[LogEntry] = deque(maxlen=log_limit)

    def log(
        self,
        level: str,
        message: str,
        operation: str | None = None,
        game_name: str | None = None,
    ) -> None:
        """Add an entry to the internal diagnostic log buffer and decky logs."""
        log_msg = f"{operation or 'frontend'}: {message}"
        if game_name:
            log_msg = f"[{game_name}] {log_msg}"

        _decky_log_fallback(level, log_msg)
        self.push_log_record(level, message, operation, game_name)

    def push_log_record(
        self,
        level: str,
        message: str,
        operation: str | None = None,
        game_name: str | None = None,
    ) -> None:
        """Push a record into the deque ring buffer."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._logs.append(LogEntry(level, message, timestamp, operation, game_name))

    def get_recent(self) -> list[dict[str, object]]:
        """Return the most recent log entries in chronological order."""
        return [entry.to_dict() for entry in self._logs]

    def setup_logging(self) -> None:
        """Configure the standard logging library to route through our handler."""
        handler = DeckyLogHandler(self)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))

        for name in ("sdh_ludusavi", "pyludusavi"):
            logger = logging.getLogger(name)
            logger.setLevel(logging.DEBUG)
            for h in logger.handlers[:]:
                logger.removeHandler(h)

            logger.addHandler(handler)
            logger.propagate = not bool(os.environ.get("DECKY_VERSION"))
