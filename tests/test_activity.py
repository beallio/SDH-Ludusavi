import pytest
from unittest.mock import Mock
from sdh_ludusavi.syncthing.activity import (
    compute_activity_status,
    get_connection_snapshot,
    get_event_cursor,
    get_initial_folder_state_and_runtime,
    get_my_device_id,
    get_peer_completion,
    process_event,
    _serialize_sample,
)
from sdh_ludusavi.syncthing._types import (
    ConnectionSnapshot,
    FolderRuntime,
    FolderSelection,
    LocalActivity,
    PeerCompletion,
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


def test_get_peer_completion_validates_one_configured_peer_response() -> None:
    api = Mock()
    api.get_json.return_value = {
        "completion": 93.56119493792454,
        "needBytes": 8_942_011,
        "needItems": 32,
        "needDeletes": 19,
    }
    folder = FolderSelection(
        folder_id="folder-a",
        label="Folder A",
        path="/sync/a",
        device_ids=("REMOTE-A",),
    )

    completion = get_peer_completion(api, folder, "REMOTE-A", now=42.0)

    assert completion == PeerCompletion(
        device_id="REMOTE-A",
        completion=93.56119493792454,
        need_bytes=8_942_011,
        need_items=32,
        need_deletes=19,
        observed_monotonic=42.0,
    )
    api.get_json.assert_called_once_with(
        "/rest/db/completion",
        params={"folder": "folder-a", "device": "REMOTE-A"},
        timeout=10,
    )


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {"completion": float("nan"), "needBytes": 0, "needItems": 0, "needDeletes": 0},
        {"completion": 100, "needBytes": -1, "needItems": 0, "needDeletes": 0},
        {"completion": 100, "needBytes": 0, "needItems": 0, "needDeletes": True},
    ],
)
def test_get_peer_completion_rejects_malformed_responses_without_device_leaks(response) -> None:
    api = Mock()
    api.get_json.return_value = response
    folder = FolderSelection(
        folder_id="folder-a",
        label="Folder A",
        path="/sync/a",
        device_ids=("SECRET-REMOTE-ID",),
    )

    with pytest.raises(RuntimeError, match="peer completion") as excinfo:
        get_peer_completion(api, folder, "SECRET-REMOTE-ID", now=42.0)

    assert "SECRET-REMOTE-ID" not in str(excinfo.value)


def test_get_peer_completion_sanitizes_api_errors() -> None:
    api = Mock()
    api.get_json.side_effect = RuntimeError("raw body for SECRET-REMOTE-ID")
    folder = FolderSelection(
        folder_id="folder-a",
        label="Folder A",
        path="/sync/a",
        device_ids=("SECRET-REMOTE-ID",),
    )

    with pytest.raises(RuntimeError, match="peer completion") as excinfo:
        get_peer_completion(api, folder, "SECRET-REMOTE-ID", now=42.0)

    assert "SECRET-REMOTE-ID" not in str(excinfo.value)
    assert "raw body" not in str(excinfo.value)


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


def _watched_folder() -> FolderSelection:
    return FolderSelection(
        folder_id="folder-a",
        label="Folder A",
        path="/sync/a",
        device_ids=("REMOTE-A", "REMOTE-B"),
    )


def _folder_completion(
    *,
    folder: str = "folder-a",
    device: str = "REMOTE-A",
    completion: float = 100.0,
    need_bytes: int = 0,
    need_items: int = 0,
    need_deletes: int = 0,
) -> dict:
    return {
        "type": "FolderCompletion",
        "data": {
            "folder": folder,
            "device": device,
            "completion": completion,
            "needBytes": need_bytes,
            "needItems": need_items,
            "needDeletes": need_deletes,
        },
    }


def _post_game_status(
    *,
    peer_completions: dict[str, PeerCompletion],
    local_activity: LocalActivity | None = None,
    connected_devices: frozenset[str] = frozenset({"REMOTE-A"}),
    now: float = 100.0,
    active_window_seconds: float = 0.0,
):
    return compute_activity_status(
        folder_state="idle",
        remote_progress={},
        local_activity=local_activity or LocalActivity(),
        runtime=FolderRuntime(),
        active_window_seconds=active_window_seconds,
        now=now,
        peer_completions=peer_completions,
        connected_relevant_device_ids=connected_devices,
        peer_completion_tracking=True,
    )


@pytest.mark.parametrize(
    "event",
    [
        _folder_completion(folder="folder-b"),
        _folder_completion(device="LOCAL-DEVICE"),
        _folder_completion(device="UNCONFIGURED-DEVICE"),
        {"type": "FolderCompletion", "data": {"device": "REMOTE-A"}},
        {"type": "FolderCompletion", "data": {"folder": "folder-a"}},
        {"type": "FolderCompletion", "data": ["REMOTE-A", "secret-payload"]},
        _folder_completion(completion=float("nan")),
        _folder_completion(completion=float("inf")),
        _folder_completion(completion=-0.1),
        _folder_completion(completion=100.1),
        _folder_completion(need_bytes=-1),
        _folder_completion(need_items=1.5),
        _folder_completion(need_deletes=True),
    ],
)
def test_folder_completion_reducer_ignores_unscoped_and_malformed_payloads(event: dict) -> None:
    peer_completions: dict[str, PeerCompletion] = {}

    process_event(
        event=event,
        folder=_watched_folder(),
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress={},
        local_activity=LocalActivity(),
        now=100.0,
        peer_completions=peer_completions,
        peer_completion_tracking=True,
    )

    assert peer_completions == {}


def test_unrelated_folder_and_unconfigured_device_cannot_activate_the_watched_folder() -> None:
    peer_completions: dict[str, PeerCompletion] = {}
    local_activity = LocalActivity()
    for event in (
        _folder_completion(folder="other-folder", completion=93.56119493792454, need_bytes=1),
        _folder_completion(
            device="UNCONFIGURED-DEVICE", completion=93.56119493792454, need_bytes=1
        ),
    ):
        process_event(
            event=event,
            folder=_watched_folder(),
            folder_state="idle",
            runtime=FolderRuntime(),
            remote_progress={},
            local_activity=local_activity,
            now=100.0,
            peer_completions=peer_completions,
            peer_completion_tracking=True,
        )

    status = _post_game_status(peer_completions=peer_completions, local_activity=local_activity)
    assert status.status == "IDLE"
    assert status.settled is True
    assert status.uploading is False


@pytest.mark.parametrize(
    ("completion", "need_bytes", "need_items", "need_deletes", "expected_uploading"),
    [
        (93.56119493792454, 0, 0, 0, True),
        (100.0, 8_942_011, 0, 0, True),
        (100.0, 0, 32, 0, True),
        (100.0, 0, 0, 19, True),
        (100.0, 0, 0, 0, False),
    ],
)
def test_connected_peer_completion_classifies_outbound_need(
    completion: float,
    need_bytes: int,
    need_items: int,
    need_deletes: int,
    expected_uploading: bool,
) -> None:
    peer_completions: dict[str, PeerCompletion] = {}
    process_event(
        event=_folder_completion(
            completion=completion,
            need_bytes=need_bytes,
            need_items=need_items,
            need_deletes=need_deletes,
        ),
        folder=_watched_folder(),
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress={},
        local_activity=LocalActivity(),
        now=100.0,
        peer_completions=peer_completions,
        peer_completion_tracking=True,
    )

    status = _post_game_status(peer_completions=peer_completions)

    assert status.uploading is expected_uploading
    assert status.update_in_progress is expected_uploading
    assert status.settled is not expected_uploading
    assert status.status == ("ACTIVE_TRANSFER" if expected_uploading else "IDLE")


def test_peer_completion_must_be_fresh_after_watched_index_mutation() -> None:
    folder = _watched_folder()
    peer_completions: dict[str, PeerCompletion] = {}
    local_activity = LocalActivity()

    process_event(
        event=_folder_completion(),
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(sequence=10),
        remote_progress={},
        local_activity=local_activity,
        now=10.0,
        peer_completions=peer_completions,
        peer_completion_tracking=True,
    )
    _, runtime, _, local_activity, _ = process_event(
        event={"type": "LocalIndexUpdated", "data": {"folder": "folder-a", "sequence": 11}},
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(sequence=10),
        remote_progress={},
        local_activity=local_activity,
        now=11.0,
        peer_completions=peer_completions,
        peer_completion_tracking=True,
    )
    assert runtime.sequence == 11

    stale_status = _post_game_status(
        peer_completions=peer_completions,
        local_activity=local_activity,
        now=20.0,
    )
    assert stale_status.uploading is True
    assert stale_status.settled is False

    process_event(
        event=_folder_completion(),
        folder=folder,
        folder_state="idle",
        runtime=runtime,
        remote_progress={},
        local_activity=local_activity,
        now=21.0,
        peer_completions=peer_completions,
        peer_completion_tracking=True,
    )
    fresh_status = _post_game_status(
        peer_completions=peer_completions,
        local_activity=local_activity,
        now=21.0,
    )
    assert fresh_status.uploading is False
    assert fresh_status.settled is True


def test_each_connected_relevant_peer_must_complete_the_mutation() -> None:
    local_activity = LocalActivity(outbound_index_observed_monotonic=10.0)
    peer_completions = {
        "REMOTE-A": PeerCompletion("REMOTE-A", 100.0, 0, 0, 0, 11.0),
        "REMOTE-B": PeerCompletion("REMOTE-B", 93.56119493792454, 8_942_011, 32, 19, 11.0),
    }

    incomplete = _post_game_status(
        peer_completions=peer_completions,
        local_activity=local_activity,
        connected_devices=frozenset({"REMOTE-A", "REMOTE-B"}),
        now=20.0,
    )
    assert incomplete.uploading is True
    assert incomplete.status == "ACTIVE_TRANSFER"

    peer_completions["REMOTE-B"] = PeerCompletion("REMOTE-B", 100.0, 0, 0, 0, 21.0)
    complete = _post_game_status(
        peer_completions=peer_completions,
        local_activity=local_activity,
        connected_devices=frozenset({"REMOTE-A", "REMOTE-B"}),
        now=21.0,
    )
    assert complete.uploading is False
    assert complete.settled is True


def test_disconnected_or_unrelated_peers_cannot_hold_folder_active() -> None:
    peer_completions = {
        "REMOTE-A": PeerCompletion("REMOTE-A", 93.0, 1, 1, 1, 100.0),
        "UNRELATED": PeerCompletion("UNRELATED", 93.0, 1, 1, 1, 100.0),
    }

    status = _post_game_status(
        peer_completions=peer_completions,
        connected_devices=frozenset({"REMOTE-B"}),
    )

    assert status.uploading is False
    assert status.settled is True


def test_remote_download_progress_remains_independent_of_peer_completion_tracking() -> None:
    folder = _watched_folder()
    remote_progress = {}
    _, _, remote_progress, _, _ = process_event(
        event={
            "type": "RemoteDownloadProgress",
            "data": {"folder": "folder-a", "device": "REMOTE-A", "state": {"save.dat": {}}},
        },
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(),
        remote_progress=remote_progress,
        local_activity=LocalActivity(),
        now=100.0,
    )

    status = compute_activity_status(
        folder_state="idle",
        remote_progress=remote_progress,
        local_activity=LocalActivity(),
        runtime=FolderRuntime(),
        active_window_seconds=15.0,
        now=100.0,
        peer_completions={},
        connected_relevant_device_ids=frozenset(),
        peer_completion_tracking=True,
    )
    assert status.uploading is True


def test_outbound_observation_hold_survives_same_batch_mutation_and_completion() -> None:
    folder = _watched_folder()
    peer_completions: dict[str, PeerCompletion] = {}
    local_activity = LocalActivity()
    _, runtime, _, local_activity, _ = process_event(
        event={"type": "LocalIndexUpdated", "data": {"folder": "folder-a", "sequence": 11}},
        folder=folder,
        folder_state="idle",
        runtime=FolderRuntime(sequence=10),
        remote_progress={},
        local_activity=local_activity,
        now=100.0,
        peer_completions=peer_completions,
        peer_completion_tracking=True,
    )
    process_event(
        event=_folder_completion(),
        folder=folder,
        folder_state="idle",
        runtime=runtime,
        remote_progress={},
        local_activity=local_activity,
        now=100.0,
        peer_completions=peer_completions,
        peer_completion_tracking=True,
    )

    held = _post_game_status(
        peer_completions=peer_completions,
        local_activity=local_activity,
        now=102.4,
    )
    expired = _post_game_status(
        peer_completions=peer_completions,
        local_activity=local_activity,
        now=102.6,
    )
    assert held.uploading is True
    assert held.status == "ACTIVE_TRANSFER"
    assert held.settled is False
    assert expired.uploading is False
    assert expired.settled is True


def test_peer_completion_tracking_defaults_to_compatibility_preserving_disabled() -> None:
    peer_completions = {
        "REMOTE-A": PeerCompletion("REMOTE-A", 93.0, 8_942_011, 32, 19, 100.0),
    }

    status = compute_activity_status(
        folder_state="idle",
        remote_progress={},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(),
        active_window_seconds=15.0,
        now=100.0,
        peer_completions=peer_completions,
        connected_relevant_device_ids=frozenset({"REMOTE-A"}),
    )

    assert status.uploading is False
    assert status.update_in_progress is False
    assert status.settled is True


def test_peer_completion_does_not_change_activity_sample_keys() -> None:
    sample = _serialize_sample(
        "watch-id",
        _post_game_status(
            peer_completions={
                "REMOTE-A": PeerCompletion("REMOTE-A", 93.0, 1, 0, 0, 100.0),
            }
        ),
    )

    assert set(sample) == {"status", "watch_id", "sample"}
    assert set(sample["sample"]) == {
        "status",
        "folder_state",
        "update_in_progress",
        "settled",
        "downloading",
        "uploading",
        "timestamp_unix",
    }


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
