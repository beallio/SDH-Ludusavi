from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

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
