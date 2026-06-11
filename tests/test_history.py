from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
import threading

from sdh_ludusavi.history import HistoryManager


class DummyService:
    def __init__(self) -> None:
        self._game_history: dict[str, dict[str, Any]] = {}


def test_history_manager_validation() -> None:
    save_callback = MagicMock()
    svc = DummyService()
    hm = HistoryManager(svc, initial_history={}, save_callback=save_callback)

    hm.record_history("Hades", "backup", "manual_backup", "backed_up")

    history = hm.get_history()
    assert "Hades" in history
    assert history["Hades"]["last_backup"] is not None
    assert history["Hades"]["last_backup"]["status"] == "backed_up"
    assert history["Hades"]["last_operation"]["operation"] == "backup"
    save_callback.assert_called_once()

    hm.record_history("Hades", "restore", "manual_restore", "failed", message="Disk Full")
    assert hm.get_history()["Hades"]["last_failure"]["message"] == "Disk Full"
    assert hm.get_history()["Hades"]["last_operation"]["status"] == "failed"


def test_history_manager_invalid_entries() -> None:
    svc = DummyService()
    hm = HistoryManager(svc, initial_history={}, save_callback=MagicMock())

    hm.record_history("Celeste", "unknown_op", "manual_backup", "backed_up")
    assert "Celeste" not in hm.get_history()


class TrackingRLock:
    """RLock wrapper that records acquisition depth for lock-coverage tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.depth = 0
        self.acquisitions = 0

    def __enter__(self) -> "TrackingRLock":
        self._lock.acquire()
        self.depth += 1
        self.acquisitions += 1
        return self

    def __exit__(self, *exc: object) -> None:
        self.depth -= 1
        self._lock.release()


def test_get_history_returns_isolated_copy() -> None:
    hm = HistoryManager(DummyService(), initial_history={}, save_callback=MagicMock())
    hm.record_history("Hades", "backup", "manual_backup", "backed_up")
    assert hm.get_history() is not hm._game_history
    snapshot = hm.get_history()
    snapshot["Hades"]["last_backup"] = None
    snapshot["Other"] = {}
    assert hm.get_history()["Hades"]["last_backup"]["status"] == "backed_up"
    assert "Other" not in hm.get_history()


def test_history_methods_acquire_lock() -> None:
    hm = HistoryManager(DummyService(), initial_history={}, save_callback=MagicMock())
    hm._lock = TrackingRLock()
    hm.record_history("Hades", "backup", "manual_backup", "backed_up")
    hm.get_history()
    assert hm._lock.acquisitions >= 2


def test_record_history_releases_lock_before_save_callback() -> None:
    hm = HistoryManager(DummyService(), initial_history={}, save_callback=MagicMock())
    tracker = TrackingRLock()
    hm._lock = tracker

    def save_cb() -> None:
        assert tracker.depth == 0
        h = hm.get_history()
        assert h["Hades"]["last_operation"]["status"] == "backed_up"

    hm._save_callback = save_cb
    hm.record_history("Hades", "backup", "manual_backup", "backed_up")
    assert tracker.acquisitions > 0
