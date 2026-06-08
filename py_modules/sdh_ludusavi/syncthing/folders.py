from __future__ import annotations

import logging
from typing import Any

from .api import SyncthingAPI
from ._types import FolderSelection, normalize_path, is_inside

logger = logging.getLogger(__name__)


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
    fs_watcher_delay = folder.get("fsWatcherDelayS")
    try:
        fs_watcher_delay_seconds = int(fs_watcher_delay) if fs_watcher_delay is not None else None
    except (TypeError, ValueError):
        fs_watcher_delay_seconds = None
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
        fs_watcher_delay_seconds=fs_watcher_delay_seconds,
        rescan_interval_seconds=rescan_interval_seconds,
    )


def resolve_folder_by_id(api: SyncthingAPI, folder_id: str) -> FolderSelection:
    for folder in get_folders(api):
        if folder.get("id") == folder_id:
            return folder_selection_from_config(folder, selected_path=None)
    raise RuntimeError(f"Unknown Syncthing folder ID {folder_id}")


def resolve_folder_by_path(api: SyncthingAPI, selected_path: str) -> FolderSelection:
    _norm_selected = normalize_path(selected_path)
    candidates: list[tuple[int, dict[str, Any], str]] = []

    for folder in get_folders(api):
        folder_id = folder.get("id")
        folder_path = folder.get("path")
        if not folder_id or not folder_path:
            continue
        expanded_folder_path = normalize_path(str(folder_path))
        if is_inside(expanded_folder_path, _norm_selected):
            candidates.append((len(expanded_folder_path), folder, expanded_folder_path))

    if not candidates:
        raise RuntimeError(f"No configured Syncthing folder contains path {selected_path}")

    _, folder_data, _norm_folder_path = max(candidates, key=lambda item: item[0])
    return folder_selection_from_config(
        folder_data,
        selected_path=_norm_selected,
        normalized_folder_path=_norm_folder_path,
    )
