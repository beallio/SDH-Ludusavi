from __future__ import annotations

from sdh_ludusavi.syncthing import folder_selection_from_config, resolve_folder_by_path


def test_folder_selection_parses_watcher_timing() -> None:
    selection = folder_selection_from_config(
        {
            "id": "saves",
            "path": "/home/deck/Sync",
            "fsWatcherEnabled": True,
            "fsWatcherDelayS": 12,
            "rescanIntervalS": 3600,
        }
    )

    assert selection.fs_watcher_delay_seconds == 12
    assert selection.rescan_interval_seconds == 3600


def test_folder_selection_parses_device_ids_with_deduplication() -> None:
    selection = folder_selection_from_config(
        {
            "id": "saves",
            "path": "/home/deck/Sync",
            "devices": [
                {"deviceID": "DEV-B"},
                {"deviceID": "DEV-A"},
                {"deviceID": "DEV-B"},
                {"deviceID": ""},
                {"deviceID": None},
                "not-a-dict",
            ],
        }
    )

    assert selection.device_ids == ("DEV-A", "DEV-B")


def test_folder_selection_excludes_local_device() -> None:
    selection = folder_selection_from_config(
        {
            "id": "saves",
            "path": "/home/deck/Sync",
            "devices": [{"deviceID": "LOCAL"}, {"deviceID": "REMOTE"}],
        },
        local_device_id="LOCAL",
    )

    assert selection.device_ids == ("REMOTE",)


def test_folder_selection_defaults_to_no_devices() -> None:
    selection = folder_selection_from_config({"id": "saves", "path": "/home/deck/Sync"})

    assert selection.device_ids == ()


def test_resolve_folder_by_path_excludes_local_device(tmp_path) -> None:
    class MockAPI:
        def get_json(self, path, params=None, timeout=None):
            return [
                {
                    "id": "saves",
                    "path": str(tmp_path),
                    "devices": [{"deviceID": "LOCAL"}, {"deviceID": "REMOTE"}],
                }
            ]

    selection = resolve_folder_by_path(MockAPI(), str(tmp_path / "Hades"), local_device_id="LOCAL")

    assert selection.folder_id == "saves"
    assert selection.device_ids == ("REMOTE",)
