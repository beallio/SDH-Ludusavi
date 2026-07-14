import type { AutoSyncStatusKind, SyncthingActivitySample } from "../types";

export type WatchPhase = "pre_game" | "post_game";
export type WatchStep = "allocating" | "watching" | "complete" | "cancelled";
export type WatchLatestStatus = "idle" | "uploading" | "downloading" | "complete";

export type WatchMachineState = Readonly<{
  phase: WatchPhase;
  step: WatchStep;
  initialized: boolean;
  publicationEnabled: boolean;
  activityObserved: boolean;
  mutationObserved: boolean;
  completionObserved: boolean; // sticky: survives later cancel
  settledCount: number;
  lastProcessedTimestamp: number | null;
  latestStatus: WatchLatestStatus;
  handoffActivated: boolean;
  detectionGraceMs: number;
  unavailableReason: string;
}>;

export type WatchMachineEvent =
  | { type: "watch_allocated"; detectionGraceMs: number | undefined }
  | { type: "watch_allocation_failed"; reason?: string }
  | { type: "sample"; sample: SyncthingActivitySample | null }
  | { type: "poll_failed"; reason?: string }
  | { type: "cancel"; reason?: string }
  | { type: "handoff_confirmed" }
  | { type: "handoff_finished" }
  | { type: "pending_activity_timeout" };

export type WatchMachineEffects = Readonly<{
  publish: { status: AutoSyncStatusKind; source: "context" | "timeout" | "rpc_result" } | null;
  resolveReadiness: "ready" | "unavailable" | null;
  resolveQuiescence: "settled" | "unavailable" | null;
  stopWatch: boolean;
  clearPendingTimer: boolean;
  schedulePendingTimer: boolean;
  nextPoll: "active" | "retry" | "none";
}>;

const DEFAULT_DETECTION_GRACE_MS = 30_000;
const ACTIONABLE_UNAVAILABLE_REASONS = new Set([
  "not_configured",
  "api_unavailable",
  "folder_not_found",
  "folder_not_shared",
  "no_connected_peers",
]);

export function mapSyncthingFailureReason(reason: string | undefined): AutoSyncStatusKind | null {
  if (reason === "no_connected_peers") return "syncthing_no_peers";
  if (reason === "folder_not_found" || reason === "folder_not_shared") return "syncthing_folder_not_found";
  if (reason === "api_unavailable") return "syncthing_unavailable";
  return null;
}

export function createInitialWatchState(phase: WatchPhase): WatchMachineState {
  return {
    phase,
    step: "allocating",
    initialized: false,
    publicationEnabled: false,
    activityObserved: false,
    mutationObserved: false,
    completionObserved: false,
    settledCount: 0,
    lastProcessedTimestamp: null,
    latestStatus: "idle",
    handoffActivated: false,
    detectionGraceMs: DEFAULT_DETECTION_GRACE_MS,
    unavailableReason: "initialization_failed",
  };
}

export function isTerminal(state: WatchMachineState): boolean {
  return state.step === "complete" || state.step === "cancelled";
}

export function canCleanup(state: WatchMachineState, superseded: boolean): boolean {
  return isTerminal(state) && (state.phase !== "post_game" || state.handoffActivated || superseded);
}

export function handoffOutcome(state: WatchMachineState): "complete" | "uploading" | "pending" {
  if (state.latestStatus === "complete") return "complete";
  if (state.activityObserved) return "uploading";
  return "pending";
}

function getStatusRank(status: WatchLatestStatus): number {
  if (status === "complete") return 2;
  if (status === "uploading" || status === "downloading") return 1;
  return 0;
}

export function transition(
  state: WatchMachineState,
  event: WatchMachineEvent,
): { state: WatchMachineState; effects: WatchMachineEffects } {
  let nextState = { ...state };
  let effects: WatchMachineEffects = {
    publish: null,
    resolveReadiness: null,
    resolveQuiescence: null,
    stopWatch: false,
    clearPendingTimer: false,
    schedulePendingTimer: false,
    nextPoll: "none",
  };

  switch (event.type) {
    case "watch_allocated": {
      if (state.step !== "allocating") break;
      nextState.step = "watching";
      nextState.detectionGraceMs =
        Number.isFinite(event.detectionGraceMs) && (event.detectionGraceMs as number) > 0
          ? (event.detectionGraceMs as number)
          : DEFAULT_DETECTION_GRACE_MS;
      if (state.phase === "pre_game") {
        nextState.publicationEnabled = true;
      }
      break;
    }

    case "watch_allocation_failed": {
      if (state.step !== "allocating") break;
      nextState.step = "cancelled";
      nextState.unavailableReason =
        event.reason && ACTIONABLE_UNAVAILABLE_REASONS.has(event.reason)
          ? event.reason
          : "initialization_failed";
      effects = {
        ...effects,
        resolveReadiness: "unavailable",
        resolveQuiescence: "unavailable",
      };
      break;
    }

    case "sample": {
      if (state.step !== "watching") break;
      const sample = event.sample;

      if (!sample) {
        effects = { ...effects, nextPoll: "retry" };
        break;
      }

      const timestamp = sample.timestamp_unix;
      const isValidSample = Number.isFinite(timestamp) && sample.folder_state !== "unknown";

      if (!state.initialized) {
        if (!isValidSample) {
          effects = { ...effects, nextPoll: "retry" };
          break;
        }
        nextState.initialized = true;
        effects = { ...effects, resolveReadiness: "ready" };
      }

      if (!Number.isFinite(timestamp) || timestamp === state.lastProcessedTimestamp) {
        effects = { ...effects, nextPoll: "active" };
        break;
      }

      nextState.lastProcessedTimestamp = timestamp;

      const hasActivity =
        state.phase === "post_game"
          ? sample.uploading
          : sample.downloading ||
            sample.uploading ||
            sample.update_in_progress ||
            sample.status === "ACTIVE_TRANSFER" ||
            sample.status === "SCANNING" ||
            sample.status === "UPDATE_NEEDED" ||
            sample.status === "PREPARING" ||
            sample.status === "INDEXING_OR_SEQUENCE_UPDATE";

      const postGameMutation =
        sample.uploading ||
        sample.update_in_progress ||
        sample.status === "ACTIVE_TRANSFER" ||
        sample.status === "SCANNING" ||
        sample.status === "UPDATE_NEEDED" ||
        sample.status === "PREPARING" ||
        sample.status === "INDEXING_OR_SEQUENCE_UPDATE";
      
      const relevantMutation = state.phase === "post_game" ? postGameMutation : hasActivity;
      if (relevantMutation && !state.mutationObserved) {
        nextState.mutationObserved = true;
      }

      if (hasActivity && !state.activityObserved) {
        nextState.activityObserved = true;
      }

      let newStatus: WatchLatestStatus = "idle";
      if (sample.downloading && state.phase !== "post_game") {
        newStatus = "downloading";
        nextState.settledCount = 0;
      } else if (sample.uploading) {
        newStatus = "uploading";
        nextState.settledCount = 0;
      } else if (sample.update_in_progress && state.phase !== "post_game") {
        newStatus = "downloading";
        nextState.settledCount = 0;
      } else if (nextState.mutationObserved && sample.settled) {
        nextState.settledCount++;
        if (nextState.settledCount >= 3) {
          newStatus = "complete";
          nextState.completionObserved = true;
          nextState.step = "complete";
          effects = { ...effects, resolveQuiescence: "settled" };
        }
      } else {
        nextState.settledCount = 0;
      }

      if (state.phase === "post_game") {
        const currentRank = getStatusRank(state.latestStatus);
        const newRank = getStatusRank(newStatus);
        if (newRank > currentRank) {
          nextState.latestStatus = newStatus;
          if (state.publicationEnabled && newStatus !== "idle") {
            const kindMap: Record<string, AutoSyncStatusKind> = {
              uploading: "syncthing_uploading",
              downloading: "syncthing_downloading",
              complete: "syncthing_complete",
            };
            if (kindMap[newStatus]) {
              effects = {
                ...effects,
                publish: { status: kindMap[newStatus], source: "context" },
              };
              if (newStatus === "uploading" || newStatus === "complete") {
                effects = { ...effects, clearPendingTimer: true };
              }
            }
          }
        }
        
        effects = { ...effects, nextPoll: nextState.completionObserved ? "none" : "active" };
        if (nextState.completionObserved) effects = { ...effects, stopWatch: true };
      } else {
        const semanticStatusChanged = newStatus !== state.latestStatus;
        nextState.latestStatus = newStatus;
        if (semanticStatusChanged && (newStatus === "downloading" || newStatus === "uploading")) {
          effects = {
            ...effects,
            publish: { status: `syncthing_${newStatus}` as AutoSyncStatusKind, source: "context" },
            nextPoll: "active"
          };
        } else if (semanticStatusChanged && newStatus === "complete") {
          effects = {
            ...effects,
            publish: { status: "syncthing_complete", source: "context" },
            stopWatch: true,
            nextPoll: "none",
          };
        } else {
          effects = { ...effects, nextPoll: "active" };
        }
      }
      break;
    }

    case "poll_failed": {
      if (state.step === "cancelled") break;
      nextState.step = "cancelled";
      nextState.publicationEnabled = false;
      if (event.reason && ACTIONABLE_UNAVAILABLE_REASONS.has(event.reason)) {
        nextState.unavailableReason = event.reason;
      }
      effects = { ...effects, stopWatch: true };
      effects = { ...effects, resolveQuiescence: "unavailable" };
      if (!state.initialized) {
        effects = { ...effects, resolveReadiness: "unavailable" };
      }
      if (state.publicationEnabled && state.phase === "post_game") {
        effects = {
          ...effects,
          publish: {
            status: mapSyncthingFailureReason(event.reason) ?? "syncthing_unavailable",
            source: "rpc_result",
          },
        };
      }
      break;
    }

    case "cancel": {
      if (state.step === "cancelled") break;
      nextState.step = "cancelled";
      nextState.publicationEnabled = false;
      if (event.reason) {
        nextState.unavailableReason = event.reason;
      }
      effects = {
        ...effects,
        resolveReadiness: "unavailable",
        resolveQuiescence: "unavailable",
        stopWatch: true,
      };
      break;
    }

    case "handoff_confirmed": {
      nextState.handoffActivated = true;
      nextState.publicationEnabled = true;
      if (handoffOutcome(state) === "pending") {
        effects = { ...effects, schedulePendingTimer: true };
      }
      break;
    }

    case "handoff_finished": {
      nextState.handoffActivated = true;
      break;
    }

    case "pending_activity_timeout": {
      if (state.publicationEnabled && state.initialized && state.step !== "cancelled") {
        nextState.step = "cancelled";
        nextState.publicationEnabled = false;
        effects = {
          ...effects,
          publish: { status: "has_backup", source: "timeout" },
          stopWatch: true,
        };
      }
      break;
    }

    default: {
      const _exhaustive: never = event;
      throw new Error(`Unhandled event: ${_exhaustive}`);
    }
  }

  return { state: nextState, effects };
}
