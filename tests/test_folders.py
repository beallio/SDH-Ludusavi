from __future__ import annotations

from sdh_ludusavi.syncthing import folder_selection_from_config


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
