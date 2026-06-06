import type {
  AutoSyncStatusKind,
  RpcResult,
  SyncthingWatchStartResult,
  SyncthingPollResult,
  SyncthingActivitySample,
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
    source: "lifecycle_start" | "lifecycle_exit";
    gameName: string;
    appID: string;
  },
) => void;

const EMPTY_SAMPLE_RETRY_MS = 250;
const ACTIVE_POLL_INTERVAL_MS = 500;
const MAX_WATCH_DURATION_MS = 120_000;

interface WatchContext {
  watchID: string;
  sessionToken: number;
  phase: "pre_game" | "post_game";
  gameName: string;
  appID: string;
  source: "lifecycle_start" | "lifecycle_exit";
  startedAt: number;
  activityObserved: boolean;
  settledCount: number;
  lastProcessedTimestamp: number | null;
}

export class SyncthingMonitor {
  private rpc: SyncthingRpc;
  private onStatus: StatusCallback;
  private activeWatchID: string | null = null;
  private activePollTimeout: number | null = null;
  private sessionToken = 0;

  constructor(rpc: SyncthingRpc, onStatus: StatusCallback) {
    this.rpc = rpc;
    this.onStatus = onStatus;
  }

  async start(
    phase: "pre_game" | "post_game",
    name: string,
    appID: string,
  ): Promise<void> {
    this.sessionToken++;
    const token = this.sessionToken;

    await this.stopInternal();

    try {
      const startRes = await this.rpc.startWatch(phase, name, appID);
      if (token !== this.sessionToken) {
        if (!isRpcStatus(startRes) && startRes.status === "watching") {
          await this.stopWatchSafe(startRes.watch_id);
        }
        return;
      }

      if (isRpcStatus(startRes)) {
        log("debug", `Syncthing watch start skipped/failed: ${startRes.reason} - ${startRes.message}`);
        return;
      }

      this.activeWatchID = startRes.watch_id;

      const source: "lifecycle_start" | "lifecycle_exit" =
        phase === "pre_game" ? "lifecycle_start" : "lifecycle_exit";

      const context: WatchContext = {
        watchID: startRes.watch_id,
        sessionToken: token,
        phase,
        gameName: name,
        appID,
        source,
        startedAt: Date.now(),
        activityObserved: false,
        settledCount: 0,
        lastProcessedTimestamp: null,
      };

      // Poll once immediately
      await this.pollOnce(context);
    } catch (err) {
      log("error", `Failed to start Syncthing monitor: ${err}`);
    }
  }

  async stop(): Promise<void> {
    this.sessionToken++;
    await this.stopInternal();
  }

  dispose(): void {
    const wID = this.activeWatchID;
    this.clearPollTimeout();
    this.activeWatchID = null;
    if (wID !== null) {
      void this.stopWatchSafe(wID);
    }
  }

  private async stopInternal(): Promise<void> {
    this.clearPollTimeout();
    if (this.activeWatchID !== null) {
      const wID = this.activeWatchID;
      this.activeWatchID = null;
      await this.stopWatchSafe(wID);
    }
  }

  private schedulePoll(delayMs: number, context: WatchContext): void {
    if (context.sessionToken !== this.sessionToken) {
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

  private async pollOnce(context: WatchContext): Promise<void> {
    if (context.sessionToken !== this.sessionToken || context.watchID !== this.activeWatchID) {
      return;
    }

    const elapsed = Date.now() - context.startedAt;
    if (elapsed > MAX_WATCH_DURATION_MS) {
      log("info", `Syncthing watch ${context.watchID} hit 120s timeout, stopping.`);
      this.clearPollStateAndStop(context.watchID);
      return;
    }

    try {
      const pollRes = await this.rpc.pollWatch(context.watchID);
      if (context.sessionToken !== this.sessionToken || context.watchID !== this.activeWatchID) {
        return;
      }

      if (isRpcStatus(pollRes)) {
        log("error", `Syncthing poll failed: ${pollRes.reason} - ${pollRes.message}`);
        this.clearPollStateAndStop(context.watchID);
        return;
      }

      if (pollRes.status === "activity") {
        const sample = pollRes.sample;
        if (!sample) {
          this.schedulePoll(EMPTY_SAMPLE_RETRY_MS, context);
          return;
        }

        const continuePolling = this.processSample(context, sample);
        if (continuePolling) {
          this.schedulePoll(ACTIVE_POLL_INTERVAL_MS, context);
        }
      } else {
        log("info", `Syncthing watch ${context.watchID} stopped by backend.`);
        this.clearPollState(context.watchID);
      }
    } catch (err) {
      log("error", `Error polling Syncthing watch ${context.watchID}: ${err}`);
      this.clearPollStateAndStop(context.watchID);
    }
  }

  private processSample(context: WatchContext, sample: SyncthingActivitySample): boolean {
    const timestamp = sample.timestamp_unix;
    if (timestamp === undefined || timestamp === null || !isFinite(timestamp)) {
      log("debug", `Invalid or missing timestamp in sample: ${timestamp}`);
      return true;
    }

    if (timestamp === context.lastProcessedTimestamp) {
      return true;
    }

    context.lastProcessedTimestamp = timestamp;

    const hasActivity =
      sample.downloading ||
      sample.uploading ||
      sample.update_in_progress ||
      sample.status === "ACTIVE_TRANSFER" ||
      sample.status === "SCANNING" ||
      sample.status === "UPDATE_NEEDED" ||
      sample.status === "PREPARING" ||
      sample.status === "INDEXING_OR_SEQUENCE_UPDATE";

    if (hasActivity) {
      context.activityObserved = true;
    }

    if (sample.downloading) {
      this.onStatus("syncthing_downloading", { source: context.source, gameName: context.gameName, appID: context.appID });
      context.settledCount = 0;
    } else if (sample.uploading) {
      this.onStatus("syncthing_uploading", { source: context.source, gameName: context.gameName, appID: context.appID });
      context.settledCount = 0;
    } else if (sample.update_in_progress) {
      this.onStatus(
        context.phase === "pre_game" ? "syncthing_downloading" : "syncthing_uploading",
        { source: context.source, gameName: context.gameName, appID: context.appID },
      );
      context.settledCount = 0;
    } else if (context.activityObserved && sample.settled) {
      context.settledCount++;
      if (context.settledCount >= 3) {
        this.onStatus("syncthing_complete", { source: context.source, gameName: context.gameName, appID: context.appID });
        this.clearPollStateAndStop(context.watchID);
        return false;
      }
    } else {
      context.settledCount = 0;
    }

    return true;
  }

  private clearPollStateAndStop(wID: string): void {
    this.clearPollState(wID);
    void this.stopWatchSafe(wID);
  }

  private clearPollState(wID: string): void {
    if (this.activeWatchID === wID) {
      this.clearPollTimeout();
      this.activeWatchID = null;
    }
  }

  private async stopWatchSafe(wID: string): Promise<void> {
    try {
      await this.rpc.stopWatch(wID);
    } catch (err) {
      log("error", `Failed to stop Syncthing watch ${wID}: ${err}`);
    }
  }
}

