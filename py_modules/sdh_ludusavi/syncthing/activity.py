from __future__ import annotations

import logging
import time
import math
from typing import Any

from .api import SyncthingAPI
from ._types import (
    EVENT_TYPES,
    PREPARING_STATES,
    SCANNING_STATES,
    ERROR_STATES,
    PAUSED_STATES,
    FolderSelection,
    FolderRuntime,
    RemoteProgress,
    PeerCompletion,
    ConnectionSnapshot,
    LocalActivity,
    ActivityStatus,
    OUTBOUND_OBSERVATION_HOLD_SECONDS,
    peer_completion_is_incomplete,
    summarize_peer_completions,
    int_field,
    parse_folder_runtime,
)

logger = logging.getLogger(__name__)
_MAX_COMPLETION_COUNTER = (2**63) - 1


def get_folder_status(api: SyncthingAPI, folder_id: str) -> dict[str, Any]:
    status = api.get_json("/rest/db/status", params={"folder": folder_id}, timeout=10)
    if not isinstance(status, dict):
        raise RuntimeError(f"Unexpected status response for {folder_id}: {status}")
    return status


def get_initial_folder_state_and_runtime(
    api: SyncthingAPI, folder_id: str, strict: bool = False
) -> tuple[str, FolderRuntime]:
    try:
        status = get_folder_status(api, folder_id)
        state = status.get("state")
        if strict and (not state or state == "unknown"):
            raise RuntimeError(f"Invalid initial folder state: {state}")
        return (str(state) if state else "unknown"), parse_folder_runtime(status)
    # Intentionally broad
    except Exception:
        if strict:
            raise
        return "unknown", FolderRuntime()


def get_event_cursor(api: SyncthingAPI) -> int:
    # Syncthing scopes id to the subscription selected by events= and matches
    # since against that scoped id, while globalID is process-wide. Keep this
    # filter aligned with get_events() so the seeded cursor is usable there.
    events = api.get_json(
        "/rest/events",
        params={"since": 0, "limit": 1000, "timeout": 1, "events": EVENT_TYPES},
        timeout=5,
    )
    if not isinstance(events, list):
        raise RuntimeError(f"Unexpected events response: {events}")
    return max((int(event.get("id", 0)) for event in events), default=0)


def get_events(api: SyncthingAPI, since: int, event_timeout_seconds: float) -> list[dict[str, Any]]:
    timeout_param = max(1, int(math.ceil(event_timeout_seconds)))
    events = api.get_json(
        "/rest/events",
        params={
            "since": since,
            "timeout": timeout_param,
            "events": EVENT_TYPES,
        },
        timeout=timeout_param + 10,
    )
    if not events:
        return []
    if not isinstance(events, list):
        raise RuntimeError(f"Unexpected events response: {events}")
    return events


def get_connection_snapshot(api: SyncthingAPI) -> ConnectionSnapshot:
    # Errors here travel through RPC via start_watch; never echo the response
    # payload because it can contain device IDs, which are backend-only.
    data = api.get_json("/rest/system/connections", timeout=10)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected system connections response: not a JSON object")
    # A missing or non-dict connections map must fail rather than read as
    # "all peers offline"; an empty connected set is a peer-availability signal.
    connections = data.get("connections")
    if not isinstance(connections, dict):
        raise RuntimeError("Unexpected system connections response: missing connections map")
    connected_devices = frozenset(
        device_id
        for device_id, info in connections.items()
        if isinstance(info, dict) and info.get("connected") is True
    )
    return ConnectionSnapshot(
        connected_devices=connected_devices,
    )


def get_my_device_id(api: SyncthingAPI) -> str:
    # Same RPC-visible error path as above: the payload holds device IDs.
    data = api.get_json("/rest/system/status", timeout=10)
    my_id = data.get("myID") if isinstance(data, dict) else None
    if not isinstance(my_id, str) or not my_id:
        raise RuntimeError("Unexpected system status response: missing myID")
    return my_id


def get_peer_completion(
    api: SyncthingAPI,
    folder: FolderSelection,
    device_id: str,
    now: float,
) -> PeerCompletion:
    """Read and validate one remote peer's completion for *folder*.

    Syncthing's response does not repeat the requested folder or device, so those
    backend-only values are supplied to the existing scoped parser rather than
    trusting a response field. Errors from the REST client can contain raw bodies
    and device IDs, so this boundary intentionally emits only generic errors.
    """
    try:
        data = api.get_json(
            "/rest/db/completion",
            params={"folder": folder.folder_id, "device": device_id},
            timeout=10,
        )
    # The API error can include response data and the backend-only device ID.
    except Exception as exc:
        raise RuntimeError("Syncthing peer completion query failed.") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Unexpected peer completion response.")

    completion = _parse_peer_completion(
        {**data, "folder": folder.folder_id, "device": device_id}, folder, now
    )
    if completion is None:
        raise RuntimeError("Invalid peer completion response.")
    return completion


def prune_remote_progress(
    remote_progress: dict[str, RemoteProgress], active_window: float, now: float
) -> dict[str, RemoteProgress]:
    return {
        device_id: progress
        for device_id, progress in remote_progress.items()
        if now - progress.last_seen_monotonic <= active_window
    }


def prune_local_activity(activity: LocalActivity, active_window: float, now: float) -> None:
    """Mutate *activity* in place, pruning stale entries."""
    activity.active_items = {
        item: last_seen
        for item, last_seen in activity.active_items.items()
        if now - last_seen <= active_window
    }
    if now - activity.last_scan_progress_monotonic > active_window:
        activity.scan_rate_bytes_per_second = 0.0
        activity.scan_current_bytes = 0
        activity.scan_total_bytes = 0
    if (
        activity.active_download_files
        and activity.last_download_progress_monotonic > 0
        and now - activity.last_download_progress_monotonic > active_window
    ):
        activity.active_download_files = 0


def _bounded_number(data: dict[str, Any], key: str, minimum: float, maximum: float) -> float | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return None
    return number


def _nonnegative_completion_counter(data: dict[str, Any], key: str) -> int | None:
    value = _bounded_number(data, key, 0, _MAX_COMPLETION_COUNTER)
    if value is None or not value.is_integer():
        return None
    return int(value)


def _parse_peer_completion(
    data: dict[str, Any], folder: FolderSelection, now: float
) -> PeerCompletion | None:
    if data.get("folder") != folder.folder_id:
        return None
    device_id = data.get("device")
    if not isinstance(device_id, str) or not device_id or device_id not in folder.device_ids:
        return None

    completion = _bounded_number(data, "completion", 0, 100)
    need_bytes = _nonnegative_completion_counter(data, "needBytes")
    need_items = _nonnegative_completion_counter(data, "needItems")
    need_deletes = _nonnegative_completion_counter(data, "needDeletes")
    if completion is None:
        return None
    if need_bytes is None or need_items is None or need_deletes is None:
        return None

    return PeerCompletion(
        device_id=device_id,
        completion=completion,
        need_bytes=need_bytes,
        need_items=need_items,
        need_deletes=need_deletes,
        observed_monotonic=now,
    )


def _serialize_sample(
    watch_id: str,
    status: ActivityStatus,
) -> dict[str, Any]:
    return {
        "status": "activity",
        "watch_id": watch_id,
        "sample": {
            "status": status.status,
            "folder_state": status.folder_state,
            "update_in_progress": status.update_in_progress,
            "settled": status.settled,
            "downloading": status.downloading,
            "uploading": status.uploading,
            "timestamp_unix": time.time(),
        },
    }


def compute_activity_status(
    folder_state: str,
    remote_progress: dict[str, RemoteProgress],
    local_activity: LocalActivity,
    runtime: FolderRuntime,
    active_window_seconds: float,
    now: float,
    peer_completions: dict[str, PeerCompletion] | None = None,
    connected_relevant_device_ids: frozenset[str] = frozenset(),
    peer_completion_tracking: bool = False,
) -> ActivityStatus:
    normalized_state = folder_state or "unknown"
    active_items = local_activity.active_items

    local_change_recent = (
        local_activity.last_local_change_monotonic > 0
        and now - local_activity.last_local_change_monotonic <= active_window_seconds
    )
    local_index_recent = (
        local_activity.last_local_index_monotonic > 0
        and now - local_activity.last_local_index_monotonic <= active_window_seconds
    )
    sequence_change_recent = (
        local_activity.last_sequence_change_monotonic > 0
        and now - local_activity.last_sequence_change_monotonic <= active_window_seconds
    )
    scan_progress_recent = (
        local_activity.last_scan_progress_monotonic > 0
        and now - local_activity.last_scan_progress_monotonic <= active_window_seconds
    )

    receive_needed = (
        runtime.need_bytes > 0 or runtime.need_total_items > 0 or runtime.need_deletes > 0
    )
    preparing = normalized_state in PREPARING_STATES
    scanning = normalized_state in SCANNING_STATES or scan_progress_recent

    item_finished_recent = (
        local_activity.last_item_finished_monotonic > 0
        and now - local_activity.last_item_finished_monotonic <= 2.0
    )

    downloading = (
        normalized_state == "syncing"
        or local_activity.active_download_files > 0
        or bool(active_items)
    )

    peer_completions = peer_completions or {}
    incomplete_peer = False
    awaiting_fresh_peer_completion = False
    outbound_observation_hold_active = False
    if peer_completion_tracking:
        completion_diagnostics = summarize_peer_completions(
            peer_completions,
            connected_relevant_device_ids,
            local_activity.outbound_index_observed_monotonic,
        )
        incomplete_peer = completion_diagnostics.incomplete_peers > 0
        awaiting_fresh_peer_completion = completion_diagnostics.awaiting_fresh_completion > 0
        outbound_observation_hold_active = (
            now < local_activity.outbound_observation_hold_deadline_monotonic
        )

    uploading = (
        bool(remote_progress)
        or incomplete_peer
        or awaiting_fresh_peer_completion
        or outbound_observation_hold_active
    )

    active_transfer = downloading or uploading
    update_in_progress = (
        active_transfer
        or receive_needed
        or preparing
        or scanning
        or local_change_recent
        or local_index_recent
        or sequence_change_recent
        or bool(active_items)
        or item_finished_recent
    )
    settled = (
        normalized_state == "idle"
        and not update_in_progress
        and not local_activity.active_download_files
        and not remote_progress
        and runtime.pull_errors == 0
        and not runtime.watch_error
    )

    if active_transfer:
        status = "ACTIVE_TRANSFER"
    elif normalized_state in ERROR_STATES or runtime.pull_errors > 0 or runtime.watch_error:
        status = "ERROR"
    elif normalized_state in PAUSED_STATES:
        status = "PAUSED"
    elif scanning:
        status = "SCANNING"
    elif receive_needed:
        status = "UPDATE_NEEDED"
    elif preparing:
        status = "PREPARING"
    elif local_change_recent or local_index_recent or sequence_change_recent:
        status = "INDEXING_OR_SEQUENCE_UPDATE"
    else:
        status = "IDLE"

    return ActivityStatus(
        status=status,
        folder_state=normalized_state,
        active_transfer=active_transfer,
        update_in_progress=update_in_progress,
        settled=settled,
        receive_needed=receive_needed,
        downloading=downloading,
        uploading=uploading,
        active_remote_devices=len(remote_progress),
        active_remote_files=sum(p.file_count for p in remote_progress.values()),
        active_download_files=local_activity.active_download_files,
        active_items=len(active_items),
        local_change_recent=local_change_recent,
        local_index_recent=local_index_recent,
        sequence_change_recent=sequence_change_recent,
        scan_progress_recent=scan_progress_recent,
        runtime=runtime,
    )


def process_event(
    event: dict[str, Any],
    folder: FolderSelection,
    folder_state: str,
    runtime: FolderRuntime,
    remote_progress: dict[str, RemoteProgress],
    local_activity: LocalActivity,
    now: float,
    peer_completions: dict[str, PeerCompletion] | None = None,
    peer_completion_tracking: bool = False,
) -> tuple[str, FolderRuntime, dict[str, RemoteProgress], LocalActivity, bool]:
    event_type = event.get("type")
    data = event.get("data") or {}
    config_changed = False

    if not isinstance(data, dict):
        return folder_state, runtime, remote_progress, local_activity, config_changed

    def _folder_match() -> bool:
        return data.get("folder") == folder.folder_id

    if event_type == "StateChanged" and _folder_match():
        folder_state = str(data.get("to") or folder_state)
    elif event_type == "FolderSummary" and _folder_match():
        summary = data.get("summary") or {}
        if isinstance(summary, dict):
            if summary.get("state"):
                folder_state = str(summary["state"])
            runtime = parse_folder_runtime(summary)
    elif event_type == "FolderScanProgress" and _folder_match():
        local_activity.last_scan_progress_monotonic = now
        local_activity.scan_rate_bytes_per_second = float(data.get("rate") or 0.0)
        local_activity.scan_current_bytes = int_field(data, "current", 0)
        local_activity.scan_total_bytes = int_field(data, "total", 0)
    elif event_type == "DownloadProgress":
        folder_downloads = data.get(folder.folder_id)
        if isinstance(folder_downloads, dict):
            local_activity.active_download_files = len(folder_downloads)
            local_activity.last_download_progress_monotonic = now
            if folder_downloads:
                local_activity.last_local_index_monotonic = now
        elif not data:
            local_activity.active_download_files = 0
            local_activity.last_download_progress_monotonic = now
    elif event_type == "RemoteDownloadProgress" and _folder_match():
        device_id = str(data.get("device") or "unknown")
        state = data.get("state") or {}
        file_count = len(state) if isinstance(state, dict) else 0
        if file_count > 0:
            remote_progress[device_id] = RemoteProgress(
                device_id=device_id,
                file_count=file_count,
                last_seen_monotonic=now,
            )
        else:
            remote_progress.pop(device_id, None)
    elif (
        event_type == "FolderCompletion"
        and peer_completion_tracking
        and peer_completions is not None
    ):
        completion = _parse_peer_completion(data, folder, now)
        if completion is not None:
            peer_completions[completion.device_id] = completion
            if peer_completion_is_incomplete(completion):
                local_activity.outbound_observation_hold_deadline_monotonic = max(
                    local_activity.outbound_observation_hold_deadline_monotonic,
                    now + OUTBOUND_OBSERVATION_HOLD_SECONDS,
                )
    elif event_type == "ItemStarted" and _folder_match():
        item = str(data.get("item") or "unknown")
        local_activity.active_items[item] = now
    elif event_type == "ItemFinished" and _folder_match():
        item = str(data.get("item") or "unknown")
        local_activity.active_items.pop(item, None)
        local_activity.last_item_finished_monotonic = now
    elif event_type == "LocalChangeDetected" and _folder_match():
        local_activity.last_local_change_monotonic = now
    elif event_type == "LocalIndexUpdated" and _folder_match():
        local_activity.last_local_index_monotonic = now
        sequence = int_field(data, "sequence", int_field(data, "version", runtime.sequence))
        previous_sequence = runtime.sequence
        if sequence and sequence != previous_sequence:
            local_activity.last_sequence_change_monotonic = now
            local_activity.sequence_change_from = previous_sequence
            local_activity.sequence_change_to = sequence
        if sequence > previous_sequence:
            local_activity.outbound_index_observed_monotonic = now
            local_activity.outbound_observation_hold_deadline_monotonic = max(
                local_activity.outbound_observation_hold_deadline_monotonic,
                now + OUTBOUND_OBSERVATION_HOLD_SECONDS,
            )
        runtime = FolderRuntime(
            sequence=sequence or runtime.sequence,
            need_bytes=runtime.need_bytes,
            need_total_items=runtime.need_total_items,
            need_deletes=runtime.need_deletes,
            global_bytes=runtime.global_bytes,
            local_bytes=runtime.local_bytes,
            in_sync_bytes=runtime.in_sync_bytes,
            pull_errors=runtime.pull_errors,
            watch_error=runtime.watch_error,
        )
    elif event_type == "FolderPaused" and _folder_match():
        folder_state = "paused"
    elif event_type == "FolderResumed" and _folder_match():
        folder_state = "unknown"
    elif event_type == "ConfigSaved":
        config_changed = True

    return folder_state, runtime, remote_progress, local_activity, config_changed
