import pytest
from unittest.mock import Mock
from sdh_ludusavi.syncthing.activity import (
    compute_activity_status,
    get_connection_snapshot,
    get_event_cursor,
    get_initial_folder_state_and_runtime,
    get_my_device_id,
    process_event,
)
from sdh_ludusavi.syncthing._types import (
    ConnectionSnapshot,
    FolderRuntime,
    FolderSelection,
    LocalActivity,
)


def test_get_event_cursor_rejects_non_list() -> None:
    class MockAPI:
        def get_json(self, path, params=None, timeout=None):
            return {"error": "malformed"}

    with pytest.raises(RuntimeError, match="Unexpected events response"):
        get_event_cursor(MockAPI())


def test_get_initial_folder_state_and_runtime_strict_failure() -> None:
    api = Mock()
    api.get_json.side_effect = Exception("API offline")

    # Under strict=True, should propagate the exception
    with pytest.raises(Exception, match="API offline"):
        get_initial_folder_state_and_runtime(api, "folder-id", strict=True)


def test_get_initial_folder_state_and_runtime_non_strict_fallback() -> None:
    api = Mock()
    api.get_json.side_effect = Exception("API offline")

    # Under strict=False, should return unknown and empty runtime fallback
    state, runtime = get_initial_folder_state_and_runtime(api, "folder-id", strict=False)
    assert state == "unknown"
    assert isinstance(runtime, FolderRuntime)


def _connections_payload() -> dict:
    return {
        "total": {"inBytesTotal": 100, "outBytesTotal": 200},
        "connections": {
            "DEV-A": {"connected": True},
            "DEV-B": {"connected": False},
            "DEV-C": {"connected": True},
            "DEV-D": "garbage",
        },
    }


def test_get_connection_snapshot_returns_connected_devices_only() -> None:
    api = Mock()
    api.get_json.return_value = _connections_payload()

    snapshot = get_connection_snapshot(api)

    assert snapshot.connected_devices == frozenset({"DEV-A", "DEV-C"})
    assert set(snapshot.__dataclass_fields__) == {"connected_devices"}


def test_get_connection_snapshot_rejects_malformed_response() -> None:
    api = Mock()
    api.get_json.return_value = ["DEV-A", "DEV-B"]

    with pytest.raises(RuntimeError, match="Unexpected system connections response") as excinfo:
        get_connection_snapshot(api)

    # Device IDs are backend-only; the error travels through RPC and must not echo them.
    assert "DEV-A" not in str(excinfo.value)


def test_get_connection_snapshot_rejects_missing_connections_map() -> None:
    api = Mock()
    api.get_json.return_value = {"total": {"inBytesTotal": 100, "outBytesTotal": 200}}

    with pytest.raises(RuntimeError, match="Unexpected system connections response"):
        get_connection_snapshot(api)


def test_get_connection_snapshot_rejects_non_dict_connections_map() -> None:
    api = Mock()
    api.get_json.return_value = {"connections": ["DEV-A"]}

    with pytest.raises(RuntimeError, match="Unexpected system connections response") as excinfo:
        get_connection_snapshot(api)

    assert "DEV-A" not in str(excinfo.value)


def test_get_connection_snapshot_does_not_require_totals() -> None:
    api = Mock()
    api.get_json.return_value = {"connections": {"DEV-A": {"connected": True}}}

    snapshot = get_connection_snapshot(api)

    assert snapshot.connected_devices == frozenset({"DEV-A"})


def test_connection_bytes_cannot_create_transfer_direction_from_folder_mutation() -> None:
    now = 100.0
    api = Mock()
    api.get_json.return_value = {
        "total": {"inBytesTotal": 1_000_000, "outBytesTotal": 1_000_000},
        "connections": {"SHARED-PEER": {"connected": True}},
    }

    snapshot = get_connection_snapshot(api)
    assert snapshot == ConnectionSnapshot(connected_devices=frozenset({"SHARED-PEER"}))

    status = compute_activity_status(
        folder_state="sync-waiting",
        remote_progress={},
        local_activity=LocalActivity(
            last_local_index_monotonic=now,
            last_sequence_change_monotonic=now,
            sequence_change_from=10,
            sequence_change_to=11,
        ),
        runtime=FolderRuntime(sequence=11),
        active_window_seconds=15.0,
        now=now,
    )

    assert status.downloading is False
    assert status.uploading is False
    assert status.status != "ACTIVE_TRANSFER"


@pytest.mark.parametrize(
    "event",
    [
        {
            "type": "RemoteDownloadProgress",
            "data": {
                "folder": "folder-b",
                "device": "SHARED-PEER",
                "state": {"save.dat": {}},
            },
        },
        {"type": "StateChanged", "data": {"folder": "folder-b", "to": "syncing"}},
        {
            "type": "FolderSummary",
            "data": {"folder": "folder-b", "summary": {"state": "syncing", "sequence": 99}},
        },
        {
            "type": "FolderScanProgress",
            "data": {"folder": "folder-b", "rate": 1000, "current": 50, "total": 100},
        },
        {"type": "ItemStarted", "data": {"folder": "folder-b", "item": "save.dat"}},
        {"type": "ItemFinished", "data": {"folder": "folder-b", "item": "save.dat"}},
        {"type": "LocalChangeDetected", "data": {"folder": "folder-b"}},
        {
            "type": "LocalIndexUpdated",
            "data": {"folder": "folder-b", "sequence": 99},
        },
    ],
)
def test_process_event_ignores_unrelated_folder_activity(event: dict) -> None:
    folder = FolderSelection(
        folder_id="folder-a",
        label="Folder A",
        path="/sync/a",
        device_ids=("SHARED-PEER",),
    )
    runtime = FolderRuntime(sequence=10, need_bytes=25)
    remote_progress = {}
    local_activity = LocalActivity(active_items={"existing.dat": 90.0})

    result = process_event(
        event=event,
        folder=folder,
        folder_state="idle",
        runtime=runtime,
        remote_progress=remote_progress,
        local_activity=local_activity,
        now=100.0,
    )

    assert result == (
        "idle",
        runtime,
        {},
        LocalActivity(active_items={"existing.dat": 90.0}),
        False,
    )


def test_download_progress_updates_only_the_watched_folder() -> None:
    folder = FolderSelection(folder_id="folder-a", label="Folder A", path="/sync/a")
    local_activity = LocalActivity(active_download_files=2, last_download_progress_monotonic=90.0)

    _, _, _, local_activity, _ = process_event(
        event={"type": "DownloadProgress", "data": {"folder-b": {"other.dat": {}}}},
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress={},
        local_activity=local_activity,
        now=100.0,
    )
    assert local_activity.active_download_files == 2
    assert local_activity.last_download_progress_monotonic == 90.0

    _, _, _, local_activity, _ = process_event(
        event={"type": "DownloadProgress", "data": {"folder-a": {"save.dat": {}}}},
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress={},
        local_activity=local_activity,
        now=101.0,
    )
    assert local_activity.active_download_files == 1
    assert local_activity.last_download_progress_monotonic == 101.0

    _, _, _, local_activity, _ = process_event(
        event={"type": "DownloadProgress", "data": {"folder-b": {"other.dat": {}}}},
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress={},
        local_activity=local_activity,
        now=102.0,
    )
    assert local_activity.active_download_files == 1

    _, _, _, local_activity, _ = process_event(
        event={"type": "DownloadProgress", "data": {}},
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress={},
        local_activity=local_activity,
        now=103.0,
    )
    assert local_activity.active_download_files == 0
    assert local_activity.last_download_progress_monotonic == 103.0


def test_watched_folder_progress_preserves_download_and_upload_direction() -> None:
    now = 100.0
    folder = FolderSelection(
        folder_id="folder-a",
        label="Folder A",
        path="/sync/a",
        device_ids=("SHARED-PEER",),
    )
    local_activity = LocalActivity()
    remote_progress = {}

    _, _, remote_progress, local_activity, _ = process_event(
        event={"type": "DownloadProgress", "data": {"folder-a": {"save.dat": {}}}},
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress=remote_progress,
        local_activity=local_activity,
        now=now,
    )
    download_status = compute_activity_status(
        folder_state="idle",
        remote_progress=remote_progress,
        local_activity=local_activity,
        runtime=FolderRuntime(),
        active_window_seconds=15.0,
        now=now,
    )
    assert download_status.downloading is True

    _, _, remote_progress, local_activity, _ = process_event(
        event={
            "type": "RemoteDownloadProgress",
            "data": {
                "folder": "folder-b",
                "device": "SHARED-PEER",
                "state": {"other.dat": {}},
            },
        },
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress=remote_progress,
        local_activity=local_activity,
        now=now,
    )
    assert remote_progress == {}

    _, _, remote_progress, local_activity, _ = process_event(
        event={
            "type": "RemoteDownloadProgress",
            "data": {
                "folder": "folder-a",
                "device": "SHARED-PEER",
                "state": {"save.dat": {}},
            },
        },
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress=remote_progress,
        local_activity=local_activity,
        now=now,
    )
    upload_status = compute_activity_status(
        folder_state="idle",
        remote_progress=remote_progress,
        local_activity=LocalActivity(),
        runtime=FolderRuntime(),
        active_window_seconds=15.0,
        now=now,
    )
    assert upload_status.uploading is True


def test_get_my_device_id() -> None:
    api = Mock()
    api.get_json.return_value = {"myID": "LOCAL-DEVICE"}

    assert get_my_device_id(api) == "LOCAL-DEVICE"


def test_get_my_device_id_rejects_malformed_response() -> None:
    api = Mock()
    api.get_json.return_value = {"myID": ""}

    with pytest.raises(RuntimeError, match="Unexpected system status response"):
        get_my_device_id(api)


def test_get_my_device_id_error_does_not_echo_response() -> None:
    api = Mock()
    api.get_json.return_value = {"myID": 123, "nearbyID": "SOME-DEVICE"}

    with pytest.raises(RuntimeError, match="Unexpected system status response") as excinfo:
        get_my_device_id(api)

    assert "SOME-DEVICE" not in str(excinfo.value)
