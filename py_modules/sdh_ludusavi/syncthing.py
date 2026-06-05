from __future__ import annotations

import logging
import os
import sys
import ssl
import json
import time
import uuid
import math
import threading
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

EVENT_TYPES = ",".join(
    [
        "StateChanged",
        "FolderSummary",
        "FolderScanProgress",
        "DownloadProgress",
        "RemoteDownloadProgress",
        "ItemStarted",
        "ItemFinished",
        "LocalChangeDetected",
        "LocalIndexUpdated",
        "RemoteIndexUpdated",
        "FolderPaused",
        "FolderResumed",
        "ConfigSaved",
    ]
)

DEFAULT_API_URL = "http://127.0.0.1:8384"
DEFAULT_ACTIVE_WINDOW_SECONDS = 15.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_EVENT_TIMEOUT_SECONDS = 1.0
DEFAULT_STATUS_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_MIN_RATE_BYTES_PER_SECOND = 32768.0

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
    rescan_interval_seconds: int | None = None
    shared_device_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FolderRuntime:
    sequence: int = 0
    remote_sequence: dict[str, int] = field(default_factory=dict)
    need_bytes: int = 0
    need_total_items: int = 0
    need_deletes: int = 0
    global_bytes: int = 0
    local_bytes: int = 0
    in_sync_bytes: int = 0
    pull_errors: int = 0
    watch_error: str = ""


@dataclass
class RemoteProgress:
    device_id: str
    file_count: int
    last_seen_monotonic: float


@dataclass(frozen=True)
class ConnectionRates:
    in_bytes_per_second: float
    out_bytes_per_second: float


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
    aggregate_downloading: bool
    aggregate_uploading: bool
    active_remote_devices: int
    active_remote_files: int
    active_download_files: int
    active_items: int
    local_change_recent: bool
    local_index_recent: bool
    sequence_change_recent: bool
    scan_progress_recent: bool
    pending_remote_ack: bool
    lagging_remote_devices: int
    runtime: FolderRuntime
    rates: ConnectionRates


class SyncthingAPI:
    def __init__(self, base_url: str, api_key: str, tls_skip_verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tls_skip_verify = tls_skip_verify
        self.ssl_context = ssl._create_unverified_context() if tls_skip_verify else None

    def get_json(
        self, path: str, params: dict[str, Any] | None = None, timeout: float = 30.0
    ) -> Any:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)

        url = f"{self.base_url}{path}{query}"
        request = urllib.request.Request(
            url,
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=timeout, context=self.ssl_context
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Syncthing API HTTP {exc.code} for {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Syncthing API at {url}: {exc}") from exc

        if not raw:
            return None

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            text = raw[:500].decode("utf-8", errors="replace")
            raise RuntimeError(f"Invalid JSON from {url}: {text!r}") from exc


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def is_inside(parent: str, child: str) -> bool:
    try:
        return os.path.commonpath(
            [normalize_path(parent), normalize_path(child)]
        ) == normalize_path(parent)
    except ValueError:
        return False


def bool_from_xml_attr(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def api_url_from_gui_address(address: str | None, tls: bool) -> str | None:
    if address is None:
        return None
    value = address.strip()
    if not value:
        return None

    if "://" in value:
        return value.rstrip("/")

    if value.startswith(":"):
        value = "127.0.0.1" + value
    elif value.startswith("0.0.0.0:"):
        value = "127.0.0.1:" + value.split(":", 1)[1]
    elif value == "0.0.0.0":
        value = "127.0.0.1:8384"
    elif value.startswith("[::]:"):
        value = "[::1]:" + value.rsplit(":", 1)[1]
    elif value == "[::]":
        value = "[::1]:8384"

    scheme = "https" if tls else "http"
    return f"{scheme}://{value}".rstrip("/")


def flatpak_ids_to_probe(extra_ids: Iterable[str] | None = None) -> list[str]:
    ids: list[str] = []
    current_flatpak_id = os.environ.get("FLATPAK_ID")
    if current_flatpak_id:
        ids.append(current_flatpak_id)
    ids.extend(COMMON_SYNCTHING_FLATPAK_IDS)
    if extra_ids:
        ids.extend(extra_ids)

    deduped: list[str] = []
    seen: set[str] = set()
    for app_id in ids:
        app_id = app_id.strip()
        if app_id and app_id not in seen:
            seen.add(app_id)
            deduped.append(app_id)
    return deduped


def candidate_config_files(extra_flatpak_ids: Iterable[str] | None = None) -> list[Path]:
    home = Path.home()
    paths: list[Path] = []

    explicit_config = os.environ.get("SYNCTHING_CONFIG_FILE")
    if explicit_config:
        paths.append(Path(explicit_config).expanduser())

    if os.environ.get("STCONFDIR"):
        paths.append(Path(os.environ["STCONFDIR"]).expanduser() / "config.xml")
    if os.environ.get("STHOMEDIR"):
        paths.append(Path(os.environ["STHOMEDIR"]).expanduser() / "config.xml")

    if sys.platform == "darwin":
        paths.append(home / "Library/Application Support/Syncthing/config.xml")
    elif os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        app_data = os.environ.get("APPDATA")
        if local_app_data:
            paths.append(Path(local_app_data) / "Syncthing/config.xml")
        if app_data:
            paths.append(Path(app_data) / "Syncthing/config.xml")
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME")
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        xdg_data = os.environ.get("XDG_DATA_HOME")

        if xdg_state:
            paths.append(Path(xdg_state).expanduser() / "syncthing/config.xml")
        paths.append(home / ".local/state/syncthing/config.xml")

        if xdg_config:
            paths.append(Path(xdg_config).expanduser() / "syncthing/config.xml")
        paths.append(home / ".config/syncthing/config.xml")

        if xdg_data:
            paths.append(Path(xdg_data).expanduser() / "syncthing/config.xml")
        paths.append(home / ".local/share/syncthing/config.xml")

    for app_id in flatpak_ids_to_probe(extra_flatpak_ids):
        base = home / ".var/app" / app_id
        paths.extend(
            [
                base / "config/syncthing/config.xml",
                base / "data/syncthing/config.xml",
                base / ".config/syncthing/config.xml",
                base / ".local/state/syncthing/config.xml",
                base / ".local/share/syncthing/config.xml",
            ]
        )

    deduped_paths: list[Path] = []
    seen_paths: set[str] = set()
    for path in paths:
        expanded = path.expanduser()
        key = str(expanded)
        if key not in seen_paths:
            seen_paths.add(key)
            deduped_paths.append(expanded)

    return deduped_paths


def parse_syncthing_config(path: Path) -> SyncthingConfig | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    # Intentionally broad
    except Exception:
        return None

    gui = root.find("gui")
    if gui is None:
        return None

    api_key = gui.findtext("apikey")
    if not api_key or not api_key.strip():
        return None

    address = gui.findtext("address")
    tls = bool_from_xml_attr(gui.attrib.get("tls"), default=False)
    api_url = api_url_from_gui_address(address, tls)

    return SyncthingConfig(path=path, api_key=api_key.strip(), api_url=api_url)


def discover_syncthing_config(
    explicit_config: Path | None = None,
    extra_flatpak_ids: Iterable[str] | None = None,
) -> SyncthingConfig | None:
    if explicit_config is not None:
        parsed = parse_syncthing_config(explicit_config.expanduser())
        if parsed:
            return parsed
        return None

    for path in candidate_config_files(extra_flatpak_ids):
        parsed = parse_syncthing_config(path)
        if parsed:
            return parsed
    return None


def resolve_api_credentials(
    explicit_url: str | None = None,
    explicit_key: str | None = None,
    explicit_config: Path | None = None,
) -> tuple[str, str, SyncthingConfig | None]:
    parsed_config = discover_syncthing_config(explicit_config)

    api_key = explicit_key or os.environ.get("SYNCTHING_API_KEY")
    if not api_key and parsed_config:
        api_key = parsed_config.api_key

    if not api_key:
        raise RuntimeError("No Syncthing API key found.")

    api_url = explicit_url or os.environ.get("SYNCTHING_API_URL")
    if not api_url and parsed_config and parsed_config.api_url:
        api_url = parsed_config.api_url
    if not api_url:
        api_url = DEFAULT_API_URL

    return api_url.rstrip("/"), api_key.strip(), parsed_config


def get_folders(api: SyncthingAPI) -> list[dict[str, Any]]:
    folders = api.get_json("/rest/config/folders", timeout=10)
    if not isinstance(folders, list):
        raise RuntimeError(f"Unexpected folders structure: {folders}")
    return folders


def folder_label(folder: dict[str, Any]) -> str:
    label = folder.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    folder_id = folder.get("id")
    return str(folder_id) if folder_id else ""


def folder_shared_device_ids(folder: dict[str, Any]) -> tuple[str, ...]:
    devices = folder.get("devices")
    if not isinstance(devices, list):
        return ()
    ids: list[str] = []
    for device in devices:
        if isinstance(device, dict):
            device_id = device.get("deviceID")
            if device_id:
                ids.append(str(device_id))
    return tuple(ids)


def folder_selection_from_config(
    folder: dict[str, Any],
    *,
    selected_path: str | None = None,
    normalized_folder_path: str | None = None,
) -> FolderSelection:
    raw_path = folder.get("path")
    path = (
        normalized_folder_path
        if normalized_folder_path is not None
        else (str(raw_path) if raw_path else None)
    )
    fs_watcher_enabled = folder.get("fsWatcherEnabled")
    if isinstance(fs_watcher_enabled, bool):
        watcher = fs_watcher_enabled
    else:
        watcher = None
    rescan_interval = folder.get("rescanIntervalS")
    try:
        rescan_interval_seconds = int(rescan_interval) if rescan_interval is not None else None
    except (TypeError, ValueError):
        rescan_interval_seconds = None

    return FolderSelection(
        folder_id=str(folder["id"]),
        label=folder_label(folder),
        path=path,
        selected_path=selected_path,
        folder_type=str(folder.get("type") or "") or None,
        paused=bool(folder.get("paused")),
        fs_watcher_enabled=watcher,
        rescan_interval_seconds=rescan_interval_seconds,
        shared_device_ids=folder_shared_device_ids(folder),
    )


def resolve_folder_by_id(api: SyncthingAPI, folder_id: str) -> FolderSelection:
    for folder in get_folders(api):
        if folder.get("id") == folder_id:
            return folder_selection_from_config(folder, selected_path=None)
    raise RuntimeError(f"Unknown Syncthing folder ID {folder_id}")


def resolve_folder_by_path(api: SyncthingAPI, selected_path: str) -> FolderSelection:
    selected_abs = normalize_path(selected_path)
    candidates: list[tuple[int, dict[str, Any], str]] = []

    for folder in get_folders(api):
        folder_id = folder.get("id")
        folder_path = folder.get("path")
        if not folder_id or not folder_path:
            continue
        expanded_folder_path = normalize_path(str(folder_path))
        if is_inside(expanded_folder_path, selected_abs):
            candidates.append((len(expanded_folder_path), folder, expanded_folder_path))

    if not candidates:
        raise RuntimeError(f"No configured Syncthing folder contains path {selected_path}")

    _, folder, normalized_folder_path = max(candidates, key=lambda item: item[0])
    return folder_selection_from_config(
        folder,
        selected_path=selected_abs,
        normalized_folder_path=normalized_folder_path,
    )


def get_folder_status(api: SyncthingAPI, folder_id: str) -> dict[str, Any]:
    status = api.get_json("/rest/db/status", params={"folder": folder_id}, timeout=10)
    if not isinstance(status, dict):
        raise RuntimeError(f"Unexpected status response for {folder_id}: {status}")
    return status


def int_field(data: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(data.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def parse_folder_runtime(data: dict[str, Any]) -> FolderRuntime:
    raw_remote_sequence = data.get("remoteSequence")
    remote_sequence: dict[str, int] = {}
    if isinstance(raw_remote_sequence, dict):
        for device_id, sequence in raw_remote_sequence.items():
            try:
                remote_sequence[str(device_id)] = int(sequence or 0)
            except (TypeError, ValueError):
                remote_sequence[str(device_id)] = 0
    return FolderRuntime(
        sequence=int_field(data, "sequence", int_field(data, "version", 0)),
        remote_sequence=remote_sequence,
        need_bytes=int_field(data, "needBytes", 0),
        need_total_items=int_field(data, "needTotalItems", 0),
        need_deletes=int_field(data, "needDeletes", 0),
        global_bytes=int_field(data, "globalBytes", 0),
        local_bytes=int_field(data, "localBytes", 0),
        in_sync_bytes=int_field(data, "inSyncBytes", 0),
        pull_errors=int_field(data, "pullErrors", 0),
        watch_error=str(data.get("watchError") or ""),
    )


def get_initial_folder_state_and_runtime(
    api: SyncthingAPI, folder_id: str
) -> tuple[str, FolderRuntime]:
    try:
        status = get_folder_status(api, folder_id)
        state = status.get("state")
        return (str(state) if state else "unknown"), parse_folder_runtime(status)
    # Intentionally broad
    except Exception:
        return "unknown", FolderRuntime()


def get_event_cursor(api: SyncthingAPI) -> int:
    events = api.get_json(
        "/rest/events", params={"since": 0, "limit": 1000, "timeout": 1}, timeout=5
    )
    if not isinstance(events, list):
        return 0
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


def get_connection_totals(api: SyncthingAPI) -> tuple[int, int]:
    data = api.get_json("/rest/system/connections", timeout=10)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected system connections response: {data}")
    total = data.get("total")
    if isinstance(total, dict):
        return int(total.get("inBytesTotal", 0) or 0), int(total.get("outBytesTotal", 0) or 0)
    return 0, 0


def compute_rates(
    previous_totals: tuple[int, int] | None,
    previous_time: float | None,
    current_totals: tuple[int, int],
    current_time: float,
) -> ConnectionRates:
    if previous_totals is None or previous_time is None:
        return ConnectionRates(in_bytes_per_second=0.0, out_bytes_per_second=0.0)
    elapsed = max(0.001, current_time - previous_time)
    in_delta = max(0, current_totals[0] - previous_totals[0])
    out_delta = max(0, current_totals[1] - previous_totals[1])
    return ConnectionRates(
        in_bytes_per_second=in_delta / elapsed,
        out_bytes_per_second=out_delta / elapsed,
    )


def prune_remote_progress(
    remote_progress: dict[str, RemoteProgress], active_window: float, now: float
) -> dict[str, RemoteProgress]:
    return {
        device_id: progress
        for device_id, progress in remote_progress.items()
        if now - progress.last_seen_monotonic <= active_window
    }


def prune_local_activity(
    activity: LocalActivity, active_window: float, now: float
) -> LocalActivity:
    active_items = activity.active_items or {}
    activity.active_items = {
        item: last_seen
        for item, last_seen in active_items.items()
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
    return activity


def has_pending_remote_ack(
    runtime: FolderRuntime, shared_device_ids: tuple[str, ...]
) -> tuple[bool, int]:
    if runtime.sequence <= 0 or not runtime.remote_sequence:
        return False, 0
    device_ids = shared_device_ids or tuple(runtime.remote_sequence.keys())
    lagging = 0
    for device_id in device_ids:
        remote_seq = runtime.remote_sequence.get(device_id)
        if remote_seq is None:
            continue
        if remote_seq < runtime.sequence:
            lagging += 1
    return lagging > 0, lagging


def compute_activity_status(
    folder_state: str,
    remote_progress: dict[str, RemoteProgress],
    local_activity: LocalActivity,
    runtime: FolderRuntime,
    rates: ConnectionRates,
    min_rate_bytes_per_second: float,
    shared_device_ids: tuple[str, ...],
    active_window_seconds: float,
    now: float,
) -> ActivityStatus:
    normalized_state = folder_state or "unknown"
    active_items = local_activity.active_items or {}

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

    pending_remote_ack, lagging_remote_devices = has_pending_remote_ack(runtime, shared_device_ids)
    aggregate_downloading = rates.in_bytes_per_second >= min_rate_bytes_per_second
    aggregate_uploading = rates.out_bytes_per_second >= min_rate_bytes_per_second

    receive_needed = (
        runtime.need_bytes > 0 or runtime.need_total_items > 0 or runtime.need_deletes > 0
    )
    preparing = normalized_state in PREPARING_STATES
    scanning = normalized_state in SCANNING_STATES or scan_progress_recent

    item_finished_recent = (
        local_activity.last_item_finished_monotonic > 0
        and now - local_activity.last_item_finished_monotonic <= 2.0
    )

    recent_folder_mutation = (
        local_change_recent
        or local_index_recent
        or sequence_change_recent
        or bool(active_items)
        or item_finished_recent
    )

    downloading = (
        normalized_state == "syncing"
        or local_activity.active_download_files > 0
        or bool(active_items)
        or (recent_folder_mutation and aggregate_downloading and normalized_state != "idle")
    )

    uploading = bool(remote_progress) or (recent_folder_mutation and aggregate_uploading)

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
        and not pending_remote_ack
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
        aggregate_downloading=aggregate_downloading,
        aggregate_uploading=aggregate_uploading,
        active_remote_devices=len(remote_progress),
        active_remote_files=sum(p.file_count for p in remote_progress.values()),
        active_download_files=local_activity.active_download_files,
        active_items=len(active_items),
        local_change_recent=local_change_recent,
        local_index_recent=local_index_recent,
        sequence_change_recent=sequence_change_recent,
        scan_progress_recent=scan_progress_recent,
        pending_remote_ack=pending_remote_ack,
        lagging_remote_devices=lagging_remote_devices,
        runtime=runtime,
        rates=rates,
    )


def process_event(
    event: dict[str, Any],
    folder: FolderSelection,
    folder_state: str,
    runtime: FolderRuntime,
    remote_progress: dict[str, RemoteProgress],
    local_activity: LocalActivity,
    now: float,
) -> tuple[str, FolderRuntime, dict[str, RemoteProgress], LocalActivity, bool]:
    event_type = event.get("type")
    data = event.get("data") or {}
    config_changed = False

    if local_activity.active_items is None:
        local_activity.active_items = {}

    if not isinstance(data, dict):
        return folder_state, runtime, remote_progress, local_activity, config_changed

    if event_type == "StateChanged" and data.get("folder") == folder.folder_id:
        new_state = str(data.get("to") or folder_state)
        folder_state = new_state
    elif event_type == "FolderSummary" and data.get("folder") == folder.folder_id:
        summary = data.get("summary") or {}
        if isinstance(summary, dict):
            if summary.get("state"):
                folder_state = str(summary["state"])
            runtime = parse_folder_runtime(summary)
    elif event_type == "FolderScanProgress" and data.get("folder") == folder.folder_id:
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
    elif event_type == "RemoteDownloadProgress" and data.get("folder") == folder.folder_id:
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
    elif event_type == "ItemStarted" and data.get("folder") == folder.folder_id:
        item = str(data.get("item") or "unknown")
        local_activity.active_items[item] = now
    elif event_type == "ItemFinished" and data.get("folder") == folder.folder_id:
        item = str(data.get("item") or "unknown")
        local_activity.active_items.pop(item, None)
        local_activity.last_item_finished_monotonic = now
    elif event_type == "LocalChangeDetected" and data.get("folder") == folder.folder_id:
        local_activity.last_local_change_monotonic = now
    elif event_type == "LocalIndexUpdated" and data.get("folder") == folder.folder_id:
        local_activity.last_local_index_monotonic = now
        sequence = int_field(data, "sequence", int_field(data, "version", runtime.sequence))
        previous_sequence = runtime.sequence
        if sequence and sequence != previous_sequence:
            local_activity.last_sequence_change_monotonic = now
            local_activity.sequence_change_from = previous_sequence
            local_activity.sequence_change_to = sequence
        runtime = FolderRuntime(
            sequence=sequence or runtime.sequence,
            remote_sequence=runtime.remote_sequence,
            need_bytes=runtime.need_bytes,
            need_total_items=runtime.need_total_items,
            need_deletes=runtime.need_deletes,
            global_bytes=runtime.global_bytes,
            local_bytes=runtime.local_bytes,
            in_sync_bytes=runtime.in_sync_bytes,
            pull_errors=runtime.pull_errors,
            watch_error=runtime.watch_error,
        )
    elif event_type == "FolderPaused" and data.get("folder") == folder.folder_id:
        folder_state = "paused"
    elif event_type == "FolderResumed" and data.get("folder") == folder.folder_id:
        folder_state = "unknown"
    elif event_type == "ConfigSaved":
        config_changed = True

    return folder_state, runtime, remote_progress, local_activity, config_changed


# ==========================================
# Watch Manager & Threads
# ==========================================


class SyncthingWatch:
    def __init__(
        self,
        watch_id: str,
        phase: str,
        game_name: str | None,
        app_id: str | None,
        folder: FolderSelection,
        api: SyncthingAPI,
    ) -> None:
        self.watch_id = watch_id
        self.phase = phase
        self.game_name = game_name
        self.app_id = app_id
        self.folder = folder
        self.api = api
        self.started_at = time.time()
        self.stop_event = threading.Event()
        self.latest_sample: dict[str, Any] = {}
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run, name=f"syncthing-watch-{self.watch_id}", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def _run(self) -> None:
        try:
            folder_state, runtime = get_initial_folder_state_and_runtime(
                self.api, self.folder.folder_id
            )
            cursor = get_event_cursor(self.api)
        # Intentionally broad
        except Exception as exc:
            logger.warning("Failed to initialize watch thread: %s", exc)
            return

        previous_totals: tuple[int, int] | None = None
        previous_totals_time: float | None = None
        rates = ConnectionRates(in_bytes_per_second=0.0, out_bytes_per_second=0.0)
        remote_progress: dict[str, RemoteProgress] = {}
        local_activity = LocalActivity(active_items={})

        last_connection_poll_time = 0.0
        last_folder_status_poll_time = 0.0

        poll_interval = DEFAULT_POLL_INTERVAL_SECONDS
        status_poll_interval = DEFAULT_STATUS_POLL_INTERVAL_SECONDS
        event_timeout = DEFAULT_EVENT_TIMEOUT_SECONDS
        active_window = DEFAULT_ACTIVE_WINDOW_SECONDS
        min_rate = DEFAULT_MIN_RATE_BYTES_PER_SECOND

        while not self.stop_event.is_set():
            now = time.monotonic()

            if now - last_connection_poll_time >= poll_interval:
                try:
                    current_totals = get_connection_totals(self.api)
                    rates = compute_rates(
                        previous_totals, previous_totals_time, current_totals, now
                    )
                    previous_totals = current_totals
                    previous_totals_time = now
                # Intentionally broad
                except Exception:
                    pass
                last_connection_poll_time = now

            if now - last_folder_status_poll_time >= status_poll_interval:
                try:
                    current_status = get_folder_status(self.api, self.folder.folder_id)
                    folder_state = str(current_status.get("state") or folder_state)
                    new_runtime = parse_folder_runtime(current_status)
                    if (
                        runtime.sequence
                        and new_runtime.sequence
                        and new_runtime.sequence != runtime.sequence
                    ):
                        local_activity.last_sequence_change_monotonic = now
                        local_activity.sequence_change_from = runtime.sequence
                        local_activity.sequence_change_to = new_runtime.sequence
                        local_activity.last_local_index_monotonic = now
                    runtime = new_runtime
                # Intentionally broad
                except Exception:
                    pass
                last_folder_status_poll_time = now

            remote_progress = prune_remote_progress(remote_progress, active_window, now)
            local_activity = prune_local_activity(local_activity, active_window, now)

            try:
                status = compute_activity_status(
                    folder_state=folder_state,
                    remote_progress=remote_progress,
                    local_activity=local_activity,
                    runtime=runtime,
                    rates=rates,
                    min_rate_bytes_per_second=min_rate,
                    shared_device_ids=self.folder.shared_device_ids,
                    active_window_seconds=active_window,
                    now=now,
                )
                self.latest_sample = {
                    "status": "activity",
                    "watch_id": self.watch_id,
                    "sample": {
                        "status": status.status,
                        "folder_id": self.folder.folder_id,
                        "label": self.folder.label,
                        "folder_state": status.folder_state,
                        "active_transfer": status.active_transfer,
                        "update_in_progress": status.update_in_progress,
                        "settled": status.settled,
                        "downloading": status.downloading,
                        "uploading": status.uploading,
                        "receive_needed": status.receive_needed,
                        "need_bytes": status.runtime.need_bytes,
                        "need_items": status.runtime.need_total_items,
                        "need_deletes": status.runtime.need_deletes,
                        "sequence": status.runtime.sequence,
                        "pending_remote_ack": status.pending_remote_ack,
                        "lagging_remote_devices": status.lagging_remote_devices,
                        "timestamp_unix": time.time(),
                    },
                }
            # Intentionally broad
            except Exception as exc:
                self.latest_sample = {
                    "status": "failed",
                    "reason": "computation_failed",
                    "message": str(exc),
                }

            # Poll events
            try:
                events = get_events(self.api, cursor, event_timeout)
                if events:
                    config_changed = False
                    for event in events:
                        cursor = max(cursor, int(event.get("id", cursor)))
                        (
                            folder_state,
                            runtime,
                            remote_progress,
                            local_activity,
                            event_config_changed,
                        ) = process_event(
                            event=event,
                            folder=self.folder,
                            folder_state=folder_state,
                            runtime=runtime,
                            remote_progress=remote_progress,
                            local_activity=local_activity,
                            now=time.monotonic(),
                        )
                        config_changed = config_changed or event_config_changed
                    if config_changed:
                        folder_state, runtime = get_initial_folder_state_and_runtime(
                            self.api, self.folder.folder_id
                        )
            # Intentionally broad
            except Exception:
                time.sleep(0.5)


class SyncthingWatchManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.watches: dict[str, SyncthingWatch] = {}

    def start_watch(
        self,
        phase: str,
        game_name: str | None,
        app_id: str | None,
        backup_path: str | None,
    ) -> dict[str, Any]:
        if not backup_path or backup_path == "unknown":
            return {
                "status": "skipped",
                "reason": "backup_path_unavailable",
                "message": "Ludusavi backupPath is not configured.",
            }

        with self.lock:
            # Stop existing watch with the same signature
            for old_id, old_watch in list(self.watches.items()):
                if (
                    old_watch.phase == phase
                    and old_watch.game_name == game_name
                    and old_watch.app_id == app_id
                ):
                    old_watch.stop()
                    self.watches.pop(old_id, None)

            # Discover Syncthing
            try:
                api_url, api_key, _ = resolve_api_credentials()
                api = SyncthingAPI(api_url, api_key)
            # Intentionally broad
            except Exception as exc:
                return {"status": "skipped", "reason": "api_unavailable", "message": str(exc)}

            # Resolve containing folder
            try:
                folder = resolve_folder_by_path(api, backup_path)
            # Intentionally broad
            except Exception as exc:
                # If we couldn't connect, it could be flatpak id config or API offline.
                # If API worked but path didn't resolve:
                if "No configured Syncthing folder contains path" in str(exc):
                    return {"status": "skipped", "reason": "folder_not_found", "message": str(exc)}
                return {"status": "skipped", "reason": "api_unavailable", "message": str(exc)}

            watch_id = str(uuid.uuid4())
            watch = SyncthingWatch(watch_id, phase, game_name, app_id, folder, api)
            watch.start()

            self.watches[watch_id] = watch

            return {
                "status": "watching",
                "watch_id": watch_id,
                "folder_id": folder.folder_id,
                "label": folder.label,
                "path": folder.path,
            }

    def poll_watch(self, watch_id: str) -> dict[str, Any]:
        with self.lock:
            watch = self.watches.get(watch_id)
            if not watch:
                return {"status": "stopped", "watch_id": watch_id}
            return dict(
                watch.latest_sample or {"status": "activity", "watch_id": watch_id, "sample": {}}
            )

    def stop_watch(self, watch_id: str) -> dict[str, Any]:
        with self.lock:
            watch = self.watches.pop(watch_id, None)
            if watch:
                watch.stop()
                return {"status": "stopped", "watch_id": watch_id}
            return {"status": "stopped", "watch_id": watch_id}

    def stop_all(self) -> None:
        with self.lock:
            for watch in self.watches.values():
                watch.stop()
            self.watches.clear()
