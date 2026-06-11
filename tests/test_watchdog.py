from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch

from sdh_ludusavi.watchdog import ProcessWatchdog


class DummyService:
    def __init__(self) -> None:
        self._paused_pids: dict[int, float] = {}
        self._paused_pids_lock = threading.Lock()
        self._watchdog_active = False
        self._watchdog_thread = None
        self._watchdog_stop = threading.Event()


def test_process_watchdog_pause_resume() -> None:
    log_mock = MagicMock()
    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[4567]),
    ):
        is_op_running = MagicMock(return_value=False)
        svc = DummyService()
        wd = ProcessWatchdog(svc, log_callback=log_mock, is_operation_running=is_op_running)

        # Pause pid 4567
        res = wd.pause(4567)
        assert res["status"] == "paused"
        assert res["pid"] == 4567
        mock_kill.assert_called_with(4567, 19)

        # Resume pid 4567
        res_res = wd.resume(4567)
        assert res_res["status"] == "resumed"
        mock_kill.assert_called_with(4567, 18)

        wd.stop()


def test_process_watchdog_auto_resume_stuck_pids() -> None:
    log_mock = MagicMock()
    is_op_running = MagicMock(return_value=False)

    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[9999]),
    ):
        svc = DummyService()
        wd = ProcessWatchdog(svc, log_callback=log_mock, is_operation_running=is_op_running)

        with wd._paused_pids_lock:
            wd._paused_pids[9999] = time.time() - 20.0

        wd._check_and_resume_stuck_pids()

        mock_kill.assert_called_with(9999, 18)
        assert 9999 not in wd._paused_pids
        wd.stop()


def test_process_watchdog_failed_resume() -> None:
    log_mock = MagicMock()
    is_op_running = MagicMock(return_value=False)
    with (
        patch("sdh_ludusavi.watchdog._send_signal_tree", return_value=False),
    ):
        svc = DummyService()
        wd = ProcessWatchdog(svc, log_callback=log_mock, is_operation_running=is_op_running)

        with wd._paused_pids_lock:
            wd._paused_pids[7777] = time.time()

        res = wd.resume(7777)
        assert res["status"] == "failed"
        assert res["pid"] == 7777
        assert "Unable to resume" in res["message"]

        with wd._paused_pids_lock:
            assert 7777 in wd._paused_pids

        wd.stop()


def test_watchdog_defers_resume_while_operation_running_within_ceiling() -> None:
    """Paused 60s with an operation running: must NOT be resumed (pre-existing
    deferral behavior, now bounded)."""
    log_mock = MagicMock()
    is_op_running = MagicMock(return_value=True)

    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[8888]),
    ):
        svc = DummyService()
        wd = ProcessWatchdog(svc, log_callback=log_mock, is_operation_running=is_op_running)

        with wd._paused_pids_lock:
            wd._paused_pids[8888] = time.time() - 60.0

        wd._check_and_resume_stuck_pids()

        mock_kill.assert_not_called()
        assert 8888 in wd._paused_pids
        wd.stop()


def test_watchdog_resumes_past_absolute_ceiling_even_when_operation_running() -> None:
    """Paused longer than WATCHDOG_ABSOLUTE_RESUME_SECONDS with an operation
    running: MUST be resumed, and the warning log must mention the absolute
    ceiling."""
    from sdh_ludusavi.constants import WATCHDOG_ABSOLUTE_RESUME_SECONDS

    log_mock = MagicMock()
    is_op_running = MagicMock(return_value=True)

    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[7777]),
    ):
        svc = DummyService()
        wd = ProcessWatchdog(svc, log_callback=log_mock, is_operation_running=is_op_running)

        with wd._paused_pids_lock:
            wd._paused_pids[7777] = time.time() - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1)

        wd._check_and_resume_stuck_pids()

        mock_kill.assert_called_with(7777, 18)
        assert 7777 not in wd._paused_pids

        # Check that the warning log mentions the absolute ceiling
        called_with_absolute = False
        for call in log_mock.call_args_list:
            if call[0][0] == "warning" and "absolute ceiling" in call[0][1]:
                called_with_absolute = True
                break
        assert called_with_absolute, "Warning log must mention the absolute ceiling"

        wd.stop()
