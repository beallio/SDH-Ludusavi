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


def test_operation_coordinator_waits_for_a_released_operation_before_running_callback() -> None:
    coord = OperationCoordinator()
    active_started = threading.Event()
    release_active = threading.Event()
    queued_called = threading.Event()
    queued_results: list[str] = []
    queued_errors: list[BaseException] = []

    def active_callback() -> str:
        active_started.set()
        assert release_active.wait(timeout=0.5)
        return "active"

    def queued_callback() -> str:
        queued_called.set()
        return "queued"

    active = threading.Thread(
        target=coord.run_locked,
        args=("refresh", None, active_callback),
        daemon=True,
    )

    def run_queued() -> None:
        try:
            queued_results.append(
                coord.run_locked(
                    "start_check",
                    "Hades",
                    queued_callback,
                    wait_timeout_seconds=0.2,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted after synchronization.
            queued_errors.append(exc)

    queued = threading.Thread(target=run_queued, daemon=True)
    active.start()
    assert active_started.wait(timeout=0.2)
    queued.start()

    try:
        assert queued.is_alive()
        assert not queued_called.wait(timeout=0.02)
        release_active.set()
        queued.join(timeout=0.5)

        assert not queued.is_alive()
        assert queued_errors == []
        assert queued_results == ["queued"]
        assert queued_called.is_set()
    finally:
        release_active.set()
        active.join(timeout=0.5)
        queued.join(timeout=0.5)


def test_operation_coordinator_timeout_preserves_active_operation_and_skips_queued_callback() -> (
    None
):
    coord = OperationCoordinator()
    active_started = threading.Event()
    release_active = threading.Event()
    queued_calls: list[str] = []

    def active_callback() -> str:
        active_started.set()
        assert release_active.wait(timeout=0.5)
        return "active"

    active = threading.Thread(
        target=coord.run_locked,
        args=("refresh", None, active_callback),
        daemon=True,
    )
    active.start()
    assert active_started.wait(timeout=0.2)

    try:
        with pytest.raises(OperationLockedError):
            coord.run_locked(
                "exit_check",
                "Hades",
                lambda: queued_calls.append("ran"),
                wait_timeout_seconds=0.02,
            )

        assert queued_calls == []
        assert coord.get_status() == {
            "is_running": True,
            "name": "refresh",
            "game_name": None,
            "last_result": None,
            "last_error": None,
        }
    finally:
        release_active.set()
        active.join(timeout=0.5)
