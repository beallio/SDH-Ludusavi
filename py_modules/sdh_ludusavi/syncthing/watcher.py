from __future__ import annotations

import logging
import time
import uuid
import threading
from typing import Any, Callable

from .api import SyncthingAPI
from .config import SyncthingNotConfiguredError, resolve_api_credentials
from .folders import resolve_folder_by_path
from ._types import (
    FolderSelection,
    FolderRuntime,
    RemoteProgress,
    PeerCompletion,
    LocalActivity,
    ConnectionSnapshot,
    DEFAULT_EVENT_TIMEOUT_SECONDS,
    DEFAULT_ACTIVE_WINDOW_SECONDS,
    POST_GAME_SETTLE_QUIET_WINDOW_SECONDS,
    OUTBOUND_CONFIRMATION_OBSERVATIONS,
    OUTBOUND_OBSERVATION_HOLD_SECONDS,
    OUTBOUND_STALL_WINDOW_SECONDS,
    POST_GAME_WATCH_HARD_CEILING_SECONDS,
    PeerCompletionDiagnostics,
    peer_completion_is_incomplete,
    summarize_peer_completions,
)
from .activity import (
    get_initial_folder_state_and_runtime,
    get_event_cursor,
    get_events,
    get_connection_snapshot,
    get_my_device_id,
    get_peer_completion,
    get_folder_status,
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

# Frontend enforces MAX_WATCH_DURATION_MS = 120_000 (syncthingMonitor.ts);
# backend TTL = frontend cap + 60s margin so well-behaved clients never hit it.
WATCH_TTL_SECONDS = 180.0


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
        on_expired: Callable[[str], None] | None = None,
    ) -> None:
        self.watch_id = watch_id
        self.phase = phase
        self.game_name = game_name
        self.app_id = app_id
        self.folder = folder
        self.api = api
        self.started_at = time.time()
        self.watch_started_monotonic = time.monotonic()
        ttl_seconds = (
            POST_GAME_WATCH_HARD_CEILING_SECONDS + 60.0
            if self._peer_completion_tracking
            else WATCH_TTL_SECONDS
        )
        self.deadline_monotonic = self.watch_started_monotonic + ttl_seconds
        self._on_expired = on_expired
        self._on_observation_finished: Callable[[str], None] | None = None
        self._released_for_observation = False
        self.stop_event = threading.Event()
        self.latest_sample: dict[str, Any] = {}
        self.thread: threading.Thread | None = None
        self.cursor = 0
        self.folder_state = "unknown"
        self.runtime = FolderRuntime()
        self.remote_progress: dict[str, RemoteProgress] = {}
        self.peer_completions: dict[str, PeerCompletion] = {}
        self.local_activity = LocalActivity(active_items={})
        self.connected_devices: frozenset[str] = (
            initial_snapshot.connected_devices if initial_snapshot else frozenset()
        )
        self._last_peer_completion_diagnostics: PeerCompletionDiagnostics | None = None
        self._last_outbound_need: int | None = None
        self._last_outbound_need_decrease_monotonic: float | None = None
        self._outbound_peer_confirmation_streak = 0
        self._outbound_first_peer_completion_reached = False
        self._debug_outbound_completion_observation = False

    @property
    def _peer_completion_tracking(self) -> bool:
        return self.phase == "post_game"

    @property
    def is_debug_extending_peer_completion(self) -> bool:
        """Whether a debug watch continues after its first confirmed peer completes."""
        return self._debug_outbound_completion_observation and not self.stop_event.is_set()

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run, name=f"syncthing-watch-{self.watch_id}", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.ident is not None:
            self.thread.join(timeout=1.0)

    def _deregister_finished_debug_observation(self) -> None:
        if (
            self._released_for_observation
            and self._debug_outbound_completion_observation
            and self._on_observation_finished
        ):
            self._on_observation_finished(self.watch_id)

    def begin_released_observation(self, callback: Callable[[str], None]) -> None:
        self._on_observation_finished = callback
        self._released_for_observation = True

    def _run(self) -> None:
        try:
            self._initialize()
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
            if time.monotonic() >= self.deadline_monotonic:
                logger.warning(
                    "Syncthing watch %s exceeded %ss TTL without stop_watch; self-terminating (phase=%s)",
                    self.watch_id,
                    WATCH_TTL_SECONDS,
                    self.phase,
                )
                self.latest_sample = {
                    "status": "stopped",
                    "watch_id": self.watch_id,
                    "reason": "watch_ttl_expired",
                }
                self.stop_event.set()
                if self._on_expired:
                    self._on_expired(self.watch_id)
                break

            self._tick(time.monotonic())

    def _initialize(self) -> None:
        """Establish the ordered watch baseline before any sample is published."""
        self.folder_state, self.runtime = get_initial_folder_state_and_runtime(
            self.api, self.folder.folder_id, strict=True
        )
        self.cursor = get_event_cursor(self.api)

        if self._peer_completion_tracking:
            self._capture_peer_completion_baselines(time.monotonic())
            # A second local sequence observation closes the baseline race: its
            # mutation must wait for completion reports captured after it.
            self._tick_folder_status(time.monotonic())

    def _capture_peer_completion_baselines(self, now: float) -> None:
        for device_id in self._connected_relevant_device_ids():
            try:
                self.peer_completions[device_id] = get_peer_completion(
                    self.api, self.folder, device_id, now
                )
            # Completion responses and API failures can contain device IDs or raw JSON.
            except Exception as exc:
                logger.warning(
                    "Syncthing peer completion initialization failed: %s", type(exc).__name__
                )
                raise RuntimeError("Syncthing peer completion initialization failed.") from exc

    def _connected_relevant_device_ids(self) -> frozenset[str]:
        return frozenset(set(self.folder.device_ids) & self.connected_devices)

    def _tick(self, now: float) -> None:
        # 1. Capture a monotonic timestamp for folder polling.
        now_pre = now

        # 2. Poll relevant-peer connectivity.
        self._tick_connectivity()

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
            self._deregister_finished_debug_observation()
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
        if self._stop_if_post_game_upload_incomplete(now_post):
            return
        self._tick_sample(now_post)
        self._latch_post_game_peer_completion()

    def _tick_connectivity(self) -> None:
        try:
            snapshot = get_connection_snapshot(self.api)
            self.connected_devices = snapshot.connected_devices
        # Intentionally broad; keeps the last known connected-device set
        except Exception:
            return

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
            if self._peer_completion_tracking and new_runtime.sequence > self.runtime.sequence:
                self.local_activity.outbound_index_observed_monotonic = now
                self.local_activity.outbound_observation_hold_deadline_monotonic = max(
                    self.local_activity.outbound_observation_hold_deadline_monotonic,
                    now + OUTBOUND_OBSERVATION_HOLD_SECONDS,
                )
            self.folder_state = new_state
            self.runtime = new_runtime
        # Intentionally broad
        except Exception:
            return

    def _tick_sample(self, now: float) -> None:
        try:
            connected_relevant_device_ids = self._connected_relevant_device_ids()
            settle_quiet_window_seconds = (
                POST_GAME_SETTLE_QUIET_WINDOW_SECONDS if self.phase == "post_game" else None
            )
            status = compute_activity_status(
                folder_state=self.folder_state,
                remote_progress=self.remote_progress,
                local_activity=self.local_activity,
                runtime=self.runtime,
                active_window_seconds=DEFAULT_ACTIVE_WINDOW_SECONDS,
                now=now,
                settle_quiet_window_seconds=settle_quiet_window_seconds,
                peer_completions=self.peer_completions,
                connected_relevant_device_ids=connected_relevant_device_ids,
                peer_completion_tracking=self._peer_completion_tracking,
                outbound_peer_confirmation_pending=self._outbound_peer_confirmation_pending(
                    connected_relevant_device_ids
                ),
            )
            self.latest_sample = _serialize_sample(self.watch_id, status)
            self._log_peer_completion_transition()
        # Intentionally broad
        except Exception as exc:
            self.latest_sample = {
                "status": "failed",
                "reason": "computation_failed",
                "message": str(exc),
            }

    def _outbound_peer_confirmation_pending(
        self, connected_relevant_device_ids: frozenset[str]
    ) -> bool:
        mutation_observed_at = self.local_activity.outbound_index_observed_monotonic
        if not self._peer_completion_tracking or mutation_observed_at == 0:
            self._outbound_peer_confirmation_streak = 0
            return False

        has_fresh_content_complete_peer = any(
            completion is not None
            and not peer_completion_is_incomplete(completion)
            and completion.observed_monotonic >= mutation_observed_at
            for device_id in connected_relevant_device_ids
            if (completion := self.peer_completions.get(device_id)) is not None
        )
        if has_fresh_content_complete_peer:
            self._outbound_peer_confirmation_streak += 1
        else:
            self._outbound_peer_confirmation_streak = 0
        return self._outbound_peer_confirmation_streak < OUTBOUND_CONFIRMATION_OBSERVATIONS

    def _latch_post_game_peer_completion(self) -> None:
        if (
            not self._peer_completion_tracking
            or self._outbound_peer_confirmation_streak < OUTBOUND_CONFIRMATION_OBSERVATIONS
        ):
            return

        sample = self.latest_sample.get("sample")
        if not isinstance(sample, dict) or not sample.get("settled"):
            return

        if not self._outbound_first_peer_completion_reached:
            self._outbound_first_peer_completion_reached = True
            self._debug_outbound_completion_observation = logger.isEnabledFor(logging.DEBUG)
            return

        if not (self._debug_outbound_completion_observation and self._released_for_observation):
            return

        diagnostics = summarize_peer_completions(
            self.peer_completions,
            self._connected_relevant_device_ids(),
            self.local_activity.outbound_index_observed_monotonic,
        )
        if diagnostics.incomplete_peers == 0 and diagnostics.awaiting_fresh_completion == 0:
            self.stop_event.set()
            self._deregister_finished_debug_observation()

    def _log_peer_completion_transition(self) -> None:
        if not self._peer_completion_tracking:
            return

        diagnostics = summarize_peer_completions(
            self.peer_completions,
            self._connected_relevant_device_ids(),
            self.local_activity.outbound_index_observed_monotonic,
        )
        if diagnostics == self._last_peer_completion_diagnostics:
            return
        if self._last_peer_completion_diagnostics is None:
            transition = "started"
        elif diagnostics.incomplete_peers or diagnostics.awaiting_fresh_completion:
            transition = "incomplete"
        else:
            transition = "acknowledged"
        self._last_peer_completion_diagnostics = diagnostics
        logger.info(
            "Syncthing peer completion %s: phase=%s connected_relevant_peers=%d "
            "incomplete_peers=%d awaiting_fresh_completion=%d needed_bytes=%d "
            "needed_items=%d needed_deletes=%d peers_pending_deletes=%d",
            transition,
            self.phase,
            diagnostics.connected_relevant_peers,
            diagnostics.incomplete_peers,
            diagnostics.awaiting_fresh_completion,
            diagnostics.needed_bytes,
            diagnostics.needed_items,
            diagnostics.needed_deletes,
            diagnostics.peers_pending_deletes,
        )

    def _stop_if_post_game_upload_incomplete(self, now: float) -> bool:
        if not self._peer_completion_tracking:
            return False

        diagnostics = summarize_peer_completions(
            self.peer_completions,
            self._connected_relevant_device_ids(),
            self.local_activity.outbound_index_observed_monotonic,
        )
        if diagnostics.incomplete_peers == 0:
            self._last_outbound_need = None
            self._last_outbound_need_decrease_monotonic = None
            return False

        outstanding_need = diagnostics.aggregate_outstanding_need
        if self._last_outbound_need is None:
            self._last_outbound_need_decrease_monotonic = now
        elif outstanding_need < self._last_outbound_need:
            self._last_outbound_need_decrease_monotonic = now
        self._last_outbound_need = outstanding_need

        stalled = (
            self._last_outbound_need_decrease_monotonic is not None
            and now - self._last_outbound_need_decrease_monotonic >= OUTBOUND_STALL_WINDOW_SECONDS
        )
        reached_hard_ceiling = (
            now - self.watch_started_monotonic >= POST_GAME_WATCH_HARD_CEILING_SECONDS
        )
        if not stalled and not reached_hard_ceiling:
            return False

        logger.info("Syncthing post-game watch stopped with incomplete upload.")
        self.latest_sample = {
            "status": "failed",
            "reason": "post_game_upload_incomplete",
            "message": "Syncthing upload did not complete before monitoring ended.",
        }
        self.stop_event.set()
        self._deregister_finished_debug_observation()
        return True

    def _tick_events(self) -> None:
        try:
            events = get_events(self.api, self.cursor, DEFAULT_EVENT_TIMEOUT_SECONDS)
            if events:
                event_ids = [int(event.get("id", self.cursor)) for event in events]
                if any(event_id < self.cursor for event_id in event_ids):
                    self.cursor = max(event_ids)
                    logger.info(
                        "Syncthing event subscription reset detected; re-seeding event cursor."
                    )
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
                        peer_completions=self.peer_completions,
                        peer_completion_tracking=self._peer_completion_tracking,
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
        self._observing_watches: dict[str, SyncthingWatch] = {}

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
        # Probe errors can echo response payloads holding device IDs, which must
        # never travel through RPC or logs; record only the exception class.
        try:
            my_device_id = get_my_device_id(api)
        # Intentionally broad
        except Exception as exc:
            logger.warning("Syncthing system status probe failed: %s", type(exc).__name__)
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
        # Intentionally broad; sanitized for RPC and logs like the status probe
        except Exception as exc:
            logger.warning("Syncthing connections probe failed: %s", type(exc).__name__)
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
            watch_id,
            phase,
            game_name,
            app_id,
            folder,
            api,
            initial_snapshot=snapshot,
            on_expired=self._deregister_expired_watch,
        )

        watches_to_stop = []
        with self.lock:
            # Check for existing watches with the same signature
            for old_id, old_watch in list(self.watches.items()):
                if old_watch.game_name == game_name and old_watch.app_id == app_id:
                    watches_to_stop.append(old_watch)
                    self.watches.pop(old_id, None)

            self.watches[watch_id] = watch

        for old_watch in watches_to_stop:
            old_watch.stop()

        with self.lock:
            still_registered = self.watches.get(watch_id) is watch

        if still_registered:
            watch.start()

        return {
            "status": "watching",
            "watch_id": watch_id,
            "folder_id": folder.folder_id,
            "label": folder.label,
            "path": folder.path,
            "detection_grace_ms": detection_grace_ms(folder),
        }

    def _deregister_expired_watch(self, watch_id: str) -> None:
        # Lock-ordering note: stop_watch joins the thread with a timeout. If a TTL
        # expiry races stop_watch, the thread can block briefly here; the join times
        # out, stop_watch releases the lock, and pop is a harmless no-op.
        with self.lock:
            self.watches.pop(watch_id, None)
            self._observing_watches.pop(watch_id, None)

    def _deregister_finished_observation(self, watch_id: str) -> None:
        with self.lock:
            self._observing_watches.pop(watch_id, None)

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
            if watch and watch.is_debug_extending_peer_completion:
                watch.begin_released_observation(self._deregister_finished_observation)
                self._observing_watches[watch_id] = watch
                return {"status": "observing", "watch_id": watch_id}
        if watch:
            watch.stop()
        return {"status": "stopped", "watch_id": watch_id}

    def stop_all(self) -> None:
        with self.lock:
            watches_to_stop = {
                **self.watches,
                **self._observing_watches,
            }.values()
            self.watches.clear()
            self._observing_watches.clear()
        for watch in watches_to_stop:
            watch.stop()
