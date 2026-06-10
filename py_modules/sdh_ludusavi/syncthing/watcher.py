from __future__ import annotations

import logging
import time
import uuid
import threading
from typing import Any

from .api import SyncthingAPI
from .config import SyncthingNotConfiguredError, resolve_api_credentials
from .folders import resolve_folder_by_path
from ._types import (
    FolderSelection,
    FolderRuntime,
    RemoteProgress,
    LocalActivity,
    ConnectionRates,
    ConnectionSnapshot,
    DEFAULT_EVENT_TIMEOUT_SECONDS,
    DEFAULT_ACTIVE_WINDOW_SECONDS,
    DEFAULT_MIN_RATE_BYTES_PER_SECOND,
)
from .activity import (
    get_initial_folder_state_and_runtime,
    get_event_cursor,
    get_events,
    get_connection_snapshot,
    get_my_device_id,
    get_folder_status,
    compute_rates,
    prune_remote_progress,
    prune_local_activity,
    compute_activity_status,
    process_event,
    _serialize_sample,
    parse_folder_runtime,
)

logger = logging.getLogger(__name__)

DEFAULT_FS_WATCHER_DELAY_SECONDS = 10
DEFAULT_RESCAN_INTERVAL_SECONDS = 3600
MIN_DETECTION_GRACE_SECONDS = 30
MAX_DETECTION_GRACE_SECONDS = 120
DETECTION_GRACE_MARGIN_SECONDS = 20


def detection_grace_ms(folder: FolderSelection) -> int:
    if folder.fs_watcher_enabled is False:
        base_seconds = folder.rescan_interval_seconds or DEFAULT_RESCAN_INTERVAL_SECONDS
    else:
        base_seconds = folder.fs_watcher_delay_seconds or DEFAULT_FS_WATCHER_DELAY_SECONDS
    grace_seconds = max(
        MIN_DETECTION_GRACE_SECONDS,
        min(MAX_DETECTION_GRACE_SECONDS, base_seconds + DETECTION_GRACE_MARGIN_SECONDS),
    )
    return grace_seconds * 1000


class SyncthingWatch:
    def __init__(
        self,
        watch_id: str,
        phase: str,
        game_name: str | None,
        app_id: str | None,
        folder: FolderSelection,
        api: SyncthingAPI,
        initial_snapshot: ConnectionSnapshot | None = None,
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
        self.cursor = 0
        self.folder_state = "unknown"
        self.runtime = FolderRuntime()
        self.remote_progress: dict[str, RemoteProgress] = {}
        self.local_activity = LocalActivity(active_items={})
        self.rates = ConnectionRates(0.0, 0.0)
        self.previous_totals: tuple[int, int] | None = None
        self.previous_totals_time: float | None = None
        self.connected_devices: frozenset[str] = (
            initial_snapshot.connected_devices if initial_snapshot else frozenset()
        )

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
            self.folder_state, self.runtime = get_initial_folder_state_and_runtime(
                self.api, self.folder.folder_id, strict=True
            )
            self.cursor = get_event_cursor(self.api)
        except Exception as exc:
            logger.warning("Failed to initialize watch thread: %s", exc)
            self.latest_sample = {
                "status": "failed",
                "reason": "watch_initialization_failed",
                "message": str(exc),
            }
            return

        # Compute and publish a baseline sample immediately
        self._tick_sample(time.monotonic())

        while not self.stop_event.is_set():
            self._tick(time.monotonic())

    def _tick(self, now: float) -> None:
        # 1. Capture a monotonic timestamp for connection and folder polling.
        now_pre = now

        # 2. Poll connection totals and compute rates.
        self._tick_connections(now_pre)

        # 2b. Stop with a terminal result if every relevant peer disconnected.
        if self.folder.device_ids and not set(self.folder.device_ids) & self.connected_devices:
            logger.info(
                "Syncthing watch %s stopping: no connected peers (phase=%s configured=%d)",
                self.watch_id,
                self.phase,
                len(self.folder.device_ids),
            )
            self.latest_sample = {
                "status": "failed",
                "reason": "no_connected_peers",
                "message": "All Syncthing devices configured for the backup folder are disconnected.",
            }
            self.stop_event.set()
            return

        # 3. Poll current folder status and detect sequence changes.
        self._tick_folder_status(now_pre)

        # 4. Poll/process events.
        self._tick_events()

        # 5. Capture a new monotonic timestamp after the event request returns.
        now_post = time.monotonic()

        # 6. Prune remote and local activity using the post-event timestamp.
        self.remote_progress = prune_remote_progress(
            self.remote_progress,
            DEFAULT_ACTIVE_WINDOW_SECONDS,
            now_post,
        )
        prune_local_activity(self.local_activity, DEFAULT_ACTIVE_WINDOW_SECONDS, now_post)

        # 7. Compute and atomically assign the latest sample using the post-event state.
        self._tick_sample(now_post)

    def _tick_connections(self, now: float) -> None:
        try:
            snapshot = get_connection_snapshot(self.api)
            current_totals = (snapshot.in_bytes_total, snapshot.out_bytes_total)
            self.rates = compute_rates(
                self.previous_totals,
                self.previous_totals_time,
                current_totals,
                now,
            )
            self.previous_totals = current_totals
            self.previous_totals_time = now
            self.connected_devices = snapshot.connected_devices
        # Intentionally broad; keeps the last known connected-device set
        except Exception:
            self.rates = ConnectionRates(0.0, 0.0)

    def _tick_folder_status(self, now: float) -> None:
        try:
            current_status = get_folder_status(self.api, self.folder.folder_id)
            new_state = str(current_status.get("state") or self.folder_state)
            new_runtime = parse_folder_runtime(current_status)
            if (
                self.runtime.sequence
                and new_runtime.sequence
                and new_runtime.sequence != self.runtime.sequence
            ):
                self.local_activity.last_sequence_change_monotonic = now
                self.local_activity.sequence_change_from = self.runtime.sequence
                self.local_activity.sequence_change_to = new_runtime.sequence
                self.local_activity.last_local_index_monotonic = now
            self.folder_state = new_state
            self.runtime = new_runtime
        # Intentionally broad
        except Exception:
            return

    def _tick_sample(self, now: float) -> None:
        try:
            status = compute_activity_status(
                folder_state=self.folder_state,
                remote_progress=self.remote_progress,
                local_activity=self.local_activity,
                runtime=self.runtime,
                rates=self.rates,
                min_rate_bytes_per_second=DEFAULT_MIN_RATE_BYTES_PER_SECOND,
                active_window_seconds=DEFAULT_ACTIVE_WINDOW_SECONDS,
                now=now,
            )
            self.latest_sample = _serialize_sample(self.watch_id, status)
        # Intentionally broad
        except Exception as exc:
            self.latest_sample = {
                "status": "failed",
                "reason": "computation_failed",
                "message": str(exc),
            }

    def _tick_events(self) -> None:
        try:
            events = get_events(self.api, self.cursor, DEFAULT_EVENT_TIMEOUT_SECONDS)
            if events:
                config_changed = False
                for event in events:
                    self.cursor = max(self.cursor, int(event.get("id", self.cursor)))
                    (
                        self.folder_state,
                        self.runtime,
                        self.remote_progress,
                        self.local_activity,
                        event_config_changed,
                    ) = process_event(
                        event=event,
                        folder=self.folder,
                        folder_state=self.folder_state,
                        runtime=self.runtime,
                        remote_progress=self.remote_progress,
                        local_activity=self.local_activity,
                        now=time.monotonic(),
                    )
                    config_changed = config_changed or event_config_changed
                if config_changed:
                    self.folder_state, self.runtime = get_initial_folder_state_and_runtime(
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
            except SyncthingNotConfiguredError as exc:
                return {"status": "skipped", "reason": "not_configured", "message": str(exc)}
            # Intentionally broad
            except Exception as exc:
                return {"status": "skipped", "reason": "api_unavailable", "message": str(exc)}

            # Identify the local device so configured folder devices are remote-only.
            # Raw API errors stay in backend logs; they can echo response payloads
            # holding device IDs, which must never travel through RPC.
            try:
                my_device_id = get_my_device_id(api)
            # Intentionally broad
            except Exception as exc:
                logger.warning("Syncthing system status probe failed: %s", exc)
                return {
                    "status": "skipped",
                    "reason": "api_unavailable",
                    "message": "Syncthing system status query failed.",
                }

            # Resolve containing folder
            try:
                folder = resolve_folder_by_path(api, backup_path, local_device_id=my_device_id)
            # Intentionally broad
            except Exception as exc:
                if "No configured Syncthing folder contains path" in str(exc):
                    return {"status": "skipped", "reason": "folder_not_found", "message": str(exc)}
                return {"status": "skipped", "reason": "api_unavailable", "message": str(exc)}

            if not folder.device_ids:
                return {
                    "status": "skipped",
                    "reason": "folder_not_shared",
                    "message": "The Syncthing folder has no configured remote devices.",
                }

            # Require at least one connected peer that shares the matched folder
            try:
                snapshot = get_connection_snapshot(api)
            # Intentionally broad; sanitized for RPC like the system status probe
            except Exception as exc:
                logger.warning("Syncthing connections probe failed: %s", exc)
                return {
                    "status": "skipped",
                    "reason": "api_unavailable",
                    "message": "Syncthing connections query failed.",
                }

            connected_count = len(set(folder.device_ids) & snapshot.connected_devices)
            logger.info(
                "Syncthing peer availability: phase=%s configured=%d connected=%d",
                phase,
                len(folder.device_ids),
                connected_count,
            )
            if connected_count == 0:
                return {
                    "status": "skipped",
                    "reason": "no_connected_peers",
                    "message": (
                        f"None of the {len(folder.device_ids)} configured devices "
                        "for the backup folder are connected."
                    ),
                }

            watch_id = str(uuid.uuid4())
            watch = SyncthingWatch(
                watch_id, phase, game_name, app_id, folder, api, initial_snapshot=snapshot
            )
            watch.start()

            self.watches[watch_id] = watch

            return {
                "status": "watching",
                "watch_id": watch_id,
                "folder_id": folder.folder_id,
                "label": folder.label,
                "path": folder.path,
                "detection_grace_ms": detection_grace_ms(folder),
            }

    def poll_watch(self, watch_id: str) -> dict[str, Any]:
        import copy

        with self.lock:
            watch = self.watches.get(watch_id)
            if not watch:
                return {"status": "stopped", "watch_id": watch_id}
            sample = watch.latest_sample
            if sample:
                return copy.deepcopy(sample)
            return {"status": "activity", "watch_id": watch_id, "sample": {}}

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
