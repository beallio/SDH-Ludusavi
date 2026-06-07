import pytest
from unittest.mock import Mock
from sdh_ludusavi.syncthing.activity import (
    get_event_cursor,
    get_initial_folder_state_and_runtime,
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
