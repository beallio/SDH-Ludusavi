from __future__ import annotations

import threading
import time
import pytest

from sdh_ludusavi.coordinator import OperationCoordinator, OperationLockedError, OperationState


class DummyService:
    def __init__(self) -> None:
        self._operation = OperationState()
        self._operation_lock = threading.Lock()

    def log(self, level, message, operation=None, game_name=None):
        pass


def test_operation_coordinator_locks() -> None:
    coord = OperationCoordinator()

    def callback():
        time.sleep(0.1)
        return "success"

    assert coord.get_status()["is_running"] is False

    res = coord.run_locked("backup", "Hades", callback)
    assert res == "success"
    assert coord.get_status()["last_result"] == "ok"
    assert coord.get_status()["is_running"] is False


def test_operation_coordinator_lock_contention() -> None:
    coord = OperationCoordinator()
    started = threading.Event()
    block = threading.Event()

    def callback():
        started.set()
        block.wait()
        return "blocked"

    t = threading.Thread(target=coord.run_locked, args=("backup", "Hades", callback))
    t.start()

    started.wait()

    assert coord.get_status()["is_running"] is True
    assert coord.get_status()["name"] == "backup"

    with pytest.raises(OperationLockedError):
        coord.run_locked("restore", "Hades", lambda: None)

    block.set()
    t.join()
