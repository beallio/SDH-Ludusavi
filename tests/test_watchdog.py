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
