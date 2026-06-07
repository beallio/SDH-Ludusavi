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

export type SyncthingMonitorStartHandle = Readonly<{
  generation: SyncthingMonitorGeneration;
  phase: "pre_game" | "post_game";
  gameName: string;
  appID: string;
}>;

export type PostGameHandoffResult =
  | {
      status: "pending";
      generation: SyncthingMonitorGeneration;
    }
  | {
      status: "uploading";
      generation: SyncthingMonitorGeneration;
    }
  | {
      status: "complete";
      generation: SyncthingMonitorGeneration;
    }
  | {
      status: "unavailable";
      generation: SyncthingMonitorGeneration;
      reason: string;
    }
  | {
      status: "stale";
      generation: SyncthingMonitorGeneration;
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
}

const EMPTY_SAMPLE_RETRY_MS = 250;
const ACTIVE_POLL_INTERVAL_MS = 500;
const MAX_WATCH_DURATION_MS = 120_000;

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
  ): SyncthingMonitorStartHandle {
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
    };

    this.contexts.set(gen, context);
    log("info", `Syncthing watch allocated: generation=${gen} watch_id=null game=${gameName} app_id=${appID}`);

    // Launch background watch allocation
    void this.allocateWatchBackground(context);

    return {
      generation: gen,
      phase,
      gameName,
      appID,
    };
  }

  async activatePostGameHandoff(
    generation: SyncthingMonitorGeneration,
    confirmationTimeoutMs: number,
    pendingActivityTimeoutMs: number,
  ): Promise<PostGameHandoffResult> {
    const context = this.contexts.get(generation);
    if (!context || context.phase !== "post_game" || context.generation !== this.currentGeneration) {
      return { status: "stale", generation };
    }

    if (context.cancelled) {
      return { status: "unavailable", generation, reason: "cancelled" };
    }

    let timeoutID: any = null;
    const timeoutPromise = new Promise<"timeout">((resolve) => {
      timeoutID = window.setTimeout(() => resolve("timeout"), confirmationTimeoutMs);
    });

    try {
      const result = await Promise.race([context.readinessPromise, timeoutPromise]);
      window.clearTimeout(timeoutID);

      if (context.generation !== this.currentGeneration || context.cancelled) {
        return { status: "stale", generation };
      }

      if (result === "timeout") {
        log("info", `Syncthing handoff confirmation timed out: generation=${generation} elapsed_ms=${Date.now() - context.startedAt}`);
        await this.cancelContext(context, "confirmation_timeout");
        return { status: "unavailable", generation, reason: "confirmation_timeout" };
      }

      if (result === "unavailable") {
        return { status: "unavailable", generation, reason: "initialization_failed" };
      }

      // Confirmed! Synchronously enable publication and return buffered state
      context.publicationEnabled = true;
      log("info", `Syncthing handoff activated: generation=${generation} state=${context.latestStatus === "complete" ? "complete" : context.activityObserved ? "uploading" : "pending"}`);

      if (context.latestStatus === "complete") {
        return { status: "complete", generation };
      } else if (context.activityObserved) {
        return { status: "uploading", generation };
      } else {
        this.schedulePendingActivityTimeout(context, pendingActivityTimeoutMs);
        return { status: "pending", generation };
      }
    } catch (err) {
      window.clearTimeout(timeoutID);
      return { status: "unavailable", generation, reason: String(err) };
    }
  }

  async cancelGeneration(
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
      };
    }
    return {
      generation: context.generation,
      phase: context.phase,
      initialized: context.initialized,
      publicationEnabled: context.publicationEnabled,
      activityObserved: context.activityObserved,
      completionObserved: context.completionObserved,
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
        context.resolveReadiness("unavailable");
        return;
      }

      context.watchID = startRes.watch_id;
      log("info", `Syncthing watch allocated: generation=${context.generation} watch_id=${startRes.watch_id} game=${context.gameName} app_id=${context.appID}`);

      if (context.phase === "pre_game") {
        context.publicationEnabled = true;
      }

      await this.pollOnce(context);
    } catch (err) {
      log("error", `Failed to allocate Syncthing watch: ${err}`);
      context.resolveReadiness("unavailable");
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

    const elapsed = Date.now() - context.startedAt;
    if (elapsed > MAX_WATCH_DURATION_MS) {
      log("info", `Syncthing watch ${context.watchID} hit 120s timeout, stopping.`);
      this.handlePollFailure(context, "watch_duration_timeout");
      return;
    }

    try {
      const pollRes = await this.rpc.pollWatch(context.watchID);
      if (context.generation !== this.currentGeneration || context.cancelled || context.watchID === null) {
        return;
      }

      if (isRpcStatus(pollRes)) {
        this.handlePollFailure(context, `${pollRes.reason} - ${pollRes.message}`);
        return;
      }

      if (pollRes.status === "activity") {
        const sample = pollRes.sample;
        if (!sample) {
          this.schedulePoll(EMPTY_SAMPLE_RETRY_MS, context);
          return;
        }

        if (!context.initialized) {
          const isValidSample = Number.isFinite(sample.timestamp_unix);
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

  private handlePollFailure(context: WatchContext, message: string): void {
    if (context.cancelled) {
      return;
    }
    log("error", `Syncthing poll failure: generation=${context.generation} message=${message}`);

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

    if (wasEnabled && !context.activityObserved && context.phase === "post_game") {
      this.onStatus("has_backup", {
        source: "rpc_result",
        gameName: context.gameName,
        appID: context.appID,
      });
    }
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
      ? (sample.uploading ||
         sample.update_in_progress ||
         sample.status === "ACTIVE_TRANSFER" ||
         sample.status === "SCANNING" ||
         sample.status === "UPDATE_NEEDED" ||
         sample.status === "PREPARING" ||
         sample.status === "INDEXING_OR_SEQUENCE_UPDATE") && !sample.downloading
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

    if (sample.downloading) {
      newStatus = "downloading";
      context.settledCount = 0;
    } else if (sample.uploading) {
      newStatus = "uploading";
      context.settledCount = 0;
    } else if (sample.update_in_progress) {
      newStatus = context.phase === "pre_game" ? "downloading" : "uploading";
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
        return false;
      }
    }

    if (context.completionObserved) {
      if (context.watchID !== null) {
        this.clearPollStateAndStop(context.watchID);
      }
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
