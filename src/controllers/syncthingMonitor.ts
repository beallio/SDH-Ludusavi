import type {
  AutoSyncStatusKind,
  RpcResult,
  SyncthingWatchStartResult,
  SyncthingPollResult,
  AutoSyncStatusSource,
} from "../types";
import { isRpcStatus } from "../utils/rpc";
import { log } from "../utils/logging";
import {
  createInitialWatchState,
  transition,
  canCleanup,
  handoffOutcome,
  WatchMachineState,
  WatchMachineEvent,
  WatchMachineEffects
} from "./syncthingMonitorMachine";

export { mapSyncthingFailureReason } from "./syncthingMonitorMachine";

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
  waitForPreGameQuiescence: (timeoutMs: number) => Promise<PreGameQuiescenceResult>;
  activatePostGameHandoff: (
    confirmationTimeoutMs: number,
  ) => Promise<PostGameHandoffResult>;
}>;
export type PreGameQuiescenceResult =
  | { status: "idle"; activityObserved: false }
  | { status: "settled"; activityObserved: true }
  | { status: "unavailable"; reason: string; activityObserved: boolean }
  | { status: "timeout"; activityObserved: boolean }
  | { status: "stale"; activityObserved: boolean };
export type PostGameHandoffResult =
  | { status: "pending" }
  | { status: "uploading" }
  | { status: "complete" }
  | { status: "unavailable"; reason: string }
  | { status: "stale" };
class WatchContext {
  watchID: string | null = null;
  generation: SyncthingMonitorGeneration;
  gameName: string;
  appID: string;
  source: "lifecycle_start" | "lifecycle_exit";
  startedAt: number;
  handoffActivatedAt: number | null = null;
  resolveReadiness!: (result: "ready" | "unavailable") => void;
  readinessPromise!: Promise<"ready" | "unavailable">;
  resolveQuiescence!: (result: "settled" | "unavailable") => void;
  quiescencePromise!: Promise<"settled" | "unavailable">;
  state: WatchMachineState;
  constructor(
    generation: SyncthingMonitorGeneration,
    phase: "pre_game" | "post_game",
    gameName: string,
    appID: string
  ) {
    this.generation = generation;
    this.gameName = gameName;
    this.appID = appID;
    this.source = phase === "pre_game" ? "lifecycle_start" : "lifecycle_exit";
    this.startedAt = Date.now();
    this.state = createInitialWatchState(phase);
    this.readinessPromise = new Promise((resolve) => {
      this.resolveReadiness = resolve;
    });
    this.quiescencePromise = new Promise((resolve) => {
      this.resolveQuiescence = resolve;
    });
  }
  get phase() {
    return this.state.phase;
  }
  get cancelled() {
    return this.state.step === "cancelled";
  }
}
const EMPTY_SAMPLE_RETRY_MS = 250;
const ACTIVE_POLL_INTERVAL_MS = 500;
const MAX_WATCH_DURATION_MS = 120_000;
export const PRE_GAME_QUIESCENCE_TIMEOUT_MS = MAX_WATCH_DURATION_MS;
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

    const prevGen = gen - 1;
    const prevContext = this.contexts.get(prevGen);
    if (prevContext) {
      void this.cancelContext(prevContext, "superseded");
    }

    const context = new WatchContext(gen, phase, gameName, appID);
    this.contexts.set(gen, context);
    log("info", `Syncthing watch allocated: generation=${gen} watch_id=null game=${gameName} app_id=${appID}`);

    void this.allocateWatchBackground(context);

    return {
      phase,
      gameName,
      appID,
      cancel: (reason: string) => this.cancelGeneration(gen, reason),
      waitForPreGameQuiescence: (timeoutMs: number) =>
        this.waitForPreGameQuiescence(context, timeoutMs),
      activatePostGameHandoff: (confirmationTimeoutMs: number) =>
        this.activatePostGameHandoff(gen, confirmationTimeoutMs),
    };
  }

  private dispatch(context: WatchContext, event: WatchMachineEvent, opts: { releaseWatchID: boolean }): WatchMachineEffects {
    const { state, effects } = transition(context.state, event);
    context.state = state;

    if (effects.resolveReadiness !== null) {
      context.resolveReadiness(effects.resolveReadiness);
    }
    if (effects.resolveQuiescence !== null) {
      context.resolveQuiescence(effects.resolveQuiescence);
    }
    
    if (effects.publish !== null) {
      this.onStatus(effects.publish.status, {
        source: effects.publish.source === "context" ? context.source : (effects.publish.source as AutoSyncStatusSource),
        gameName: context.gameName,
        appID: context.appID,
      });
    }

    if (effects.clearPendingTimer) {
      this.clearPendingTimeout();
    }
    if (effects.schedulePendingTimer) {
      this.schedulePendingActivityTimeout(context, context.state.detectionGraceMs);
    }

    if (effects.stopWatch) {
      const wID = context.watchID;
      if (opts.releaseWatchID) {
        context.watchID = null;
      } else {
        if (wID !== null) {
          void this.stopWatchSafe(wID);
        }
      }
    }

    if (effects.nextPoll === "retry") {
      this.schedulePoll(EMPTY_SAMPLE_RETRY_MS, context);
    } else if (effects.nextPoll === "active") {
      this.schedulePoll(ACTIVE_POLL_INTERVAL_MS, context);
    }

    this.maybeCleanupContext(context);
    return effects;
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
      this.dispatch(context, { type: "handoff_finished" }, { releaseWatchID: false });
      return { status: "unavailable", reason: context.state.unavailableReason };
    }

    let timeoutID: any = null;
    const timeoutPromise = new Promise<"timeout">((resolve) => {
      timeoutID = window.setTimeout(() => resolve("timeout"), confirmationTimeoutMs);
    });

    try {
      const result = await Promise.race([context.readinessPromise, timeoutPromise]);
      window.clearTimeout(timeoutID);

      if (context.generation !== this.currentGeneration) {
        this.dispatch(context, { type: "handoff_finished" }, { releaseWatchID: false });
        return { status: "stale" };
      }

      if (context.cancelled && result !== "unavailable") {
        this.dispatch(context, { type: "handoff_finished" }, { releaseWatchID: false });
        return { status: "unavailable", reason: context.state.unavailableReason };
      }

      if (result === "timeout") {
        log("info", `Syncthing handoff confirmation timed out: generation=${generation} elapsed_ms=${Date.now() - context.startedAt}`);
        await this.cancelContext(context, "confirmation_timeout");
        this.dispatch(context, { type: "handoff_finished" }, { releaseWatchID: false });
        return { status: "unavailable", reason: "confirmation_timeout" };
      }

      if (result === "unavailable") {
        this.dispatch(context, { type: "handoff_finished" }, { releaseWatchID: false });
        return { status: "unavailable", reason: context.state.unavailableReason };
      }

      const outcome = handoffOutcome(context.state);
      log("info", `Syncthing handoff activated: generation=${generation} state=${outcome}`);
      this.dispatch(context, { type: "handoff_confirmed" }, { releaseWatchID: false });
      return { status: outcome };
    } catch (err) {
      window.clearTimeout(timeoutID);
      this.dispatch(context, { type: "handoff_finished" }, { releaseWatchID: false });
      return { status: "unavailable", reason: String(err) };
    }
  }

  private async waitForPreGameQuiescence(
    context: WatchContext,
    timeoutMs: number,
  ): Promise<PreGameQuiescenceResult> {
    const generation = context.generation;
    if (context.phase !== "pre_game" || generation !== this.currentGeneration) {
      return { status: "stale", activityObserved: context.state.activityObserved };
    }

    let timeoutID: number | null = null;
    const timeoutPromise = new Promise<"timeout">((resolve) => {
      timeoutID = window.setTimeout(() => resolve("timeout"), timeoutMs);
    });

    try {
      if (!context.state.initialized && !context.cancelled) {
        const readiness = await Promise.race([context.readinessPromise, timeoutPromise]);
        if (readiness === "timeout") {
          const activityObserved = context.state.activityObserved;
          await this.cancelContext(context, "quiescence_timeout");
          return { status: "timeout", activityObserved };
        }
      }

      if (generation !== this.currentGeneration) {
        return { status: "stale", activityObserved: context.state.activityObserved };
      }
      if (context.state.completionObserved) {
        return { status: "settled", activityObserved: true };
      }
      if (context.cancelled) {
        return {
          status: "unavailable",
          reason: context.state.unavailableReason,
          activityObserved: context.state.activityObserved,
        };
      }
      if (context.state.initialized && !context.state.activityObserved) {
        return { status: "idle", activityObserved: false };
      }

      const outcome = await Promise.race([context.quiescencePromise, timeoutPromise]);
      if (generation !== this.currentGeneration) {
        return { status: "stale", activityObserved: context.state.activityObserved };
      }
      if (outcome === "timeout") {
        const activityObserved = context.state.activityObserved;
        await this.cancelContext(context, "quiescence_timeout");
        return { status: "timeout", activityObserved };
      }
      if (outcome === "settled" || context.state.completionObserved) {
        return { status: "settled", activityObserved: true };
      }
      return {
        status: "unavailable",
        reason: context.state.unavailableReason,
        activityObserved: context.state.activityObserved,
      };
    } finally {
      if (timeoutID !== null) {
        window.clearTimeout(timeoutID);
      }
    }
  }

  private maybeCleanupContext(context: WatchContext): void {
    if (canCleanup(context.state, context.generation !== this.currentGeneration)) {
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
      initialized: context.state.initialized,
      publicationEnabled: context.state.publicationEnabled,
      activityObserved: context.state.activityObserved,
      completionObserved: context.state.completionObserved,
      latestStatus: context.state.latestStatus,
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
        context.resolveQuiescence("unavailable");
        return;
      }

      if (isRpcStatus(startRes)) {
        log("debug", `Syncthing watch start skipped/failed: ${startRes.reason} - ${startRes.message}`);
        this.dispatch(context, { type: "watch_allocation_failed", reason: startRes.reason }, { releaseWatchID: true });
        return;
      }

      context.watchID = startRes.watch_id;
      this.dispatch(context, { type: "watch_allocated", detectionGraceMs: startRes.detection_grace_ms }, { releaseWatchID: false });
      
      log(
        "info",
        `Syncthing watch allocated: generation=${context.generation} watch_id=${startRes.watch_id} game=${context.gameName} app_id=${context.appID} detection_grace_ms=${context.state.detectionGraceMs}`,
      );

      await this.pollOnce(context);
    } catch (err) {
      log("error", `Failed to allocate Syncthing watch: ${err}`);
      this.dispatch(context, { type: "watch_allocation_failed", reason: "initialization_failed" }, { releaseWatchID: true });
    }
  }

  private async cancelContext(context: WatchContext, reason: string): Promise<void> {
    if (context.cancelled) {
      return;
    }
    log("info", `Syncthing generation cancelled: generation=${context.generation} reason=${reason}`);
    
    if (context.generation === this.currentGeneration) {
      this.clearPollTimeout();
      this.clearPendingTimeout();
    }
    
    const wID = context.watchID;
    const effects = this.dispatch(context, { type: "cancel", reason }, { releaseWatchID: true });
    
    if (effects.stopWatch && wID !== null) {
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
      if (context.generation === this.currentGeneration) {
        const wID = context.watchID;
        const effects = this.dispatch(context, { type: "pending_activity_timeout" }, { releaseWatchID: true });
        if (effects.stopWatch) {
          log("info", `Syncthing pending activity timed out: generation=${context.generation}`);
          this.clearPollTimeout();
          if (wID !== null) {
            void this.stopWatchSafe(wID);
          }
        }
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
      if (context.phase === "pre_game") {
        log("info", `Syncthing pre-game watch reached max duration with no incoming sync; stopping: generation=${context.generation}`);
        this.stopWatchTerminally(context, "watch_duration_timeout");
      } else {
        log("info", `Syncthing watch ${context.watchID} hit the active 120s timeout, stopping.`);
        this.handlePollFailure(context, "watch_duration_timeout");
      }
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
        if (!context.state.initialized && pollRes.sample) {
          const isValidSample = Number.isFinite(pollRes.sample.timestamp_unix) && pollRes.sample.folder_state !== "unknown";
          if (isValidSample) {
            log("info", `Syncthing watch initialized: generation=${context.generation} elapsed_ms=${Date.now() - context.startedAt}`);
          }
        }
        
        const hadActivity = context.state.activityObserved;
        this.dispatch(context, { type: "sample", sample: pollRes.sample || null }, { releaseWatchID: false });
        if (!hadActivity && context.state.activityObserved) {
          log("info", `Syncthing activity observed: generation=${context.generation}`);
        }
      } else {
        log("info", `Syncthing watch ${context.watchID} stopped by backend.`);
        this.handlePollFailure(context, "stopped_by_backend");
      }
    } catch (err) {
      this.handlePollFailure(context, String(err));
    }
  }

  private stopWatchTerminally(context: WatchContext, reason?: string): void {
    if (context.cancelled) {
      return;
    }

    if (context.generation === this.currentGeneration) {
      this.clearPollTimeout();
      this.clearPendingTimeout();
    }

    const wID = context.watchID;
    const effects = this.dispatch(context, { type: "poll_failed", reason }, { releaseWatchID: true });
    
    if (effects.stopWatch && wID !== null) {
      void this.stopWatchSafe(wID);
    }
  }

  private handlePollFailure(context: WatchContext, message: string, reason?: string): void {
    if (context.cancelled) {
      return;
    }
    log("error", `Syncthing poll failure: generation=${context.generation} message=${message}`);
    this.stopWatchTerminally(context, reason);
  }

  private async stopWatchSafe(wID: string): Promise<void> {
    try {
      await this.rpc.stopWatch(wID);
    } catch (err) {
      log("error", `Failed to stop Syncthing watch ${wID}: ${err}`);
    }
  }
}
