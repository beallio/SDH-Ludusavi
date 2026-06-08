from __future__ import annotations

import inspect
import time
import threading
from unittest.mock import patch

from sdh_ludusavi.syncthing.watcher import SyncthingWatch, SyncthingWatchManager
from sdh_ludusavi.syncthing.config import SyncthingNotConfiguredError
from sdh_ludusavi.syncthing import (
    FolderSelection,
    FolderRuntime,
    LocalActivity,
    ConnectionRates,
)


def test_watch_tick_owns_runtime_state() -> None:
    assert list(inspect.signature(SyncthingWatch._tick).parameters) == ["self", "now"]


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_watch_manager(mock_resolve_path, mock_resolve_creds) -> None:
    # Setup mock SyncthingAPI and credentials
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_folder = FolderSelection(
        folder_id="test-folder", label="Test Folder", path="/home/deck/Sync", shared_device_ids=()
    )
    mock_resolve_path.return_value = mock_folder

    manager = SyncthingWatchManager()

    # Mock get_initial_folder_state_and_runtime, get_event_cursor, get_connection_totals
    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_totals") as mock_totals,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_cursor.return_value = 100
        mock_totals.return_value = (0, 0)
        mock_status.return_value = {"state": "idle", "sequence": 5}
        mock_events.return_value = []

        # Start watch
        res = manager.start_watch("pre_game", "Hades", "1145300", "/home/deck/Sync/Hades")
        assert res["status"] == "watching"
        assert res["folder_id"] == "test-folder"
        watch_id = res["watch_id"]

        # Poll watch
        time.sleep(0.1)  # Let the daemon thread run one iteration
        poll_res = manager.poll_watch(watch_id)
        assert poll_res["status"] == "activity"
        assert poll_res["watch_id"] == watch_id
        assert set(poll_res["sample"]) == {
            "status",
            "folder_state",
            "update_in_progress",
            "settled",
            "downloading",
            "uploading",
            "timestamp_unix",
        }

        # Stop watch
        stop_res = manager.stop_watch(watch_id)
        assert stop_res["status"] == "stopped"

        # Poll stopped watch
        poll_stopped = manager.poll_watch(watch_id)
        assert poll_stopped["status"] == "stopped"


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
def test_watch_manager_silently_classifies_missing_syncthing_config(mock_resolve_creds) -> None:
    mock_resolve_creds.side_effect = SyncthingNotConfiguredError(
        "No Syncthing configuration found."
    )

    result = SyncthingWatchManager().start_watch(
        "post_game",
        "Hades",
        "1145300",
        "/home/deck/ludusavi-backup",
    )

    assert result == {
        "status": "skipped",
        "reason": "not_configured",
        "message": "No Syncthing configuration found.",
    }


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
def test_watch_manager_classifies_configured_but_unreachable_api(mock_resolve_creds) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)

    with patch(
        "sdh_ludusavi.syncthing.watcher.resolve_folder_by_path",
        side_effect=RuntimeError("Cannot reach Syncthing API"),
    ):
        result = SyncthingWatchManager().start_watch(
            "post_game",
            "Hades",
            "1145300",
            "/home/deck/ludusavi-backup",
        )

    assert result["status"] == "skipped"
    assert result["reason"] == "api_unavailable"


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_watch_start_returns_bounded_detection_grace(mock_resolve_path, mock_resolve_creds) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_resolve_path.return_value = FolderSelection(
        folder_id="test-folder",
        label="Test Folder",
        path="/home/deck/Sync",
        fs_watcher_enabled=True,
        fs_watcher_delay_seconds=45,
        rescan_interval_seconds=3600,
    )

    manager = SyncthingWatchManager()
    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_totals") as mock_totals,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_cursor.return_value = 100
        mock_totals.return_value = (0, 0)
        mock_status.return_value = {"state": "idle", "sequence": 5}
        mock_events.return_value = []

        result = manager.start_watch(
            "post_game",
            "Hades",
            "1145300",
            "/home/deck/ludusavi-backup",
        )

        assert result["status"] == "watching"
        assert result["detection_grace_ms"] == 65_000
        manager.stop_watch(result["watch_id"])


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_watch_start_clamps_rescan_detection_grace(mock_resolve_path, mock_resolve_creds) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_resolve_path.return_value = FolderSelection(
        folder_id="test-folder",
        label="Test Folder",
        path="/home/deck/Sync",
        fs_watcher_enabled=False,
        fs_watcher_delay_seconds=10,
        rescan_interval_seconds=300,
    )

    manager = SyncthingWatchManager()
    with patch.object(SyncthingWatch, "start"):
        result = manager.start_watch(
            "post_game",
            "Hades",
            "1145300",
            "/home/deck/ludusavi-backup",
        )

    assert result["status"] == "watching"
    assert result["detection_grace_ms"] == 120_000
    manager.stop_watch(result["watch_id"])


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_watcher_sample_timing_and_failures(mock_resolve_path, mock_resolve_creds) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_folder = FolderSelection(
        folder_id="test-folder", label="Test Folder", path="/home/deck/Sync", shared_device_ids=()
    )
    mock_resolve_path.return_value = mock_folder

    manager = SyncthingWatchManager()

    cursor_called = threading.Event()
    cursor_proceed = threading.Event()
    baseline_checked = {}

    def mock_get_event_cursor(api):
        with manager.lock:
            for w in manager.watches.values():
                baseline_checked["sample"] = w.latest_sample.copy()
        cursor_called.set()
        cursor_proceed.wait()
        return 100

    init_failed = threading.Event()

    def mock_get_event_cursor_fail(api):
        init_failed.set()
        raise RuntimeError("cursor failed")

    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor", side_effect=mock_get_event_cursor),
        patch("sdh_ludusavi.syncthing.watcher.get_connection_totals") as mock_totals,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_totals.return_value = (0, 0)
        mock_status.return_value = {"state": "idle", "sequence": 5}
        mock_events.return_value = []

        res = manager.start_watch("pre_game", "Hades", "1145300", "/home/deck/Sync/Hades")
        assert res["status"] == "watching"
        watch_id = res["watch_id"]

        assert cursor_called.wait(timeout=2.0)
        # Verify no populated sample is exposed before cursor initialization completes
        assert baseline_checked["sample"] == {}

        cursor_proceed.set()

        # Poll deterministically with a bounded deadline instead of relying on fixed sleep timing
        start_time = time.time()
        poll_res = None
        while time.time() - start_time < 2.0:
            poll_res = manager.poll_watch(watch_id)
            if poll_res and poll_res.get("status") == "activity" and poll_res.get("sample"):
                break
            time.sleep(0.01)

        assert poll_res is not None
        assert poll_res["status"] == "activity"
        assert "sample" in poll_res
        assert poll_res["sample"]["folder_state"] == "idle"

        manager.stop_watch(watch_id)

    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch(
            "sdh_ludusavi.syncthing.watcher.get_event_cursor",
            side_effect=mock_get_event_cursor_fail,
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_connection_totals") as mock_totals,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_totals.return_value = (0, 0)
        mock_status.return_value = {"state": "idle", "sequence": 5}
        mock_events.return_value = []

        res = manager.start_watch("pre_game", "Hades", "1145300", "/home/deck/Sync/Hades")
        assert res["status"] == "watching"
        watch_id = res["watch_id"]

        assert init_failed.wait(timeout=2.0)
        time.sleep(0.1)
        poll_res = manager.poll_watch(watch_id)
        assert poll_res["status"] == "failed"
        assert poll_res["reason"] == "watch_initialization_failed"
        assert "cursor failed" in poll_res["message"]

        manager.stop_watch(watch_id)


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_event_processing_before_sample_serialization(
    mock_resolve_path, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_folder = FolderSelection(
        folder_id="test-folder", label="Test Folder", path="/home/deck/Sync", shared_device_ids=()
    )
    mock_resolve_path.return_value = mock_folder

    manager = SyncthingWatchManager()

    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_totals") as mock_totals,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_cursor.return_value = 100
        mock_totals.return_value = (0, 0)
        mock_status.return_value = {"state": "idle", "sequence": 5}
        mock_events.return_value = [
            {
                "id": 101,
                "type": "StateChanged",
                "data": {
                    "folder": "test-folder",
                    "to": "syncing",
                },
            }
        ]

        res = manager.start_watch("pre_game", "Hades", "1145300", "/home/deck/Sync/Hades")
        assert res["status"] == "watching"
        watch_id = res["watch_id"]

        watch = manager.watches[watch_id]
        watch.stop_event.set()
        watch.thread.join()
        watch.cursor = 100
        watch.folder_state = "idle"
        watch.runtime = FolderRuntime(sequence=5)
        watch.remote_progress = {}
        watch.local_activity = LocalActivity(active_items={})
        watch.rates = ConnectionRates(0.0, 0.0)
        watch._tick(time.monotonic())

        assert watch.latest_sample["sample"]["folder_state"] == "syncing"


def test_poll_watch_returns_copied_dict() -> None:
    watch = SyncthingWatch(
        "123",
        "pre_game",
        "Hades",
        "1145300",
        FolderSelection(folder_id="test", label="test", path="/path", shared_device_ids=()),
        None,
    )
    watch.latest_sample = {"status": "activity", "sample": {"folder_state": "idle"}}
    manager = SyncthingWatchManager()
    manager.watches["123"] = watch

    polled = manager.poll_watch("123")
    polled["status"] = "mutated"
    polled["sample"]["folder_state"] = "mutated"

    assert watch.latest_sample["status"] == "activity"
    assert watch.latest_sample["sample"]["folder_state"] == "idle"


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_strict_folder_status_initialization_failure(mock_resolve_path, mock_resolve_creds) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_folder = FolderSelection(
        folder_id="test-folder", label="Test Folder", path="/home/deck/Sync", shared_device_ids=()
    )
    mock_resolve_path.return_value = mock_folder

    manager = SyncthingWatchManager()
    init_failed = threading.Event()

    def mock_get_initial_folder_state_and_runtime_fail(api, folder_id, strict=False):
        init_failed.set()
        raise RuntimeError("initial status failed")

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime",
            side_effect=mock_get_initial_folder_state_and_runtime_fail,
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_totals") as mock_totals,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_cursor.return_value = 100
        mock_totals.return_value = (0, 0)
        mock_status.return_value = {"state": "idle", "sequence": 5}
        mock_events.return_value = []

        res = manager.start_watch("pre_game", "Hades", "1145300", "/home/deck/Sync/Hades")
        assert res["status"] == "watching"
        watch_id = res["watch_id"]

        assert init_failed.wait(timeout=2.0)
        time.sleep(0.1)
        poll_res = manager.poll_watch(watch_id)
        assert poll_res["status"] == "failed"
        assert poll_res["reason"] == "watch_initialization_failed"
        assert "initial status failed" in poll_res["message"]

        manager.stop_watch(watch_id)
