import type {
  AutoSyncStatusKind,
  RpcResult,
  SyncthingWatchStartResult,
  SyncthingPollResult,
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

export class SyncthingMonitor {
  private rpc: SyncthingRpc;
  private onStatus: StatusCallback;
  private activeWatchID: string | null = null;
  private activePollInterval: number | null = null;
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
      const wID = startRes.watch_id;

      let elapsedSeconds = 0;
      let activityObserved = false;
      let settledCount = 0;
      const source: "lifecycle_start" | "lifecycle_exit" =
        phase === "pre_game" ? "lifecycle_start" : "lifecycle_exit";

      this.activePollInterval = window.setInterval(async () => {
        if (wID !== this.activeWatchID) {
          if (this.activePollInterval !== null) {
            window.clearInterval(this.activePollInterval);
            this.activePollInterval = null;
          }
          return;
        }

        elapsedSeconds++;
        if (elapsedSeconds > 120) {
          log("info", `Syncthing watch ${wID} hit 120s timeout, stopping.`);
          this.clearPollState(wID);
          await this.stopWatchSafe(wID);
          return;
        }

        try {
          const pollRes = await this.rpc.pollWatch(wID);
          if (wID !== this.activeWatchID) {
            if (this.activePollInterval !== null) {
              window.clearInterval(this.activePollInterval);
              this.activePollInterval = null;
            }
            return;
          }

          if (isRpcStatus(pollRes)) {
            log("error", `Syncthing poll failed: ${pollRes.reason} - ${pollRes.message}`);
            this.clearPollState(wID);
            await this.stopWatchSafe(wID);
            return;
          }

          if (pollRes.status === "stopped") {
            log("info", `Syncthing watch ${wID} stopped by backend.`);
            this.clearPollState(wID);
            return;
          }

          const sample = pollRes.sample;
          if (!sample) return;

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
            activityObserved = true;
          }

          if (sample.downloading) {
            this.onStatus("syncthing_downloading", { source, gameName: name, appID });
          } else if (sample.uploading) {
            this.onStatus("syncthing_uploading", { source, gameName: name, appID });
          } else if (sample.update_in_progress) {
            this.onStatus(
              phase === "pre_game" ? "syncthing_downloading" : "syncthing_uploading",
              { source, gameName: name, appID },
            );
          } else if (activityObserved && sample.settled) {
            settledCount++;
            if (settledCount >= 3) {
              this.onStatus("syncthing_complete", { source, gameName: name, appID });
              this.clearPollState(wID);
              await this.stopWatchSafe(wID);
            }
          } else {
            settledCount = 0;
          }
        } catch (err) {
          log("error", `Error polling Syncthing watch ${wID}: ${err}`);
          this.clearPollState(wID);
          await this.stopWatchSafe(wID);
        }
      }, 1000);
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
    if (this.activePollInterval !== null) {
      window.clearInterval(this.activePollInterval);
      this.activePollInterval = null;
    }
    this.activeWatchID = null;
    if (wID !== null) {
      void this.stopWatchSafe(wID);
    }
  }

  private async stopInternal(): Promise<void> {
    if (this.activePollInterval !== null) {
      window.clearInterval(this.activePollInterval);
      this.activePollInterval = null;
    }
    if (this.activeWatchID !== null) {
      const wID = this.activeWatchID;
      this.activeWatchID = null;
      await this.stopWatchSafe(wID);
    }
  }

  private clearPollState(wID: string): void {
    if (this.activePollInterval !== null) {
      window.clearInterval(this.activePollInterval);
    }
    if (this.activeWatchID === wID) {
      this.activePollInterval = null;
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
