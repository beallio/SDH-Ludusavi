from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import pytest
import time
from unittest.mock import patch

from sdh_ludusavi.syncthing import (
    api_url_from_gui_address,
    parse_syncthing_config,
    resolve_folder_by_path,
    resolve_folder_by_id,
    compute_activity_status,
    FolderSelection,
    FolderRuntime,
    RemoteProgress,
    LocalActivity,
    ConnectionRates,
    SyncthingWatchManager,
)


def test_api_url_from_gui_address() -> None:
    assert api_url_from_gui_address("127.0.0.1:8384", False) == "http://127.0.0.1:8384"
    assert api_url_from_gui_address("127.0.0.1:8384", True) == "https://127.0.0.1:8384"
    assert api_url_from_gui_address("0.0.0.0:8384", False) == "http://127.0.0.1:8384"
    assert api_url_from_gui_address(":8384", False) == "http://127.0.0.1:8384"
    assert api_url_from_gui_address("[::]:8384", False) == "http://[::1]:8384"


def test_parse_syncthing_config(tmp_path: Path) -> None:
    config_xml = tmp_path / "config.xml"
    assert parse_syncthing_config(config_xml) is None

    config_xml.write_text("invalid")
    assert parse_syncthing_config(config_xml) is None

    config_xml.write_text(
        "<configuration><gui><address>127.0.0.1:8384</address></gui></configuration>"
    )
    assert parse_syncthing_config(config_xml) is None

    config_xml.write_text(
        '<configuration><gui tls="true"><address>127.0.0.1:8384</address><apikey>testkey</apikey></gui></configuration>'
    )
    cfg = parse_syncthing_config(config_xml)
    assert cfg is not None
    assert cfg.api_key == "testkey"
    assert cfg.api_url == "https://127.0.0.1:8384"


class MockAPI:
    def __init__(self, folders: list[dict] = None) -> None:
        self.folders = folders or []
        self.get_json_calls = []

    def get_json(self, path: str, params: dict = None, timeout: float = 30.0) -> Any:
        self.get_json_calls.append((path, params))
        if path == "/rest/config/folders":
            return self.folders
        raise RuntimeError("Not mocked")


def test_resolve_folder_by_path() -> None:
    folders = [
        {"id": "folder1", "label": "Folder 1", "path": "~/Sync"},
        {"id": "folder2", "label": "Folder 2", "path": "~/Sync/Saves"},
        {"id": "folder3", "label": "Folder 3", "path": "~/Games"},
    ]
    api = MockAPI(folders)

    # Resolve a path inside folder2 (which is deeper than folder1)
    # Note: expanduser will expand ~/ to the user home. Let's expand them for comparison.
    home = os.path.expanduser("~")
    resolved = resolve_folder_by_path(api, os.path.join(home, "Sync/Saves/game1"))
    assert resolved.folder_id == "folder2"
    assert resolved.label == "Folder 2"

    # Path inside folder3
    resolved3 = resolve_folder_by_path(api, os.path.join(home, "Games/game2"))
    assert resolved3.folder_id == "folder3"

    # Path not contained
    with pytest.raises(RuntimeError, match="No configured Syncthing folder contains path"):
        resolve_folder_by_path(api, "/other/path")


def test_resolve_folder_by_id() -> None:
    folders = [
        {"id": "folder1", "label": "Folder 1", "path": "~/Sync"},
    ]
    api = MockAPI(folders)
    resolved = resolve_folder_by_id(api, "folder1")
    assert resolved.folder_id == "folder1"
    assert resolved.label == "Folder 1"

    with pytest.raises(RuntimeError, match="Unknown Syncthing folder ID"):
        resolve_folder_by_id(api, "nonexistent")


def test_compute_activity_status() -> None:
    now = time.monotonic()
    shared_device_ids = ("peer1",)

    # 1. Idle state
    status = compute_activity_status(
        folder_state="idle",
        remote_progress={},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(sequence=10, remote_sequence={"peer1": 10}),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
        shared_device_ids=shared_device_ids,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.status == "IDLE"
    assert status.settled is True
    assert status.downloading is False
    assert status.uploading is False

    # 2. Local downloading (State is syncing)
    status = compute_activity_status(
        folder_state="syncing",
        remote_progress={},
        local_activity=LocalActivity(active_download_files=1),
        runtime=FolderRuntime(sequence=10, remote_sequence={"peer1": 10}),
        rates=ConnectionRates(50000.0, 0.0),
        min_rate_bytes_per_second=32768.0,
        shared_device_ids=shared_device_ids,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.status == "ACTIVE_TRANSFER"
    assert status.settled is False
    assert status.downloading is True
    assert status.uploading is False

    # 3. Local uploading (Remote progress exists)
    status = compute_activity_status(
        folder_state="idle",
        remote_progress={"peer1": RemoteProgress("peer1", file_count=1, last_seen_monotonic=now)},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(sequence=10, remote_sequence={"peer1": 10}),
        rates=ConnectionRates(0.0, 50000.0),
        min_rate_bytes_per_second=32768.0,
        shared_device_ids=shared_device_ids,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.status == "ACTIVE_TRANSFER"
    assert status.settled is False
    assert status.downloading is False
    assert status.uploading is True

    # 4. Scanning state
    status = compute_activity_status(
        folder_state="scanning",
        remote_progress={},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(sequence=10, remote_sequence={"peer1": 10}),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
        shared_device_ids=shared_device_ids,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.status == "SCANNING"
    assert status.update_in_progress is True
    assert status.settled is False

    # 5. Update needed (receive needed)
    status = compute_activity_status(
        folder_state="idle",
        remote_progress={},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(sequence=10, remote_sequence={"peer1": 10}, need_bytes=100),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
        shared_device_ids=shared_device_ids,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.status == "UPDATE_NEEDED"
    assert status.update_in_progress is True
    assert status.settled is False

    # 6. Pending remote ack
    status = compute_activity_status(
        folder_state="idle",
        remote_progress={},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(sequence=12, remote_sequence={"peer1": 10}),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
        shared_device_ids=shared_device_ids,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.pending_remote_ack is True
    assert status.update_in_progress is False
    assert status.settled is False


@patch("sdh_ludusavi.syncthing.watcher.resolve_api_credentials")
@patch("sdh_ludusavi.syncthing.watcher.resolve_folder_by_path")
def test_watch_manager(mock_resolve_path, mock_resolve_creds) -> None:
    # Setup mock SyncthingAPI and credentials
    mock_resolve_creds.return_value = ("http://127.0.0.1:8384", "test-key", None)
    mock_folder = FolderSelection(
        folder_id="test-folder", label="Test Folder", path="/home/deck/Sync"
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
        assert poll_res["sample"]["folder_id"] == "test-folder"

        # Stop watch
        stop_res = manager.stop_watch(watch_id)
        assert stop_res["status"] == "stopped"

        # Poll stopped watch
        poll_stopped = manager.poll_watch(watch_id)
        assert poll_stopped["status"] == "stopped"
