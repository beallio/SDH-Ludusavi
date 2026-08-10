from __future__ import annotations

from sdh_ludusavi.syncthing import (
    EVENT_TYPES,
    OUTBOUND_OBSERVATION_HOLD_SECONDS,
    FolderSelection,
    PeerCompletion,
)


def test_folder_selection_exposes_filesystem_watcher_delay() -> None:
    selection = FolderSelection(
        folder_id="saves",
        label="Saves",
        path="/home/deck/Sync",
        fs_watcher_delay_seconds=12,
    )

    assert selection.fs_watcher_delay_seconds == 12


def test_peer_completion_model_and_event_subscription_are_backend_only() -> None:
    completion = PeerCompletion(
        device_id="REMOTE-DEVICE",
        completion=93.56119493792454,
        need_bytes=8_942_011,
        need_items=32,
        need_deletes=19,
        observed_monotonic=123.0,
    )

    assert "FolderCompletion" in EVENT_TYPES.split(",")
    assert OUTBOUND_OBSERVATION_HOLD_SECONDS == 2.5
    assert completion.device_id == "REMOTE-DEVICE"
    assert completion.completion < 100
    assert completion.need_bytes == 8_942_011
