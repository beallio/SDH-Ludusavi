import type {
  AutoSyncStatusKind,
  RpcResult,
  SyncthingWatchStartResult,
  SyncthingPollResult,
  SyncthingActivitySample,
  AutoSyncStatusSource,
} from "../types";
import { isRpcStatus } from "../utils/rpc";
import { log } from "../utils/logging";

export type SyncthingRpc = {
  startWatch: (
    phase: string,
    gameName?: string,
    appID?: string,
  ) => Promise<RpcResult<SyncthingWatchStartResult>>;
  pollWatch: (watchID: string) => Promise<RpcResult<SyncthingPollResult>>;
  stopWatch: (watchID: string) => Promise<RpcResult<SyncthingPollResult>>;
};

export type StatusCallback = (
  status: AutoSyncStatusKind,
  options: {
    source: AutoSyncStatusSource;
    gameName: string;
    appID: string;
  },
) => void;

export type SyncthingMonitorGeneration = number;

export type SyncthingWatchSession = Readonly<{
  phase: "pre_game" | "post_game";
  gameName: string;
  appID: string;
  cancel: (reason: string) => Promise<void>;
  activatePostGameHandoff: (
    confirmationTimeoutMs: number,
  ) => Promise<PostGameHandoffResult>;
}>;

export type PostGameHandoffResult =
  | {
      status: "pending";
    }
  | {
      status: "uploading";
    }
  | {
      status: "complete";
    }
  | {
      status: "unavailable";
      reason: string;
    }
  | {
      status: "stale";
    };

interface WatchContext {
  watchID: string | null;
  generation: SyncthingMonitorGeneration;
  phase: "pre_game" | "post_game";
  gameName: string;
  appID: string;
  source: "lifecycle_start" | "lifecycle_exit";
  startedAt: number;
  initialized: boolean;
  cancelled: boolean;
  publicationEnabled: boolean;
  activityObserved: boolean;
  completionObserved: boolean;
  settledCount: number;
  lastProcessedTimestamp: number | null;
  latestStatus: "idle" | "uploading" | "downloading" | "complete";
  resolveReadiness: (result: "ready" | "unavailable") => void;
  readinessPromise: Promise<"ready" | "unavailable">;
  handoffActivated: boolean;
  handoffActivatedAt: number | null;
  detectionGraceMs: number;
  unavailableReason: string;
}

const EMPTY_SAMPLE_RETRY_MS = 250;
const ACTIVE_POLL_INTERVAL_MS = 500;
const MAX_WATCH_DURATION_MS = 120_000;
const DEFAULT_DETECTION_GRACE_MS = 30_000;
const ACTIONABLE_UNAVAILABLE_REASONS = new Set([
  "not_configured",
  "api_unavailable",
  "folder_not_found",
  "folder_not_shared",
  "no_connected_peers",
]);

// Shared reason-to-status mapper for watch allocation and poll failures.
// Returns null for reasons that publish no Syncthing status (not_configured,
// initialization failures, timeouts); callers decide their own fallback.
export function mapSyncthingFailureReason(
  reason: string | undefined,
): AutoSyncStatusKind | null {
  if (reason === "no_connected_peers") {
    return "syncthing_no_peers";
  }
  if (reason === "folder_not_found" || reason === "folder_not_shared") {
    return "syncthing_folder_not_found";
  }
  if (reason === "api_unavailable") {
    return "syncthing_unavailable";
  }
  return null;
}

function getStatusRank(status: "idle" | "uploading" | "downloading" | "complete"): number {
  if (status === "complete") return 2;
  if (status === "uploading" || status === "downloading") return 1;
  return 0;
}

export class SyncthingMonitor {
  private rpc: SyncthingRpc;
  private onStatus: StatusCallback;
  private currentGeneration: SyncthingMonitorGeneration = 0;
  private contexts = new Map<SyncthingMonitorGeneration, WatchContext>();
  private activePollTimeout: number | null = null;
  private pendingTimeoutID: number | null = null;

  constructor(rpc: SyncthingRpc, onStatus: StatusCallback) {
    this.rpc = rpc;
    this.onStatus = onStatus;
  }

  start(
    phase: "pre_game" | "post_game",
    gameName: string,
    appID: string,
  ): SyncthingWatchSession {
    this.currentGeneration++;
    const gen = this.currentGeneration;

    // Synchronously invalidate previous generation and cleanup
    const prevGen = gen - 1;
    const prevContext = this.contexts.get(prevGen);
    if (prevContext) {
      void this.cancelContext(prevContext, "superseded");
    }

    let resolveReadiness!: (result: "ready" | "unavailable") => void;
    const readinessPromise = new Promise<"ready" | "unavailable">((resolve) => {
      resolveReadiness = resolve;
    });

    const source = phase === "pre_game" ? ("lifecycle_start" as const) : ("lifecycle_exit" as const);

    const context: WatchContext = {
      watchID: null,
      generation: gen,
      phase,
      gameName,
      appID,
      source,
      startedAt: Date.now(),
      initialized: false,
      cancelled: false,
      publicationEnabled: false,
      activityObserved: false,
      completionObserved: false,
      settledCount: 0,
      lastProcessedTimestamp: null,
      latestStatus: "idle",
      resolveReadiness,
      readinessPromise,
      handoffActivated: false,
      handoffActivatedAt: null,
      detectionGraceMs: DEFAULT_DETECTION_GRACE_MS,
      unavailableReason: "initialization_failed",
    };

    this.contexts.set(gen, context);
    log("info", `Syncthing watch allocated: generation=${gen} watch_id=null game=${gameName} app_id=${appID}`);

    // Launch background watch allocation
    void this.allocateWatchBackground(context);

    return {
      phase,
      gameName,
      appID,
      cancel: (reason: string) => this.cancelGeneration(gen, reason),
      activatePostGameHandoff: (confirmationTimeoutMs: number) =>
        this.activatePostGameHandoff(gen, confirmationTimeoutMs),
    };
  }

  private async activatePostGameHandoff(
    generation: SyncthingMonitorGeneration,
    confirmationTimeoutMs: number,
  ): Promise<PostGameHandoffResult> {
    const context = this.contexts.get(generation);
    if (!context || context.phase !== "post_game" || context.generation !== this.currentGeneration) {
      return { status: "stale" };
    }
    context.handoffActivatedAt = Date.now();

    if (context.cancelled) {
      context.handoffActivated = true;
      this.maybeCleanupContext(context);
      return { status: "unavailable", reason: context.unavailableReason };
    }

    let timeoutID: any = null;
    const timeoutPromise = new Promise<"timeout">((resolve) => {
      timeoutID = window.setTimeout(() => resolve("timeout"), confirmationTimeoutMs);
    });

    const finish = (res: PostGameHandoffResult) => {
      context.handoffActivated = true;
      this.maybeCleanupContext(context);
      return res;
    };

    try {
      const result = await Promise.race([context.readinessPromise, timeoutPromise]);
      window.clearTimeout(timeoutID);

      if (context.generation !== this.currentGeneration) {
        return finish({ status: "stale" });
      }

      if (context.cancelled && result !== "unavailable") {
        return finish({ status: "unavailable", reason: context.unavailableReason });
      }

      if (result === "timeout") {
        log("info", `Syncthing handoff confirmation timed out: generation=${generation} elapsed_ms=${Date.now() - context.startedAt}`);
        await this.cancelContext(context, "confirmation_timeout");
        return finish({ status: "unavailable", reason: "confirmation_timeout" });
      }

      if (result === "unavailable") {
        return finish({
          status: "unavailable",
          reason: context.unavailableReason,
        });
      }

      // Confirmed! Synchronously enable publication and return buffered state
      context.publicationEnabled = true;
      log("info", `Syncthing handoff activated: generation=${generation} state=${context.latestStatus === "complete" ? "complete" : context.activityObserved ? "uploading" : "pending"}`);

      if (context.latestStatus === "complete") {
        return finish({ status: "complete" });
      } else if (context.activityObserved) {
        return finish({ status: "uploading" });
      } else {
        this.schedulePendingActivityTimeout(context, context.detectionGraceMs);
        return finish({ status: "pending" });
      }
    } catch (err) {
      window.clearTimeout(timeoutID);
      return finish({ status: "unavailable", reason: String(err) });
    }
  }

  private maybeCleanupContext(context: WatchContext): void {
    const isTerminal = context.cancelled || context.completionObserved;
    const isPostGame = context.phase === "post_game";
    const canClean = !isPostGame || context.handoffActivated || context.generation !== this.currentGeneration;

    if (isTerminal && canClean) {
      this.contexts.delete(context.generation);
    }
  }

  private async cancelGeneration(
    generation: SyncthingMonitorGeneration,
    reason: string,
  ): Promise<void> {
    const context = this.contexts.get(generation);
    if (context) {
      await this.cancelContext(context, reason);
    }
  }

  async stop(): Promise<void> {
    const currentContext = this.contexts.get(this.currentGeneration);
    if (currentContext) {
      await this.cancelContext(currentContext, "stop_called");
    }
  }

  dispose(): void {
    this.clearPollTimeout();
    this.clearPendingTimeout();
    for (const context of this.contexts.values()) {
      void this.cancelContext(context, "disposed");
    }
    this.contexts.clear();
  }

  getSnapshotForTest(): Readonly<{
    generation: number | null;
    phase: "pre_game" | "post_game" | null;
    initialized: boolean;
    publicationEnabled: boolean;
    activityObserved: boolean;
    completionObserved: boolean;
    latestStatus: "idle" | "uploading" | "downloading" | "complete" | null;
  }> {
    const context = this.contexts.get(this.currentGeneration);
    if (!context) {
      return {
        generation: null,
        phase: null,
        initialized: false,
        publicationEnabled: false,
        activityObserved: false,
        completionObserved: false,
        latestStatus: null,
      };
    }
    return {
      generation: context.generation,
      phase: context.phase,
      initialized: context.initialized,
      publicationEnabled: context.publicationEnabled,
      activityObserved: context.activityObserved,
      completionObserved: context.completionObserved,
      latestStatus: context.latestStatus,
    };
  }

  private async allocateWatchBackground(context: WatchContext): Promise<void> {
    try {
      const startRes = await this.rpc.startWatch(context.phase, context.gameName, context.appID);

      if (context.generation !== this.currentGeneration || context.cancelled) {
        if (!isRpcStatus(startRes) && startRes.status === "watching") {
          log("info", `Syncthing late watch allocation stopped: generation=${context.generation} watch_id=${startRes.watch_id}`);
          void this.stopWatchSafe(startRes.watch_id);
        }
        context.resolveReadiness("unavailable");
        return;
      }

      if (isRpcStatus(startRes)) {
        log("debug", `Syncthing watch start skipped/failed: ${startRes.reason} - ${startRes.message}`);
        context.unavailableReason =
          startRes.reason && ACTIONABLE_UNAVAILABLE_REASONS.has(startRes.reason)
            ? startRes.reason
            : "initialization_failed";
        context.cancelled = true;
        context.resolveReadiness("unavailable");
        this.maybeCleanupContext(context);
        return;
      }

      context.watchID = startRes.watch_id;
      context.detectionGraceMs =
        Number.isFinite(startRes.detection_grace_ms) && startRes.detection_grace_ms > 0
          ? startRes.detection_grace_ms
          : DEFAULT_DETECTION_GRACE_MS;
      log(
        "info",
        `Syncthing watch allocated: generation=${context.generation} watch_id=${startRes.watch_id} game=${context.gameName} app_id=${context.appID} detection_grace_ms=${context.detectionGraceMs}`,
      );

      if (context.phase === "pre_game") {
        context.publicationEnabled = true;
      }

      await this.pollOnce(context);
    } catch (err) {
      log("error", `Failed to allocate Syncthing watch: ${err}`);
      context.cancelled = true;
      context.resolveReadiness("unavailable");
      this.maybeCleanupContext(context);
    }
  }

  private async cancelContext(context: WatchContext, reason: string): Promise<void> {
    if (context.cancelled) {
      return;
    }
    log("info", `Syncthing generation cancelled: generation=${context.generation} reason=${reason}`);
    context.cancelled = true;
    context.publicationEnabled = false;
    context.resolveReadiness("unavailable");

    if (context.generation === this.currentGeneration) {
      this.clearPollTimeout();
      this.clearPendingTimeout();
    }

    const wID = context.watchID;
    context.watchID = null;
    if (wID !== null) {
      await this.stopWatchSafe(wID);
    }
    this.maybeCleanupContext(context);
  }

  private schedulePoll(delayMs: number, context: WatchContext): void {
    if (context.generation !== this.currentGeneration || context.cancelled) {
      return;
    }
    this.clearPollTimeout();
    this.activePollTimeout = window.setTimeout(async () => {
      await this.pollOnce(context);
    }, delayMs);
  }

  private clearPollTimeout(): void {
    if (this.activePollTimeout !== null) {
      window.clearTimeout(this.activePollTimeout);
      this.activePollTimeout = null;
    }
  }

  private schedulePendingActivityTimeout(context: WatchContext, timeoutMs: number): void {
    this.clearPendingTimeout();
    this.pendingTimeoutID = window.setTimeout(async () => {
      if (
        context.generation === this.currentGeneration &&
        context.publicationEnabled &&
        context.initialized &&
        !context.activityObserved &&
        !context.cancelled
      ) {
        log("info", `Syncthing pending activity timed out: generation=${context.generation}`);
        context.cancelled = true;
        context.publicationEnabled = false;
        this.clearPollTimeout();

        const wID = context.watchID;
        context.watchID = null;
        if (wID !== null) {
          void this.stopWatchSafe(wID);
        }

        this.onStatus("has_backup", {
          source: "timeout",
          gameName: context.gameName,
          appID: context.appID,
        });

        this.maybeCleanupContext(context);
      }
    }, timeoutMs);
  }

  private clearPendingTimeout(): void {
    if (this.pendingTimeoutID !== null) {
      window.clearTimeout(this.pendingTimeoutID);
      this.pendingTimeoutID = null;
    }
  }

  private async pollOnce(context: WatchContext): Promise<void> {
    if (context.generation !== this.currentGeneration || context.cancelled || context.watchID === null) {
      return;
    }

    const timeoutStartedAt =
      context.phase === "pre_game" ? context.startedAt : context.handoffActivatedAt;
    if (
      timeoutStartedAt !== null &&
      Date.now() - timeoutStartedAt > MAX_WATCH_DURATION_MS
    ) {
      log("info", `Syncthing watch ${context.watchID} hit the active 120s timeout, stopping.`);
      this.handlePollFailure(context, "watch_duration_timeout");
      return;
    }

    try {
      const pollRes = await this.rpc.pollWatch(context.watchID);
      if (context.generation !== this.currentGeneration || context.cancelled || context.watchID === null) {
        return;
      }

      if (isRpcStatus(pollRes)) {
        this.handlePollFailure(context, `${pollRes.reason} - ${pollRes.message}`, pollRes.reason);
        return;
      }

      if (pollRes.status === "activity") {
        const sample = pollRes.sample;
        if (!sample) {
          this.schedulePoll(EMPTY_SAMPLE_RETRY_MS, context);
          return;
        }

        if (!context.initialized) {
          const isValidSample = Number.isFinite(sample.timestamp_unix) && sample.folder_state !== "unknown";
          if (isValidSample) {
            context.initialized = true;
            log("info", `Syncthing watch initialized: generation=${context.generation} elapsed_ms=${Date.now() - context.startedAt}`);
            context.resolveReadiness("ready");
          } else {
            this.schedulePoll(EMPTY_SAMPLE_RETRY_MS, context);
            return;
          }
        }

        const continuePolling = this.processSample(context, sample);
        if (continuePolling) {
          this.schedulePoll(ACTIVE_POLL_INTERVAL_MS, context);
        }
      } else {
        log("info", `Syncthing watch ${context.watchID} stopped by backend.`);
        this.handlePollFailure(context, "stopped_by_backend");
      }
    } catch (err) {
      this.handlePollFailure(context, String(err));
    }
  }

  private handlePollFailure(context: WatchContext, message: string, reason?: string): void {
    if (context.cancelled) {
      return;
    }
    log("error", `Syncthing poll failure: generation=${context.generation} message=${message}`);

    if (reason && ACTIONABLE_UNAVAILABLE_REASONS.has(reason)) {
      context.unavailableReason = reason;
    }

    if (!context.initialized) {
      context.resolveReadiness("unavailable");
    }

    context.cancelled = true;
    const wasEnabled = context.publicationEnabled;
    context.publicationEnabled = false;

    if (context.generation === this.currentGeneration) {
      this.clearPollTimeout();
      this.clearPendingTimeout();
    }

    const wID = context.watchID;
    context.watchID = null;
    if (wID !== null) {
      void this.stopWatchSafe(wID);
    }

    if (wasEnabled && context.phase === "post_game") {
      this.onStatus(mapSyncthingFailureReason(reason) ?? "syncthing_unavailable", {
        source: "rpc_result",
        gameName: context.gameName,
        appID: context.appID,
      });
    }

    this.maybeCleanupContext(context);
  }

  private processSample(context: WatchContext, sample: SyncthingActivitySample): boolean {
    const timestamp = sample.timestamp_unix;
    if (timestamp === undefined || timestamp === null || !Number.isFinite(timestamp)) {
      log("debug", `Invalid or missing timestamp in sample: ${timestamp}`);
      return true;
    }

    if (timestamp === context.lastProcessedTimestamp) {
      return true;
    }

    context.lastProcessedTimestamp = timestamp;

    const hasActivity = context.phase === "post_game"
      ? sample.uploading
      : (sample.downloading ||
         sample.uploading ||
         sample.update_in_progress ||
         sample.status === "ACTIVE_TRANSFER" ||
         sample.status === "SCANNING" ||
         sample.status === "UPDATE_NEEDED" ||
         sample.status === "PREPARING" ||
         sample.status === "INDEXING_OR_SEQUENCE_UPDATE");

    if (hasActivity) {
      if (!context.activityObserved) {
        context.activityObserved = true;
        log("info", `Syncthing upload activity observed: generation=${context.generation}`);
      }
    }

    let newStatus: "idle" | "uploading" | "downloading" | "complete" = "idle";

    if (sample.downloading && context.phase !== "post_game") {
      newStatus = "downloading";
      context.settledCount = 0;
    } else if (sample.uploading) {
      newStatus = "uploading";
      context.settledCount = 0;
    } else if (sample.update_in_progress && context.phase !== "post_game") {
      newStatus = "downloading";
      context.settledCount = 0;
    } else if (context.activityObserved && sample.settled) {
      context.settledCount++;
      if (context.settledCount >= 3) {
        newStatus = "complete";
        context.completionObserved = true;
      }
    } else {
      context.settledCount = 0;
    }

    if (context.phase === "post_game") {
      const currentRank = getStatusRank(context.latestStatus);
      const newRank = getStatusRank(newStatus);
      if (newRank > currentRank) {
        context.latestStatus = newStatus;
        if (context.publicationEnabled) {
          if (newStatus !== "idle") {
            this.publishStatusForPostGame(context, newStatus);
          }
        }
      }
    } else {
      // Pre-game immediate non-blocking publication
      if (newStatus === "downloading") {
        this.onStatus("syncthing_downloading", { source: context.source, gameName: context.gameName, appID: context.appID });
      } else if (newStatus === "uploading") {
        this.onStatus("syncthing_uploading", { source: context.source, gameName: context.gameName, appID: context.appID });
      } else if (newStatus === "complete") {
        this.onStatus("syncthing_complete", { source: context.source, gameName: context.gameName, appID: context.appID });
        if (context.watchID !== null) {
          this.clearPollStateAndStop(context.watchID);
        }
        this.maybeCleanupContext(context);
        return false;
      }
    }

    if (context.completionObserved) {
      if (context.watchID !== null) {
        this.clearPollStateAndStop(context.watchID);
      }
      this.maybeCleanupContext(context);
      return false;
    }

    return true;
  }

  private publishStatusForPostGame(context: WatchContext, status: "uploading" | "downloading" | "complete"): void {
    if (status === "uploading" || status === "complete") {
      this.clearPendingTimeout();
    }
    const kindMap: Record<string, AutoSyncStatusKind> = {
      uploading: "syncthing_uploading",
      downloading: "syncthing_downloading",
      complete: "syncthing_complete",
    };
    this.onStatus(kindMap[status], {
      source: context.source,
      gameName: context.gameName,
      appID: context.appID,
    });
  }

  private clearPollStateAndStop(wID: string): void {
    this.clearPollTimeout();
    void this.stopWatchSafe(wID);
  }

  private async stopWatchSafe(wID: string): Promise<void> {
    try {
      await this.rpc.stopWatch(wID);
    } catch (err) {
      log("error", `Failed to stop Syncthing watch ${wID}: ${err}`);
    }
  }
}
