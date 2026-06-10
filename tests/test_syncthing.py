from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import pytest
import time

from sdh_ludusavi.syncthing import (
    api_url_from_gui_address,
    folder_selection_from_config,
    parse_syncthing_config,
    resolve_folder_by_path,
    resolve_folder_by_id,
    compute_activity_status,
    FolderRuntime,
    RemoteProgress,
    LocalActivity,
    ConnectionRates,
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


def test_parse_syncthing_config_fallback_regex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import py_modules.sdh_ludusavi.syncthing.config as syncthing_config

    monkeypatch.setattr(syncthing_config, "HAS_XML_ETREE", False)

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


def test_folder_selection_parses_filesystem_watcher_delay() -> None:
    selection = folder_selection_from_config(
        {
            "id": "folder1",
            "label": "Folder 1",
            "path": "/home/deck/Sync",
            "fsWatcherEnabled": True,
            "fsWatcherDelayS": 12,
            "rescanIntervalS": 3600,
        }
    )

    assert selection.fs_watcher_enabled is True
    assert selection.fs_watcher_delay_seconds == 12
    assert selection.rescan_interval_seconds == 3600


def test_compute_activity_status() -> None:
    now = time.monotonic()

    # 1. Idle state
    status = compute_activity_status(
        folder_state="idle",
        remote_progress={},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(sequence=10),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
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
        runtime=FolderRuntime(sequence=10),
        rates=ConnectionRates(50000.0, 0.0),
        min_rate_bytes_per_second=32768.0,
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
        runtime=FolderRuntime(sequence=10),
        rates=ConnectionRates(0.0, 50000.0),
        min_rate_bytes_per_second=32768.0,
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
        runtime=FolderRuntime(sequence=10),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
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
        runtime=FolderRuntime(sequence=10, need_bytes=100),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.status == "UPDATE_NEEDED"
    assert status.update_in_progress is True
    assert status.settled is False

    # 6. Pending remote ack (Strict TDD RED test: expected to pass eventually but will fail now)
    status = compute_activity_status(
        folder_state="idle",
        remote_progress={},
        local_activity=LocalActivity(),
        runtime=FolderRuntime(sequence=12),
        rates=ConnectionRates(0.0, 0.0),
        min_rate_bytes_per_second=32768.0,
        active_window_seconds=15.0,
        now=now,
    )
    assert status.update_in_progress is False
    assert status.settled is True
