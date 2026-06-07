from __future__ import annotations

import logging
import time
import uuid
import threading
from typing import Any

from .api import SyncthingAPI
from .config import resolve_api_credentials
from .folders import resolve_folder_by_path
from ._types import (
    FolderSelection,
    FolderRuntime,
    RemoteProgress,
    LocalActivity,
    ConnectionRates,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    DEFAULT_EVENT_TIMEOUT_SECONDS,
    DEFAULT_ACTIVE_WINDOW_SECONDS,
    DEFAULT_MIN_RATE_BYTES_PER_SECOND,
)
from .activity import (
    get_initial_folder_state_and_runtime,
    get_event_cursor,
    get_events,
    get_connection_totals,
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
        except Exception as exc:
            logger.warning("Failed to initialize watch thread: %s", exc)
            self.latest_sample = {
                "status": "failed",
                "reason": "watch_initialization_failed",
                "message": str(exc),
            }
            return

        previous_totals: tuple[int, int] | None = None
        previous_totals_time: float | None = None
        rates = ConnectionRates(in_bytes_per_second=0.0, out_bytes_per_second=0.0)
        remote_progress: dict[str, RemoteProgress] = {}
        local_activity = LocalActivity(active_items={})

        poll_interval = DEFAULT_POLL_INTERVAL_SECONDS
        status_poll_interval = DEFAULT_STATUS_POLL_INTERVAL_SECONDS
        event_timeout = DEFAULT_EVENT_TIMEOUT_SECONDS
        active_window = DEFAULT_ACTIVE_WINDOW_SECONDS
        min_rate = DEFAULT_MIN_RATE_BYTES_PER_SECOND

        # Compute and publish a baseline sample immediately
        self._tick_sample(
            now=time.monotonic(),
            folder_state=folder_state,
            runtime=runtime,
            remote_progress=remote_progress,
            local_activity=local_activity,
            rates=rates,
            active_window=active_window,
            min_rate=min_rate,
        )

        while not self.stop_event.is_set():
            (
                previous_totals,
                previous_totals_time,
                rates,
                remote_progress,
                folder_state,
                runtime,
                cursor,
            ) = self._tick(
                now=time.monotonic(),
                cursor=cursor,
                folder_state=folder_state,
                runtime=runtime,
                remote_progress=remote_progress,
                local_activity=local_activity,
                rates=rates,
                previous_totals=previous_totals,
                previous_totals_time=previous_totals_time,
                poll_interval=poll_interval,
                status_poll_interval=status_poll_interval,
                event_timeout=event_timeout,
                active_window=active_window,
                min_rate=min_rate,
            )

    def _tick(
        self,
        now: float,
        cursor: int,
        folder_state: str,
        runtime: FolderRuntime,
        remote_progress: dict[str, RemoteProgress],
        local_activity: LocalActivity,
        rates: ConnectionRates,
        previous_totals: tuple[int, int] | None,
        previous_totals_time: float | None,
        poll_interval: float,
        status_poll_interval: float,
        event_timeout: float,
        active_window: float,
        min_rate: float,
    ) -> tuple[
        tuple[int, int] | None,
        float | None,
        ConnectionRates,
        dict[str, RemoteProgress],
        str,
        FolderRuntime,
        int,
    ]:
        # 1. Capture a monotonic timestamp for connection and folder polling.
        now_pre = time.monotonic()

        # 2. Poll connection totals and compute rates.
        previous_totals, previous_totals_time, rates = self._tick_connections(
            now_pre, previous_totals, previous_totals_time
        )

        # 3. Poll current folder status and detect sequence changes.
        folder_state, runtime = self._tick_folder_status(
            now_pre, folder_state, runtime, local_activity
        )

        # 4. Poll/process events.
        cursor, folder_state, runtime = self._tick_events(
            cursor,
            folder_state,
            runtime,
            remote_progress,
            local_activity,
            event_timeout,
        )

        # 5. Capture a new monotonic timestamp after the event request returns.
        now_post = time.monotonic()

        # 6. Prune remote and local activity using the post-event timestamp.
        remote_progress = prune_remote_progress(remote_progress, active_window, now_post)
        prune_local_activity(local_activity, active_window, now_post)

        # 7. Compute and atomically assign the latest sample using the post-event state.
        self._tick_sample(
            now_post,
            folder_state,
            runtime,
            remote_progress,
            local_activity,
            rates,
            active_window,
            min_rate,
        )

        # 8. Return updated calculation state.
        return (
            previous_totals,
            previous_totals_time,
            rates,
            remote_progress,
            folder_state,
            runtime,
            cursor,
        )

    def _tick_connections(
        self,
        now: float,
        previous_totals: tuple[int, int] | None,
        previous_totals_time: float | None,
    ) -> tuple[tuple[int, int] | None, float | None, ConnectionRates]:
        try:
            current_totals = get_connection_totals(self.api)
            new_rates = compute_rates(previous_totals, previous_totals_time, current_totals, now)
            return current_totals, now, new_rates
        # Intentionally broad
        except Exception:
            return previous_totals, previous_totals_time, ConnectionRates(0.0, 0.0)

    def _tick_folder_status(
        self,
        now: float,
        folder_state: str,
        runtime: FolderRuntime,
        local_activity: LocalActivity,
    ) -> tuple[str, FolderRuntime]:
        try:
            current_status = get_folder_status(self.api, self.folder.folder_id)
            new_state = str(current_status.get("state") or folder_state)
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
            return new_state, new_runtime
        # Intentionally broad
        except Exception:
            return folder_state, runtime

    def _tick_sample(
        self,
        now: float,
        folder_state: str,
        runtime: FolderRuntime,
        remote_progress: dict[str, RemoteProgress],
        local_activity: LocalActivity,
        rates: ConnectionRates,
        active_window: float,
        min_rate: float,
    ) -> None:
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
            self.latest_sample = _serialize_sample(self.watch_id, self.folder, status)
        # Intentionally broad
        except Exception as exc:
            self.latest_sample = {
                "status": "failed",
                "reason": "computation_failed",
                "message": str(exc),
            }

    def _tick_events(
        self,
        cursor: int,
        folder_state: str,
        runtime: FolderRuntime,
        remote_progress: dict[str, RemoteProgress],
        local_activity: LocalActivity,
        event_timeout: float,
    ) -> tuple[int, str, FolderRuntime]:
        try:
            events = get_events(self.api, cursor, event_timeout)
            if events:
                config_changed = False
                for event in events:
                    cursor = max(cursor, int(event.get("id", cursor)))
                    (
                        folder_state,
                        runtime,
                        _remote_progress,
                        _local_activity,
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
            return cursor, folder_state, runtime
        # Intentionally broad
        except Exception:
            time.sleep(0.5)
            return cursor, folder_state, runtime


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
