from __future__ import annotations

import inspect
import time
import threading
from unittest.mock import Mock, patch

from sdh_ludusavi.syncthing.watcher import SyncthingWatch, SyncthingWatchManager
from sdh_ludusavi.syncthing.config import SyncthingNotConfiguredError
from sdh_ludusavi.syncthing import (
    FolderSelection,
    FolderRuntime,
    LocalActivity,
    ConnectionSnapshot,
    PeerCompletion,
)


def test_watch_tick_owns_runtime_state() -> None:
    assert list(inspect.signature(SyncthingWatch._tick).parameters) == ["self", "now"]


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_watch_manager(mock_resolve_path, mock_resolve_creds) -> None:
    # Setup mock SyncthingAPI and credentials
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_folder = FolderSelection(
        folder_id="test-folder",
        label="Test Folder",
        path="/home/deck/Sync",
        device_ids=("DEV-A",),
    )
    mock_resolve_path.return_value = mock_folder

    manager = SyncthingWatchManager()

    # Mock initial folder state, event cursor, and relevant-peer connectivity.
    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id") as mock_my_id,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot") as mock_snapshot,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_cursor.return_value = 100
        mock_my_id.return_value = "LOCAL-DEVICE"
        mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-A"}))
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

    with (
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id", return_value="LOCAL-DEVICE"),
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_folder_by_path",
            side_effect=RuntimeError("Cannot reach Syncthing API"),
        ),
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
        device_ids=("DEV-A",),
    )

    manager = SyncthingWatchManager()
    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id") as mock_my_id,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot") as mock_snapshot,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_cursor.return_value = 100
        mock_my_id.return_value = "LOCAL-DEVICE"
        mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-A"}))
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
        device_ids=("DEV-A",),
    )

    manager = SyncthingWatchManager()
    with (
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id", return_value="LOCAL-DEVICE"),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            return_value=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        ),
        patch.object(SyncthingWatch, "start"),
    ):
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
        folder_id="test-folder",
        label="Test Folder",
        path="/home/deck/Sync",
        device_ids=("DEV-A",),
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
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id") as mock_my_id,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot") as mock_snapshot,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_my_id.return_value = "LOCAL-DEVICE"
        mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-A"}))
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
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id") as mock_my_id,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot") as mock_snapshot,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_my_id.return_value = "LOCAL-DEVICE"
        mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-A"}))
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
        folder_id="test-folder",
        label="Test Folder",
        path="/home/deck/Sync",
        device_ids=("DEV-A",),
    )
    mock_resolve_path.return_value = mock_folder

    manager = SyncthingWatchManager()

    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id") as mock_my_id,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot") as mock_snapshot,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_cursor.return_value = 100
        mock_my_id.return_value = "LOCAL-DEVICE"
        mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-A"}))
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
        watch._tick(time.monotonic())

        assert watch.latest_sample["sample"]["folder_state"] == "syncing"


def test_poll_watch_returns_copied_dict() -> None:
    watch = SyncthingWatch(
        "123",
        "pre_game",
        "Hades",
        "1145300",
        FolderSelection(folder_id="test", label="test", path="/path"),
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
        folder_id="test-folder",
        label="Test Folder",
        path="/home/deck/Sync",
        device_ids=("DEV-A",),
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
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id") as mock_my_id,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot") as mock_snapshot,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
    ):
        mock_cursor.return_value = 100
        mock_my_id.return_value = "LOCAL-DEVICE"
        mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-A"}))
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


def _shared_folder(device_ids: tuple[str, ...]) -> FolderSelection:
    return FolderSelection(
        folder_id="test-folder",
        label="Test Folder",
        path="/home/deck/Sync",
        device_ids=device_ids,
    )


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_watch_manager_classifies_unshared_folder(
    mock_resolve_path, mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.return_value = "LOCAL-DEVICE"
    mock_resolve_path.return_value = _shared_folder(())

    result = SyncthingWatchManager().start_watch(
        "post_game", "Hades", "1145300", "/home/deck/Sync/Hades"
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "folder_not_shared"


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
@patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot")
def test_watch_manager_classifies_no_connected_peers(
    mock_snapshot, mock_resolve_path, mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.return_value = "LOCAL-DEVICE"
    mock_resolve_path.return_value = _shared_folder(("DEV-A", "DEV-B"))
    mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset())

    result = SyncthingWatchManager().start_watch(
        "post_game", "Hades", "1145300", "/home/deck/Sync/Hades"
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "no_connected_peers"
    # Device IDs are backend-only and must never leak through RPC.
    assert "DEV-A" not in result["message"]
    assert "DEV-B" not in result["message"]


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
@patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot")
def test_watch_manager_ignores_unrelated_connected_devices(
    mock_snapshot, mock_resolve_path, mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.return_value = "LOCAL-DEVICE"
    mock_resolve_path.return_value = _shared_folder(("DEV-A",))
    mock_snapshot.return_value = ConnectionSnapshot(
        connected_devices=frozenset({"UNRELATED-DEVICE"})
    )

    result = SyncthingWatchManager().start_watch(
        "post_game", "Hades", "1145300", "/home/deck/Sync/Hades"
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "no_connected_peers"


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
@patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot")
def test_watch_manager_starts_with_one_relevant_peer_connected(
    mock_snapshot, mock_resolve_path, mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.return_value = "LOCAL-DEVICE"
    mock_resolve_path.return_value = _shared_folder(("DEV-A", "DEV-B"))
    mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-B"}))

    manager = SyncthingWatchManager()
    with patch.object(SyncthingWatch, "start"):
        result = manager.start_watch("post_game", "Hades", "1145300", "/home/deck/Sync/Hades")

    assert result["status"] == "watching"
    manager.stop_watch(result["watch_id"])


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
@patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot")
def test_watch_manager_classifies_connection_endpoint_failure(
    mock_snapshot, mock_resolve_path, mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.return_value = "LOCAL-DEVICE"
    mock_resolve_path.return_value = _shared_folder(("DEV-A",))
    mock_snapshot.side_effect = RuntimeError("Cannot reach Syncthing API")

    result = SyncthingWatchManager().start_watch(
        "post_game", "Hades", "1145300", "/home/deck/Sync/Hades"
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "api_unavailable"


def _stopped_watch_for_tick(device_ids: tuple[str, ...]) -> SyncthingWatch:
    watch = SyncthingWatch(
        "watch-1",
        "post_game",
        "Hades",
        "1145300",
        _shared_folder(device_ids),
        None,
        initial_snapshot=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
    )
    watch.cursor = 100
    watch.folder_state = "idle"
    watch.runtime = FolderRuntime(sequence=5)
    return watch


def test_post_game_initialization_captures_peer_baselines_before_second_status_poll() -> None:
    watch = _stopped_watch_for_tick(("DEV-A", "DEV-B"))
    watch.connected_devices = frozenset({"DEV-A", "DEV-B"})
    calls: list[str] = []

    def initial_folder_state(api, folder_id, strict=False):
        calls.append("initial-folder")
        return "idle", FolderRuntime(sequence=5)

    def event_cursor(api):
        calls.append("event-cursor")
        return 100

    def completion(api, folder, device_id, now):
        calls.append(f"completion-{device_id}")
        return PeerCompletion(device_id, 100.0, 0, 0, 0, now)

    def folder_status(api, folder_id):
        calls.append("second-folder")
        return {"state": "idle", "sequence": 6}

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime",
            side_effect=initial_folder_state,
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor", side_effect=event_cursor),
        patch("sdh_ludusavi.syncthing.watcher.get_peer_completion", side_effect=completion),
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status", side_effect=folder_status),
    ):
        watch._initialize()

    assert calls[:2] == ["initial-folder", "event-cursor"]
    assert set(calls[2:4]) == {"completion-DEV-A", "completion-DEV-B"}
    assert calls[4] == "second-folder"
    assert set(watch.peer_completions) == {"DEV-A", "DEV-B"}
    # A baseline captured before the second sequence observation cannot acknowledge it.
    assert watch.local_activity.outbound_index_observed_monotonic > 0


def test_pre_game_initialization_never_requests_peer_completion() -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))
    watch.phase = "pre_game"

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime",
            return_value=("idle", FolderRuntime(sequence=5)),
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor", return_value=100),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_peer_completion",
            side_effect=AssertionError("pre-game must not query completion"),
        ) as completion,
    ):
        watch._initialize()

    completion.assert_not_called()
    assert watch.peer_completions == {}


def test_post_game_completion_initialization_failure_is_sanitized(caplog) -> None:
    watch = _stopped_watch_for_tick(("SECRET-REMOTE-ID",))
    watch.connected_devices = frozenset({"SECRET-REMOTE-ID"})

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime",
            return_value=("idle", FolderRuntime(sequence=5)),
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor", return_value=100),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_peer_completion",
            side_effect=RuntimeError("raw completion body for SECRET-REMOTE-ID"),
        ),
        caplog.at_level("DEBUG", logger="sdh_ludusavi.syncthing.watcher"),
    ):
        watch._run()

    assert watch.latest_sample == {
        "status": "failed",
        "reason": "watch_initialization_failed",
        "message": "Syncthing peer completion initialization failed.",
    }
    assert "SECRET-REMOTE-ID" not in caplog.text
    assert "raw completion body" not in caplog.text


def test_post_game_peer_completion_events_gate_settlement_and_ignore_unscoped_traffic() -> None:
    watch = _stopped_watch_for_tick(("DEV-A", "DEV-B"))
    watch.connected_devices = frozenset({"DEV-A", "DEV-B"})
    watch.local_activity = LocalActivity(active_items={})

    event_batches = [
        [
            {
                "id": 101,
                "type": "LocalIndexUpdated",
                "data": {"folder": "test-folder", "sequence": 6},
            },
            {
                "id": 102,
                "type": "FolderCompletion",
                "data": {
                    "folder": "test-folder",
                    "device": "DEV-A",
                    "completion": 93.56119493792454,
                    "needBytes": 8_942_011,
                    "needItems": 32,
                    "needDeletes": 19,
                },
            },
            {
                "id": 103,
                "type": "FolderCompletion",
                "data": {
                    "folder": "test-folder",
                    "device": "DEV-B",
                    "completion": 93.56119493792454,
                    "needBytes": 8_942_011,
                    "needItems": 32,
                    "needDeletes": 19,
                },
            },
        ],
        [
            {
                "id": 104,
                "type": "FolderCompletion",
                "data": {
                    "folder": "test-folder",
                    "device": "DEV-A",
                    "completion": 100,
                    "needBytes": 0,
                    "needItems": 0,
                    "needDeletes": 0,
                },
            },
            {
                "id": 105,
                "type": "FolderCompletion",
                "data": {
                    "folder": "other-folder",
                    "device": "DEV-B",
                    "completion": 1,
                    "needBytes": 1,
                    "needItems": 1,
                    "needDeletes": 1,
                },
            },
            {
                "id": 106,
                "type": "FolderCompletion",
                "data": {
                    "folder": "test-folder",
                    "device": "UNCONFIGURED-DEVICE",
                    "completion": 1,
                    "needBytes": 1,
                    "needItems": 1,
                    "needDeletes": 1,
                },
            },
        ],
        [
            {
                "id": 107,
                "type": "FolderCompletion",
                "data": {
                    "folder": "test-folder",
                    "device": "DEV-B",
                    "completion": 100,
                    "needBytes": 0,
                    "needItems": 0,
                    "needDeletes": 0,
                },
            }
        ],
    ]

    with patch("sdh_ludusavi.syncthing.watcher.get_events", side_effect=event_batches):
        watch._tick_events()
        watch._tick_sample(time.monotonic())
        assert watch.latest_sample["sample"]["uploading"] is True
        assert watch.latest_sample["sample"]["settled"] is False

        watch._tick_events()
        watch.local_activity.outbound_observation_hold_deadline_monotonic = 0
        watch._tick_sample(time.monotonic())
        assert watch.latest_sample["sample"]["uploading"] is True
        assert watch.latest_sample["sample"]["settled"] is False

        watch._tick_events()
        watch.local_activity.last_local_index_monotonic = 0
        watch.local_activity.last_sequence_change_monotonic = 0
        watch._tick_sample(time.monotonic())

    sample = watch.latest_sample["sample"]
    assert sample["uploading"] is False
    assert sample["settled"] is True
    assert set(watch.peer_completions) == {"DEV-A", "DEV-B"}


def test_newly_connected_peer_waits_for_a_fresh_completion_and_disconnects_stop_gating() -> None:
    watch = _stopped_watch_for_tick(("DEV-A", "DEV-B"))
    now = time.monotonic()
    watch.local_activity = LocalActivity(outbound_index_observed_monotonic=now)
    watch.peer_completions = {
        "DEV-A": PeerCompletion("DEV-A", 100.0, 0, 0, 0, now + 1.0),
    }

    watch.connected_devices = frozenset({"DEV-A", "DEV-B"})
    watch._tick_sample(now + 1.0)
    assert watch.latest_sample["sample"]["uploading"] is True

    watch.connected_devices = frozenset({"DEV-A"})
    watch._tick_sample(now + 1.0)
    assert watch.latest_sample["sample"]["uploading"] is False
    assert watch.latest_sample["sample"]["settled"] is True


def test_peer_completion_diagnostics_are_transition_only_and_privacy_safe(caplog) -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))
    now = time.monotonic()
    watch.local_activity = LocalActivity(outbound_index_observed_monotonic=now)
    watch.peer_completions = {
        "DEV-A": PeerCompletion("DEV-A", 93.56119493792454, 8_942_011, 32, 19, now + 1)
    }

    with caplog.at_level("INFO", logger="sdh_ludusavi.syncthing.watcher"):
        watch._tick_sample(now + 1)
        watch._tick_sample(now + 1.5)
        watch.peer_completions["DEV-A"] = PeerCompletion("DEV-A", 100.0, 0, 0, 0, now + 2)
        watch._tick_sample(now + 2)

    transition_records = [
        record
        for record in caplog.records
        if record.name == "sdh_ludusavi.syncthing.watcher" and "peer completion" in record.message
    ]
    assert len(transition_records) == 2
    assert "phase=post_game" in caplog.text
    assert "connected_relevant_peers=1" in caplog.text
    assert "incomplete_peers=1" in caplog.text
    assert "awaiting_fresh_completion=0" in caplog.text
    assert "needed_bytes=8942011" in caplog.text
    assert "needed_items=32" in caplog.text
    assert "needed_deletes=19" in caplog.text
    assert "DEV-A" not in caplog.text
    assert "test-folder" not in caplog.text


def test_malformed_completion_event_keeps_last_good_state_and_never_leaks_payload(caplog) -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))
    now = time.monotonic()
    watch.local_activity = LocalActivity(outbound_index_observed_monotonic=now)
    watch.peer_completions = {
        "DEV-A": PeerCompletion("DEV-A", 93.56119493792454, 8_942_011, 32, 19, now + 1)
    }

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_events",
            side_effect=[
                [
                    {
                        "id": 101,
                        "type": "FolderCompletion",
                        "data": {
                            "folder": "test-folder",
                            "device": "DEV-A",
                            "completion": "RAW-COMPLETION-PAYLOAD",
                            "needBytes": 0,
                            "needItems": 0,
                            "needDeletes": 0,
                        },
                    }
                ],
                [
                    {
                        "id": 102,
                        "type": "FolderCompletion",
                        "data": {
                            "folder": "test-folder",
                            "device": "DEV-A",
                            "completion": 100,
                            "needBytes": 0,
                            "needItems": 0,
                            "needDeletes": 0,
                        },
                    }
                ],
            ],
        ),
        caplog.at_level("DEBUG", logger="sdh_ludusavi.syncthing.watcher"),
    ):
        watch._tick_events()
        watch._tick_sample(now + 1)
        assert watch.latest_sample["sample"]["uploading"] is True

        watch._tick_events()
        watch._tick_sample(now + 2)

    assert watch.latest_sample["sample"]["uploading"] is False
    assert watch.latest_sample["sample"]["settled"] is True
    assert "DEV-A" not in caplog.text
    assert "RAW-COMPLETION-PAYLOAD" not in caplog.text


def test_watch_stops_when_final_relevant_peer_disconnects() -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))

    with patch(
        "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
        return_value=ConnectionSnapshot(connected_devices=frozenset()),
    ):
        watch._tick(time.monotonic())

    assert watch.latest_sample["status"] == "failed"
    assert watch.latest_sample["reason"] == "no_connected_peers"
    assert watch.stop_event.is_set()


def test_watch_continues_while_relevant_peer_connected() -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            return_value=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_folder_status",
            return_value={"state": "idle", "sequence": 5},
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_events", return_value=[]),
    ):
        watch._tick(time.monotonic())

    assert watch.latest_sample["status"] == "activity"
    assert not watch.stop_event.is_set()


def test_watch_keeps_last_known_peers_when_connections_poll_fails() -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            side_effect=RuntimeError("connections endpoint down"),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_folder_status",
            return_value={"state": "idle", "sequence": 5},
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_events", return_value=[]),
    ):
        watch._tick(time.monotonic())

    assert watch.latest_sample["status"] == "activity"
    assert not watch.stop_event.is_set()


def test_watch_ignores_other_folder_traffic_shared_with_relevant_peer() -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))
    now = time.monotonic()
    watch.api = Mock()
    watch.api.get_json.side_effect = [
        {
            "total": {"inBytesTotal": 1_000_000, "outBytesTotal": 1_000_000},
            "connections": {"DEV-A": {"connected": True}},
        },
        {
            "total": {"inBytesTotal": 2_000_000, "outBytesTotal": 2_000_000},
            "connections": {"DEV-A": {"connected": True}},
        },
    ]

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_folder_status",
            side_effect=[
                {"state": "sync-waiting", "sequence": 5},
                {"state": "sync-waiting", "sequence": 5},
            ],
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_events",
            return_value=[
                {
                    "id": 101,
                    "type": "RemoteDownloadProgress",
                    "data": {
                        "folder": "other-folder",
                        "device": "DEV-A",
                        "state": {"other.dat": {}},
                    },
                }
            ],
        ),
    ):
        watch._tick(now)
        watch._tick(now + 1.0)

    sample = watch.latest_sample["sample"]
    assert sample["downloading"] is False
    assert sample["uploading"] is False
    assert sample["status"] != "ACTIVE_TRANSFER"


def test_watch_preserves_watched_folder_download_and_upload_progress() -> None:
    watch = _stopped_watch_for_tick(("DEV-A",))

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            return_value=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_folder_status",
            return_value={"state": "idle", "sequence": 5},
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_events",
            return_value=[
                {
                    "id": 101,
                    "type": "DownloadProgress",
                    "data": {"test-folder": {"save.dat": {}}},
                },
                {
                    "id": 102,
                    "type": "RemoteDownloadProgress",
                    "data": {
                        "folder": "test-folder",
                        "device": "DEV-A",
                        "state": {"save.dat": {}},
                    },
                },
            ],
        ),
    ):
        watch._tick(time.monotonic())

    sample = watch.latest_sample["sample"]
    assert sample["downloading"] is True
    assert sample["uploading"] is True
    assert sample["status"] == "ACTIVE_TRANSFER"


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
def test_watch_manager_sanitizes_system_status_probe_failure(
    mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.side_effect = RuntimeError("HTTP 500 body: RAW-RESPONSE-WITH-DEVICE-ID")

    result = SyncthingWatchManager().start_watch(
        "post_game", "Hades", "1145300", "/home/deck/Sync/Hades"
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "api_unavailable"
    # Raw API responses can hold device IDs and must never travel through RPC.
    assert "RAW-RESPONSE-WITH-DEVICE-ID" not in result["message"]


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
@patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot")
def test_watch_manager_sanitizes_connections_probe_failure(
    mock_snapshot, mock_resolve_path, mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.return_value = "LOCAL-DEVICE"
    mock_resolve_path.return_value = _shared_folder(("DEV-A",))
    mock_snapshot.side_effect = RuntimeError("Invalid JSON: 'RAW-RESPONSE-WITH-DEVICE-ID'")

    result = SyncthingWatchManager().start_watch(
        "post_game", "Hades", "1145300", "/home/deck/Sync/Hades"
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "api_unavailable"
    assert "RAW-RESPONSE-WITH-DEVICE-ID" not in result["message"]


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
def test_watch_manager_keeps_raw_probe_responses_out_of_logs(
    mock_my_id, mock_resolve_creds, caplog
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.side_effect = RuntimeError("HTTP 500 body: RAW-RESPONSE-WITH-DEVICE-ID")

    with caplog.at_level("DEBUG", logger="sdh_ludusavi.syncthing.watcher"):
        result = SyncthingWatchManager().start_watch(
            "post_game", "Hades", "1145300", "/home/deck/Sync/Hades"
        )

    assert result["reason"] == "api_unavailable"
    # get_json errors can embed response bodies holding device IDs; logs must
    # carry only the probe type and exception class.
    assert "RAW-RESPONSE-WITH-DEVICE-ID" not in caplog.text


def test_watch_self_terminates_after_ttl() -> None:
    callback_calls = []

    def on_expired(wid):
        callback_calls.append(wid)

    watch = SyncthingWatch(
        "watch-ttl-1",
        "post_game",
        "Hades",
        "1145300",
        _shared_folder(("DEV-A",)),
        None,
        initial_snapshot=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        on_expired=on_expired,
    )

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime",
            return_value=("idle", FolderRuntime(sequence=5)),
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor", return_value=100),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_peer_completion",
            return_value=PeerCompletion("DEV-A", 100.0, 0, 0, 0, time.monotonic()),
        ),
    ):
        watch.deadline_monotonic = time.monotonic() - 1.0  # force past
        watch._run()  # Should return immediately and set status

    assert watch.stop_event.is_set()
    assert watch.latest_sample == {
        "status": "stopped",
        "watch_id": "watch-ttl-1",
        "reason": "watch_ttl_expired",
    }
    assert callback_calls == ["watch-ttl-1"]


def test_manager_poll_returns_stopped_after_ttl_deregistration() -> None:
    manager = SyncthingWatchManager()

    with (
        patch("sdh_ludusavi.syncthing.watcher.get_initial_folder_state_and_runtime") as mock_init,
        patch("sdh_ludusavi.syncthing.watcher.get_event_cursor") as mock_cursor,
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id") as mock_my_id,
        patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot") as mock_snapshot,
        patch("sdh_ludusavi.syncthing.watcher.get_folder_status") as mock_status,
        patch("sdh_ludusavi.syncthing.watcher.get_events") as mock_events,
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_api_credentials",
            return_value=("http://127.0.0.1:8384", "test-key", None),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_folder_by_path",
            return_value=_shared_folder(("DEV-A",)),
        ),
    ):
        mock_init.return_value = ("idle", FolderRuntime(sequence=5))
        mock_cursor.return_value = 100
        mock_my_id.return_value = "LOCAL-DEVICE"
        mock_snapshot.return_value = ConnectionSnapshot(connected_devices=frozenset({"DEV-A"}))
        mock_status.return_value = {"state": "idle", "sequence": 5}
        mock_events.return_value = []

        res = manager.start_watch("pre_game", "Hades", "1145300", "/home/deck/Sync/Hades")
        watch_id = res["watch_id"]

        # Manually invoke deregistration to simulate expiration
        watch = manager.watches[watch_id]
        watch.stop_event.set()
        watch.thread.join(timeout=1.0)

        manager._deregister_expired_watch(watch_id)

        assert watch_id not in manager.watches
        poll_res = manager.poll_watch(watch_id)
        assert poll_res == {"status": "stopped", "watch_id": watch_id}


def test_watch_within_ttl_does_not_expire() -> None:
    from sdh_ludusavi.syncthing.watcher import WATCH_TTL_SECONDS

    callback_calls = []

    def on_expired(wid):
        callback_calls.append(wid)

    watch = _stopped_watch_for_tick(("DEV-A",))
    watch._on_expired = on_expired
    watch.deadline_monotonic = time.monotonic() + WATCH_TTL_SECONDS

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            return_value=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_folder_status",
            return_value={"state": "idle", "sequence": 5},
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_events", return_value=[]),
    ):
        watch._tick(time.monotonic())

    assert not watch.stop_event.is_set()
    assert len(callback_calls) == 0


def test_no_connected_peers_terminal_watch_stays_registered() -> None:
    callback_calls = []

    def on_expired(wid):
        callback_calls.append(wid)

    watch = _stopped_watch_for_tick(("DEV-A",))
    watch._on_expired = on_expired

    with patch(
        "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
        return_value=ConnectionSnapshot(connected_devices=frozenset()),
    ):
        # We manually call _tick to simulate the disconnect path in the watch loop.
        # It should set stop_event but NOT call on_expired.
        watch._tick(time.monotonic())

    assert watch.latest_sample["status"] == "failed"
    assert watch.latest_sample["reason"] == "no_connected_peers"
    assert watch.stop_event.is_set()
    assert len(callback_calls) == 0


def test_watch_ttl_exceeds_frontend_cap() -> None:
    from sdh_ludusavi.syncthing.watcher import WATCH_TTL_SECONDS

    assert WATCH_TTL_SECONDS >= 120 + 30


def test_start_watch_does_not_block_polling() -> None:
    manager = SyncthingWatchManager()

    # Setup pre-existing watch
    watch_old = SyncthingWatch(
        "old_watch",
        "pre_game",
        "Hades",
        "1145300",
        FolderSelection(folder_id="test-folder", label="Test", path="/path"),
        None,
    )
    manager.watches["old_watch"] = watch_old

    start_event = threading.Event()
    proceed_event = threading.Event()

    def slow_resolve_creds():
        start_event.set()
        proceed_event.wait(timeout=2.0)
        return ("http://127.0.0.1:8384", "key", None)

    def start_slow():
        manager.start_watch("post_game", "Hades", "1145300", "/path")

    with patch(
        "sdh_ludusavi.syncthing.watcher.resolve_api_credentials", side_effect=slow_resolve_creds
    ):
        t = threading.Thread(target=start_slow)
        t.start()

        assert start_event.wait(timeout=2.0)
        # Polling and stop_watch should complete instantly without waiting
        poll_res = manager.poll_watch("old_watch")
        stop_res = manager.stop_watch("old_watch")

        proceed_event.set()
        t.join(timeout=2.0)

    assert poll_res is not None
    assert stop_res["status"] == "stopped"


def test_stop_all_does_not_hold_lock_while_joining() -> None:
    manager = SyncthingWatchManager()

    watch_old = SyncthingWatch(
        "old_watch",
        "pre_game",
        "Hades",
        "1145300",
        FolderSelection(folder_id="test-folder", label="Test", path="/path"),
        None,
    )
    # mock stop to block
    stop_event = threading.Event()
    proceed_event = threading.Event()

    def slow_stop():
        stop_event.set()
        proceed_event.wait(timeout=2.0)

    watch_old.stop = slow_stop
    manager.watches["old_watch"] = watch_old

    def stop_all_thread():
        manager.stop_all()

    t = threading.Thread(target=stop_all_thread)
    t.start()

    assert stop_event.wait(timeout=2.0)
    # The lock must be acquirable here
    acquirable = manager.lock.acquire(timeout=0.1)
    if acquirable:
        manager.lock.release()

    proceed_event.set()
    t.join(timeout=2.0)
    assert acquirable is True


def test_same_signature_replacement_leaves_exactly_one_registered() -> None:
    manager = SyncthingWatchManager()

    watch_old = SyncthingWatch(
        "old_watch",
        "pre_game",
        "Hades",
        "1145300",
        FolderSelection(folder_id="test-folder", label="Test", path="/path"),
        None,
    )
    manager.watches["old_watch"] = watch_old

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_api_credentials",
            return_value=("http://127.0.0.1:8384", "key", None),
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id", return_value="LOCAL"),
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_folder_by_path",
            return_value=_shared_folder(("DEV-A",)),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            return_value=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        ),
        patch.object(SyncthingWatch, "start"),
        patch.object(SyncthingWatch, "stop") as mock_stop,
    ):
        res = manager.start_watch("pre_game", "Hades", "1145300", "/path")

    assert res["status"] == "watching"
    assert len(manager.watches) == 1
    assert "old_watch" not in manager.watches
    assert mock_stop.call_count == 1


def test_cross_phase_replacement_supersedes_first_watch() -> None:
    manager = SyncthingWatchManager()

    watch_old = SyncthingWatch(
        "old_watch",
        "post_game",
        "Hades",
        "1145300",
        FolderSelection(folder_id="test-folder", label="Test", path="/path"),
        None,
    )
    manager.watches["old_watch"] = watch_old

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_api_credentials",
            return_value=("http://127.0.0.1:8384", "key", None),
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id", return_value="LOCAL"),
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_folder_by_path",
            return_value=_shared_folder(("DEV-A",)),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            return_value=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        ),
        patch.object(SyncthingWatch, "start"),
        patch.object(SyncthingWatch, "stop") as mock_stop,
    ):
        res = manager.start_watch("pre_game", "Hades", "1145300", "/path")

    assert res["status"] == "watching"
    assert len(manager.watches) == 1
    assert "old_watch" not in manager.watches
    assert mock_stop.call_count == 1


def test_different_game_does_not_get_stopped() -> None:
    manager = SyncthingWatchManager()

    watch_old = SyncthingWatch(
        "old_watch",
        "pre_game",
        "Hades",
        "1145300",
        FolderSelection(folder_id="test-folder", label="Test", path="/path"),
        None,
    )
    manager.watches["old_watch"] = watch_old

    with (
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_api_credentials",
            return_value=("http://127.0.0.1:8384", "key", None),
        ),
        patch("sdh_ludusavi.syncthing.watcher.get_my_device_id", return_value="LOCAL"),
        patch(
            "sdh_ludusavi.syncthing.watcher.resolve_folder_by_path",
            return_value=_shared_folder(("DEV-A",)),
        ),
        patch(
            "sdh_ludusavi.syncthing.watcher.get_connection_snapshot",
            return_value=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
        ),
        patch.object(SyncthingWatch, "start"),
        patch.object(SyncthingWatch, "stop") as mock_stop,
    ):
        res = manager.start_watch("pre_game", "Celeste", "504230", "/path")

    assert res["status"] == "watching"
    assert len(manager.watches) == 2
    assert "old_watch" in manager.watches
    assert mock_stop.call_count == 0


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.get_my_device_id")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
@patch("sdh_ludusavi.syncthing.watcher.get_connection_snapshot")
def test_watch_manager_concurrent_same_signature_start(
    mock_snapshot, mock_resolve_path, mock_my_id, mock_resolve_creds
) -> None:
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_my_id.return_value = "LOCAL-DEVICE"
    mock_resolve_path.return_value = _shared_folder(("DEV-B",))

    manager = SyncthingWatchManager()
    started_watches = set()
    stopped_watches = set()

    def mock_start(self):
        started_watches.add(self.watch_id)
        # don't actually start the thread for this unit test
        pass

    original_stop = SyncthingWatch.stop

    def mock_stop(self):
        stopped_watches.add(self.watch_id)
        original_stop(self)

    barrier = threading.Barrier(2)

    def mock_get_connection_snapshot(*args, **kwargs):
        barrier.wait()
        # yield some time to let both threads wake up before racing for the lock
        time.sleep(0.05)
        return ConnectionSnapshot(connected_devices=frozenset({"DEV-B"}))

    mock_snapshot.side_effect = mock_get_connection_snapshot

    with (
        patch.object(SyncthingWatch, "start", autospec=True, side_effect=mock_start),
        patch.object(SyncthingWatch, "stop", autospec=True, side_effect=mock_stop),
    ):

        def run_start():
            manager.start_watch("post_game", "Hades", "1145300", "/home/deck/Sync/Hades")

        t1 = threading.Thread(target=run_start)
        t2 = threading.Thread(target=run_start)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # Assert exactly one watch remains registered
    assert len(manager.watches) == 1
    registered_id = list(manager.watches.keys())[0]

    # Assert no started-but-unregistered watch thread survives
    for wid in started_watches:
        if wid != registered_id:
            assert wid in stopped_watches


def test_watch_stop_on_never_started_watch() -> None:
    watch = SyncthingWatch(
        "watch-1",
        "post_game",
        "Hades",
        "1145300",
        _shared_folder(("DEV-A",)),
        None,
        initial_snapshot=ConnectionSnapshot(connected_devices=frozenset({"DEV-A"})),
    )
    # Never call watch.start()
    # Does not raise
    watch.stop()
    assert watch.stop_event.is_set()
