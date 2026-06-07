from __future__ import annotations

from sdh_ludusavi.syncthing import FolderSelection


def test_folder_selection_exposes_filesystem_watcher_delay() -> None:
    selection = FolderSelection(
        folder_id="saves",
        label="Saves",
        path="/home/deck/Sync",
        fs_watcher_delay_seconds=12,
    )

    assert selection.fs_watcher_delay_seconds == 12
