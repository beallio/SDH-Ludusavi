from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ==========================================
# Constants
# ==========================================

EVENT_TYPES = ",".join(
    [
        "StateChanged",
        "FolderSummary",
        "FolderScanProgress",
        "DownloadProgress",
        "RemoteDownloadProgress",
        "FolderCompletion",
        "ItemStarted",
        "ItemFinished",
        "LocalChangeDetected",
        "LocalIndexUpdated",
        "FolderPaused",
        "FolderResumed",
        "ConfigSaved",
    ]
)

DEFAULT_API_URL = "http://127.0.0.1:8384"
DEFAULT_ACTIVE_WINDOW_SECONDS = 15.0
# Seven post-backup captures spread local activity across 0.051s to 0.111s, so
# three seconds is about 30x the worst burst. Below roughly 6.5s, first-peer
# confirmation binds first, making shorter values equivalent in practice.
POST_GAME_SETTLE_QUIET_WINDOW_SECONDS = 3.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_EVENT_TIMEOUT_SECONDS = 1.0
DEFAULT_STATUS_POLL_INTERVAL_SECONDS = 1.0
OUTBOUND_OBSERVATION_HOLD_SECONDS = 2.5
# At Syncthing's roughly two-second cadence, three observations provide a
# four-to-six second settling window for multi-write saves; freshness already
# excludes completion reports that predate the observed mutation.
OUTBOUND_CONFIRMATION_OBSERVATIONS = 3
# The observed straggler held needDeletes unchanged for about 60 seconds while
# still making progress, so a 90-second window avoids treating that as stalled.
OUTBOUND_STALL_WINDOW_SECONDS = 90.0
# This is a post-game backstop, not the usual completion path: fifteen minutes
# leaves room for a slow peer while still bounding a watch that never settles.
POST_GAME_WATCH_HARD_CEILING_SECONDS = 900.0

COMMON_SYNCTHING_FLATPAK_IDS = [
    "me.kozec.syncthingtk",
    "com.github.zocker_160.SyncThingy",
    "io.github.martchus.syncthingtray",
    "org.syncthing.Syncthing",
    "com.syncthing.Syncthing",
]

PREPARING_STATES = {
    "sync-waiting",
    "sync-preparing",
    "syncing-waiting",
    "clean-waiting",
    "clean-preparing",
    "cleaning",
}

SCANNING_STATES = {
    "scanning",
    "scan-waiting",
    "scan-preparing",
}

ERROR_STATES = {
    "error",
}

PAUSED_STATES = {
    "paused",
}

# ==========================================
# Dataclasses
# ==========================================


@dataclass(frozen=True)
class SyncthingConfig:
    path: Path
    api_key: str
    api_url: str | None


@dataclass(frozen=True)
class FolderSelection:
    folder_id: str
    label: str
    path: str | None
    selected_path: str | None = None
    folder_type: str | None = None
    paused: bool = False
    fs_watcher_enabled: bool | None = None
    fs_watcher_delay_seconds: int | None = None
    rescan_interval_seconds: int | None = None
    # Configured remote device IDs for this folder. Backend-only: never log
    # these or return them through RPC.
    device_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FolderRuntime:
    sequence: int = 0
    need_bytes: int = 0
    need_total_items: int = 0
    need_deletes: int = 0
    need_files: int = 0
    need_directories: int = 0
    need_symlinks: int = 0
    global_bytes: int = 0
    local_bytes: int = 0
    in_sync_bytes: int = 0
    pull_errors: int = 0
    watch_error: str = ""

    @property
    def need_content_items(self) -> int:
        return self.need_files + self.need_directories + self.need_symlinks


@dataclass
class RemoteProgress:
    device_id: str
    file_count: int
    last_seen_monotonic: float


@dataclass(frozen=True)
class PeerCompletion:
    """Backend-only completion state for one remote folder peer."""

    device_id: str
    completion: float
    need_bytes: int
    need_items: int
    need_deletes: int
    observed_monotonic: float


@dataclass(frozen=True)
class PeerCompletionDiagnostics:
    """Aggregate backend-only completion state for connected relevant peers."""

    connected_relevant_peers: int
    incomplete_peers: int
    peers_pending_deletes: int
    awaiting_fresh_completion: int
    needed_bytes: int
    needed_items: int
    needed_deletes: int

    @property
    def aggregate_outstanding_need(self) -> int:
        # Stall progress must track the content that gates completion. Deletes are
        # diagnostic-only, so their progress cannot mask a stalled upload.
        return self.needed_bytes + self.needed_items


def peer_completion_is_incomplete(completion: PeerCompletion | None) -> bool:
    # Syncthing's completion percentage is reduced by pending deletes, so retaining
    # it would re-introduce delete gating through the back door.
    return completion is not None and (completion.need_bytes > 0 or completion.need_items > 0)


def summarize_peer_completions(
    peer_completions: Mapping[str, PeerCompletion],
    connected_relevant_device_ids: frozenset[str],
    mutation_observed_at: float,
) -> PeerCompletionDiagnostics:
    incomplete_peers = 0
    peers_pending_deletes = 0
    awaiting_fresh_completion = 0
    needed_bytes = 0
    needed_items = 0
    needed_deletes = 0

    for device_id in connected_relevant_device_ids:
        completion = peer_completions.get(device_id)
        if completion is not None:
            needed_deletes += completion.need_deletes
            if completion.need_deletes > 0:
                peers_pending_deletes += 1
            if peer_completion_is_incomplete(completion):
                incomplete_peers += 1
                needed_bytes += completion.need_bytes
                needed_items += completion.need_items
        if mutation_observed_at > 0 and (
            completion is None or completion.observed_monotonic < mutation_observed_at
        ):
            awaiting_fresh_completion += 1

    return PeerCompletionDiagnostics(
        connected_relevant_peers=len(connected_relevant_device_ids),
        incomplete_peers=incomplete_peers,
        peers_pending_deletes=peers_pending_deletes,
        awaiting_fresh_completion=awaiting_fresh_completion,
        needed_bytes=needed_bytes,
        needed_items=needed_items,
        needed_deletes=needed_deletes,
    )


@dataclass(frozen=True)
class ConnectionSnapshot:
    # Device IDs whose Syncthing "connected" field is true. Backend-only:
    # never log these or return them through RPC.
    connected_devices: frozenset[str] = frozenset()


@dataclass
class LocalActivity:
    active_download_files: int = 0
    active_items: dict[str, float] = field(default_factory=dict)
    last_local_change_monotonic: float = 0.0
    last_local_index_monotonic: float = 0.0
    last_sequence_change_monotonic: float = 0.0
    sequence_change_from: int = 0
    sequence_change_to: int = 0
    last_download_progress_monotonic: float = 0.0
    last_scan_progress_monotonic: float = 0.0
    scan_rate_bytes_per_second: float = 0.0
    scan_current_bytes: int = 0
    scan_total_bytes: int = 0
    last_item_finished_monotonic: float = 0.0
    # Monotonic timestamps for outbound peer acknowledgement. These stay in
    # process memory and must never be exposed through the activity RPC.
    outbound_index_observed_monotonic: float = 0.0
    outbound_observation_hold_deadline_monotonic: float = 0.0


@dataclass(frozen=True)
class ActivityStatus:
    status: str
    folder_state: str
    active_transfer: bool
    update_in_progress: bool
    settled: bool
    receive_needed: bool
    downloading: bool
    uploading: bool
    active_remote_devices: int
    active_remote_files: int
    active_download_files: int
    active_items: int
    local_change_recent: bool
    local_index_recent: bool
    sequence_change_recent: bool
    scan_progress_recent: bool
    runtime: FolderRuntime


# ==========================================
# Path utilities
# ==========================================


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def is_inside(parent: str, child: str) -> bool:
    normalized_parent = normalize_path(parent)
    normalized_child = normalize_path(child)
    try:
        return os.path.commonpath([normalized_parent, normalized_child]) == normalized_parent
    except ValueError:
        return False


# ==========================================
# XML / config helpers
# ==========================================


def bool_from_xml_attr(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ==========================================
# Data helpers
# ==========================================


def int_field(data: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(data.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def parse_folder_runtime(data: dict[str, Any]) -> FolderRuntime:
    return FolderRuntime(
        sequence=int_field(data, "sequence", int_field(data, "version", 0)),
        need_bytes=int_field(data, "needBytes", 0),
        need_total_items=int_field(data, "needTotalItems", 0),
        need_deletes=int_field(data, "needDeletes", 0),
        need_files=int_field(data, "needFiles", 0),
        need_directories=int_field(data, "needDirectories", 0),
        need_symlinks=int_field(data, "needSymlinks", 0),
        global_bytes=int_field(data, "globalBytes", 0),
        local_bytes=int_field(data, "localBytes", 0),
        in_sync_bytes=int_field(data, "inSyncBytes", 0),
        pull_errors=int_field(data, "pullErrors", 0),
        watch_error=str(data.get("watchError") or ""),
    )
