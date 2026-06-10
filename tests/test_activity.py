import pytest
from unittest.mock import Mock
from sdh_ludusavi.syncthing.activity import (
    get_connection_snapshot,
    get_connection_totals,
    get_event_cursor,
    get_initial_folder_state_and_runtime,
    get_my_device_id,
)
from sdh_ludusavi.syncthing._types import FolderRuntime


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


def test_get_connection_snapshot_parses_totals_and_connected_devices() -> None:
    api = Mock()
    api.get_json.return_value = _connections_payload()

    snapshot = get_connection_snapshot(api)

    assert snapshot.in_bytes_total == 100
    assert snapshot.out_bytes_total == 200
    assert snapshot.connected_devices == frozenset({"DEV-A", "DEV-C"})


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


def test_get_connection_snapshot_tolerates_missing_totals() -> None:
    api = Mock()
    api.get_json.return_value = {"connections": {"DEV-A": {"connected": True}}}

    snapshot = get_connection_snapshot(api)

    assert snapshot.in_bytes_total == 0
    assert snapshot.out_bytes_total == 0
    assert snapshot.connected_devices == frozenset({"DEV-A"})


def test_get_connection_totals_wraps_snapshot() -> None:
    api = Mock()
    api.get_json.return_value = _connections_payload()

    assert get_connection_totals(api) == (100, 200)


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
