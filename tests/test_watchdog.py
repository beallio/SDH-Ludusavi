from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from sdh_ludusavi.watchdog import ProcessWatchdog, _PauseLease


def mock_identity() -> object:
    from sdh_ludusavi.watchdog import _ProcessIdentity

    return _ProcessIdentity(12345, 1000)


def test_process_watchdog_pause_resume() -> None:
    log_mock = MagicMock()
    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[4567]),
        patch("sdh_ludusavi.watchdog.os.geteuid", return_value=1000),
        patch("sdh_ludusavi.watchdog._read_process_identity", return_value=mock_identity()),
    ):
        wd = ProcessWatchdog(log_callback=log_mock)

        # Pause pid 4567
        res = wd.pause(4567)
        assert res["status"] == "paused"
        assert res["pid"] == 4567
        assert "lease_id" in res
        lease_id = res["lease_id"]
        mock_kill.assert_called_with(4567, 19)

        # Renew pid 4567
        res_renew = wd.renew_pause(4567, lease_id)
        assert res_renew["status"] == "renewed"
        assert res_renew["pid"] == 4567

        # Resume pid 4567
        res_res = wd.resume(4567)
        assert res_res["status"] == "resumed"
        mock_kill.assert_called_with(4567, 18)

        wd.stop()


def test_process_watchdog_auto_resume_expired_lease() -> None:
    log_mock = MagicMock()

    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[9999]),
        patch("sdh_ludusavi.watchdog.os.geteuid", return_value=1000),
        patch("sdh_ludusavi.watchdog._read_process_identity", return_value=mock_identity()),
    ):
        wd = ProcessWatchdog(log_callback=log_mock)

        with wd._paused_pids_lock:
            wd._paused_pids[9999] = _PauseLease(
                identity=mock_identity(),
                paused_at=time.monotonic() - 60.0,
                lease_id="test",
                lease_deadline=time.monotonic() - 10.0,
            )

        wd._check_and_resume_stuck_pids()

        mock_kill.assert_called_with(9999, 18)
        assert 9999 not in wd._paused_pids
        wd.stop()


def test_process_watchdog_failed_resume() -> None:
    log_mock = MagicMock()
    with (
        patch("sdh_ludusavi.watchdog._send_signal_tree", return_value=False),
        patch("sdh_ludusavi.watchdog.os.geteuid", return_value=1000),
        patch("sdh_ludusavi.watchdog._read_process_identity", return_value=mock_identity()),
    ):
        wd = ProcessWatchdog(log_callback=log_mock)

        with wd._paused_pids_lock:
            wd._paused_pids[7777] = _PauseLease(
                identity=mock_identity(),
                paused_at=time.monotonic(),
                lease_id="test",
                lease_deadline=time.monotonic() + 30.0,
            )

        res = wd.resume(7777)
        assert res["status"] == "failed"
        assert res["pid"] == 7777
        assert "Unable to resume" in res["message"]

        with wd._paused_pids_lock:
            assert 7777 in wd._paused_pids

        wd.stop()


def test_watchdog_defers_resume_while_lease_valid() -> None:
    """Paused with a valid lease must NOT be resumed."""
    log_mock = MagicMock()

    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[8888]),
        patch("sdh_ludusavi.watchdog.os.geteuid", return_value=1000),
        patch("sdh_ludusavi.watchdog._read_process_identity", return_value=mock_identity()),
    ):
        wd = ProcessWatchdog(log_callback=log_mock)

        with wd._paused_pids_lock:
            wd._paused_pids[8888] = _PauseLease(
                identity=mock_identity(),
                paused_at=time.monotonic(),
                lease_id="test",
                lease_deadline=time.monotonic() + 30.0,
            )

        wd._check_and_resume_stuck_pids()

        mock_kill.assert_not_called()
        assert 8888 in wd._paused_pids
        wd.stop()


def test_watchdog_resumes_past_absolute_ceiling_even_when_lease_valid() -> None:
    """Paused longer than WATCHDOG_ABSOLUTE_RESUME_SECONDS with an operation
    running (even if lease renewed): MUST be resumed, and the warning log must mention the absolute
    ceiling."""
    from sdh_ludusavi.constants import WATCHDOG_ABSOLUTE_RESUME_SECONDS

    log_mock = MagicMock()

    with (
        patch("sdh_ludusavi.watchdog.os.kill") as mock_kill,
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[7777]),
        patch("sdh_ludusavi.watchdog.os.geteuid", return_value=1000),
        patch("sdh_ludusavi.watchdog._read_process_identity", return_value=mock_identity()),
    ):
        wd = ProcessWatchdog(log_callback=log_mock)

        with wd._paused_pids_lock:
            wd._paused_pids[7777] = _PauseLease(
                identity=mock_identity(),
                paused_at=time.monotonic() - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1),
                lease_id="test",
                lease_deadline=time.monotonic() + 30.0,  # recently renewed
            )

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


def test_watchdog_identity_mismatch() -> None:
    log_mock = MagicMock()

    with (
        patch("sdh_ludusavi.watchdog.os.geteuid", return_value=1000),
        patch("sdh_ludusavi.watchdog.os.kill"),
        patch("sdh_ludusavi.watchdog._process_tree", return_value=[4567]),
    ):
        wd = ProcessWatchdog(log_callback=log_mock)

        # Identity is none
        with patch("sdh_ludusavi.watchdog._read_process_identity", return_value=None):
            res = wd.pause(4567)
            assert res["status"] == "failed"
            assert "verify process identity" in res["message"]

        # Identity uid mismatch
        from sdh_ludusavi.watchdog import _ProcessIdentity

        with patch(
            "sdh_ludusavi.watchdog._read_process_identity", return_value=_ProcessIdentity(123, 9999)
        ):
            res = wd.pause(4567)
            assert res["status"] == "failed"
            assert "verify process identity" in res["message"]

        # Re-use mismatch
        with patch(
            "sdh_ludusavi.watchdog._read_process_identity", return_value=_ProcessIdentity(123, 1000)
        ):
            res_pause = wd.pause(4567)
            lease_id = res_pause["lease_id"]

        with patch(
            "sdh_ludusavi.watchdog._read_process_identity", return_value=_ProcessIdentity(999, 1000)
        ):
            res = wd.resume(4567)
            assert res["status"] == "failed"
            assert "identity mismatch" in res["message"]

        # Re-use mismatch on renew
        with patch(
            "sdh_ludusavi.watchdog._read_process_identity", return_value=_ProcessIdentity(123, 1000)
        ):
            res_pause = wd.pause(4567)
            lease_id = res_pause["lease_id"]

        with patch(
            "sdh_ludusavi.watchdog._read_process_identity", return_value=_ProcessIdentity(999, 1000)
        ):
            res = wd.renew_pause(4567, lease_id)
            assert res["status"] == "failed"
            assert "identity mismatch" in res["message"]

        # Bad lease ID
        with patch(
            "sdh_ludusavi.watchdog._read_process_identity", return_value=_ProcessIdentity(123, 1000)
        ):
            res_pause = wd.pause(4567)
            res = wd.renew_pause(4567, "wrong")
            assert res["status"] == "failed"
            assert "Lease ID mismatch" in res["message"]

        wd.stop()
