

import type {
  ConflictResolution,
  LifecycleCheckResult,
  OperationResult,
  ProcessSignalResult,
  RpcResult,
  RpcStatus,
  AutoSyncStatusKind,
  SyncthingWatchStartResult,
  SyncthingPollResult,
} from "../types";
import type { LudusaviStateStore } from "../state/ludusaviState";
import { summarizeOperationResult } from "../formatting/operationText";
import { createSteamLifecycleSource } from "./steamLifecycleSource";
import { log } from "../utils/logging";
import { isRpcStatus } from "../utils/rpc";
import {
  SyncthingMonitor,
  mapSyncthingFailureReason,
  type SyncthingRpc,
  type SyncthingWatchSession,
} from "./syncthingMonitor";

type AutoSyncStatusSurface = {
  publish: (
    status: AutoSyncStatusKind,
    options: {
      source: "lifecycle_start" | "lifecycle_exit" | "rpc_result" | "timeout" | "hide";
      gameName?: string;
      appID?: string;
      tracked?: boolean;
      resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];
    },
  ) => void;
  hide: (options?: {
    source?: "lifecycle_start" | "lifecycle_exit" | "rpc_result" | "timeout" | "hide";
    gameName?: string;
    appID?: string;
    tracked?: boolean;
    resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];
  }) => void;
  complete: (
    result: OperationResult | LifecycleCheckResult,
    options: {
      gameName?: string;
      appID?: string;
      tracked?: boolean;
    },
  ) => void;
};

type LifecycleRpc = {
  checkGameStart: (
    gameName: string,
    appID?: string,
  ) => Promise<RpcResult<LifecycleCheckResult>>;
  restoreGameOnStart: (
    gameName: string,
    appID?: string,
  ) => Promise<RpcResult<OperationResult>>;
  resolveGameStartConflict: (
    gameName: string,
    appID: string | undefined,
    resolution: ConflictResolution,
  ) => Promise<RpcResult<OperationResult>>;
  checkGameExit: (
    gameName: string,
    appID?: string,
  ) => Promise<RpcResult<LifecycleCheckResult>>;
  backupGameOnExit: (
    gameName: string,
    appID?: string,
  ) => Promise<RpcResult<OperationResult>>;
  pauseGameProcess: (pid: number) => Promise<RpcResult<ProcessSignalResult>>;
  resumeGameProcess: (pid: number) => Promise<RpcResult<ProcessSignalResult>>;
  startSyncthingActivityWatch: (
    phase: string,
    gameName?: string,
    appID?: string,
  ) => Promise<RpcResult<SyncthingWatchStartResult>>;
  getSyncthingActivity: (watchID: string) => Promise<RpcResult<SyncthingPollResult>>;
  stopSyncthingActivityWatch: (watchID: string) => Promise<RpcResult<SyncthingPollResult>>;
};

type GameLifecycleControllerDependencies = {
  store: LudusaviStateStore;
  rpc: LifecycleRpc;
  statusSurface: AutoSyncStatusSurface;
  resolveConflict: (conflict: LifecycleCheckResult) => Promise<ConflictResolution | null>;
  notifyFailure: (title: string, body: string) => void;
  syncGlobalHistory: () => Promise<void>;
  ensureStateReady?: () => Promise<void>;
};

function createEpochGuardedSurface(
  surface: AutoSyncStatusSurface,
  epoch: number,
  getCurrentEpoch: () => number,
): AutoSyncStatusSurface {
  const logStaleDrop = (kind: string, detail: string, gameName?: string) => {
    log("debug", `Dropped stale status ${kind} (epoch ${epoch} superseded by ${getCurrentEpoch()}): ${detail}`, "lifecycle", gameName);
  };
  return {
    publish: (status, options) => {
      if (epoch === getCurrentEpoch()) {
        surface.publish(status, options);
      } else {
        logStaleDrop("publish", `status=${status}`, options.gameName);
      }
    },
    complete: (result, options) => {
      if (epoch === getCurrentEpoch()) {
        surface.complete(result, options);
      } else {
        logStaleDrop("complete", `result=${result.status}`, options.gameName);
      }
    },
    hide: (options) => {
      if (epoch === getCurrentEpoch()) {
        surface.hide(options);
      } else {
        logStaleDrop("hide", `source=${options?.source ?? "hide"}`, options?.gameName);
      }
    },
  };
}

export function createGameLifecycleController(
  dependencies: GameLifecycleControllerDependencies,
) {
  const {
    store,
    rpc,
    statusSurface,
    resolveConflict,
    notifyFailure,
    syncGlobalHistory,
    ensureStateReady = async () => {},
  } = dependencies;
  const ludusaviStore = store;
  const {
    startSyncthingActivityWatch: startSyncthingActivityWatchCall,
    getSyncthingActivity: getSyncthingActivityCall,
    stopSyncthingActivityWatch: stopSyncthingActivityWatchCall,
    checkGameStart: checkGameStartCall,
    restoreGameOnStart: restoreGameOnStartCall,
    resolveGameStartConflict: resolveGameStartConflictCall,
    checkGameExit: checkGameExitCall,
    backupGameOnExit: backupGameOnExitCall,
    pauseGameProcess: pauseGameProcessCall,
    resumeGameProcess: resumeGameProcessCall,
  } = rpc;
  const { publish: rawPublish } = statusSurface;
  let lifecycleEpoch = 0;
  let activeMonitorEpoch = 0;

  const syncthingRpc: SyncthingRpc = {
    startWatch: startSyncthingActivityWatchCall,
    pollWatch: getSyncthingActivityCall,
    stopWatch: stopSyncthingActivityWatchCall,
  };

  const syncthingMonitor = new SyncthingMonitor(syncthingRpc, (status, options) => {
    if (activeMonitorEpoch === lifecycleEpoch) {
      rawPublish(status, {
        source: options.source,
        gameName: options.gameName,
        appID: options.appID,
        tracked: true,
      });
    }
  });

  const isTracked = (name: string, appID: string) => {
    return ludusaviStore.isTracked(
      name,
      appID,
      (reason, detail) => {
        if (reason === "appId") {
          log("debug", `Match found via AppID: ${detail}`);
        } else if (reason === "exact") {
          log("debug", `Match found via exact name: ${detail}`);
        } else if (reason === "substring") {
          log("debug", `Match found via substring: ${detail}`);
        }
      },
      (normalizedInput) => {
        log("debug", `No match for ${name} (${appID}) [normalized: ${normalizedInput}]`);
      },
    );
  };

  function shouldPublishAutoSyncStatusBeforeRpc(store: LudusaviStateStore, tracked: boolean) {
    return store.shouldPublishAutoSyncStatusBeforeRpc(tracked);
  }

  function logPreRpcStatusBarSuppressed(phase: "start" | "exit", name: string, tracked: boolean) {
    const snapshot = ludusaviStore.getSnapshot();
    const detail = `tracked=${tracked} autoSyncNotificationsEnabled=${snapshot.autoSyncNotificationsEnabled} trackedNames=${snapshot.trackedNames?.size ?? 0} trackedAppIDs=${snapshot.trackedAppIDs?.size ?? 0}`;
    log("info", `Pre-check status bar not shown on ${phase} for ${name}: ${detail}`, "lifecycle", name);
  }

  const handleAppStart = async (name: string, appID: string, instanceID?: number) => {
    await ensureStateReady();
    const epoch = ++lifecycleEpoch;
    void syncthingMonitor.stop();
    const {
      publish: publishAutoSyncStatus,
      complete: completeAutoSyncStatus,
      hide: hideAutoSyncStatus,
    } = createEpochGuardedSurface(statusSurface, epoch, () => lifecycleEpoch);

    const tracked = isTracked(name, appID);
    log("info", `App started: ${name} (${appID}) tracked=${tracked}`);
    let paused = false;

    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_start",
        gameName: name,
        appID,
        tracked,
      });
    } else {
      logPreRpcStatusBarSuppressed("start", name, tracked);
    }

    const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
    let preGameWatch: SyncthingWatchSession | null = null;
    let retainPreGameWatch = false;

    try {
      const shouldPauseLaunch =
        autoSyncEnabled &&
        tracked &&
        typeof instanceID === "number" &&
        instanceID > 1;

      if (shouldPauseLaunch) {
        const pauseResult = await pauseGameProcessCall(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
          paused = true;
        }
      }

      if (autoSyncEnabled && tracked) {
        activeMonitorEpoch = epoch;
        preGameWatch = syncthingMonitor.start("pre_game", name, appID);
      }
      log("info", `Calling check_game_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameStartCall(name, appID);
      log("info", `check_game_start result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        hideAutoSyncStatus({
          source: "hide",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status,
        });
        return;
      }

      if (checkResult.status === "needed" && checkResult.operation === "restore") {
        if (!paused) {
          const result: OperationResult = {
            status: "failed",
            game: name,
            message: "Launch gate unavailable; restore skipped while game is loading.",
          };
          completeAutoSyncStatus(result, { gameName: name, appID, tracked });
          notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"));
          return;
        }
        publishAutoSyncStatus("restoring", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked,
        });
        log("info", `Calling restore_game_on_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
        const result = await restoreGameOnStartCall(name, appID);
        log("info", `restore_game_on_start result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"));
        } else {
          retainPreGameWatch = true;
        }
        return;
      }

      if (checkResult.status === "conflict") {
        publishAutoSyncStatus("conflict", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status,
        });
        if (!paused) {
          notifyFailure(
            "SDH-Ludusavi Auto-sync",
            "Launch gate unavailable; conflict resolution skipped while game is loading.",
          );
          return;
        }
        await preGameWatch?.cancel("conflict_resolution_pending");
        preGameWatch = null;
        const resolution = await resolveConflict(checkResult);
        if (!resolution) {
          completeAutoSyncStatus(
            { status: "skipped", game: name, reason: "conflict_unresolved" },
            { gameName: name, appID, tracked },
          );
          return;
        }
        if (autoSyncEnabled && tracked) {
          activeMonitorEpoch = epoch;
          preGameWatch = syncthingMonitor.start("pre_game", name, appID);
        }
        const result = await resolveGameStartConflictCall(
          checkResult.game ?? name,
          appID,
          resolution,
        );
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"));
        } else {
          retainPreGameWatch = true;
        }
        return;
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"));
      } else {
        retainPreGameWatch = true;
      }
    } catch (err) {
      log("error", `App start handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed",
      });
    } finally {
      if (!retainPreGameWatch) {
        await preGameWatch?.cancel("start_handler_cleanup");
      }
      if (paused && typeof instanceID === "number") {
        try {
          await resumeGameProcessCall(instanceID);
        } catch (err) {
          log("error", `Failed to resume game process ${instanceID}: ${err}`, "lifecycle", name);
        }
      }
      await syncGlobalHistory();
    }
  };

  const handleAppExit = async (name: string, appID: string) => {
    await ensureStateReady();
    const epoch = ++lifecycleEpoch;
    void syncthingMonitor.stop();
    const {
      publish: publishAutoSyncStatus,
      complete: completeAutoSyncStatus,
      hide: hideAutoSyncStatus,
    } = createEpochGuardedSurface(statusSurface, epoch, () => lifecycleEpoch);

    const tracked = isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);

    const autoSyncEnabledExit = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
    let postGameWatch: SyncthingWatchSession | null = null;
    let handoffTransferred = false;
    // The backend check is authoritative; the frontend tracking cache can be stale.
    // Post-game publication stays buffered until a successful backup activates it.
    if (autoSyncEnabledExit) {
      activeMonitorEpoch = epoch;
      postGameWatch = syncthingMonitor.start("post_game", name, appID);
    }

    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_exit",
        gameName: name,
        appID,
        tracked,
      });
    } else {
      logPreRpcStatusBarSuppressed("exit", name, tracked);
    }

    try {
      log("info", `Calling check_game_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameExitCall(name, appID);
      log("info", `check_game_exit result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        hideAutoSyncStatus({
          source: "hide",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status,
        });
        return;
      }

      if (checkResult.status === "needed" && checkResult.operation === "backup") {
        publishAutoSyncStatus("backing_up", {
          source: "lifecycle_exit",
          gameName: name,
          appID,
          tracked,
        });
        log("info", `Calling backup_game_on_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
        const result = await backupGameOnExitCall(name, appID);
        log("info", `backup_game_on_exit result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);

        if (result.status === "backed_up") {
          publishAutoSyncStatus("has_backup", {
            source: "lifecycle_exit",
            gameName: name,
            appID,
            tracked,
          });
          const handoff = postGameWatch === null
            ? { status: "unavailable" as const, reason: "watch_not_started" }
            : await postGameWatch.activatePostGameHandoff(
                750, // SYNCTHING_HANDOFF_CONFIRMATION_MS
              );

          if (epoch !== lifecycleEpoch) {
            return;
          }

          switch (handoff.status) {
            case "pending":
              handoffTransferred = true;
              publishAutoSyncStatus("syncthing_pending_upload", {
                source: "lifecycle_exit",
                gameName: name,
                appID,
                tracked,
              });
              return;
            case "uploading":
              handoffTransferred = true;
              publishAutoSyncStatus("syncthing_uploading", {
                source: "lifecycle_exit",
                gameName: name,
                appID,
                tracked,
              });
              return;
            case "complete":
              handoffTransferred = true;
              publishAutoSyncStatus("syncthing_complete", {
                source: "lifecycle_exit",
                gameName: name,
                appID,
                tracked,
              });
              return;
            case "unavailable": {
              const mappedStatus = mapSyncthingFailureReason(handoff.reason);
              if (mappedStatus) {
                publishAutoSyncStatus(mappedStatus, {
                  source: "rpc_result",
                  gameName: name,
                  appID,
                  tracked,
                  resultStatus: result.status,
                });
                return;
              }
              completeAutoSyncStatus(result, { gameName: name, appID, tracked });
              return;
            }
            case "stale":
              completeAutoSyncStatus(result, { gameName: name, appID, tracked });
              return;
          }
        } else {
          completeAutoSyncStatus(result, { gameName: name, appID, tracked });
          if (result.status === "failed") {
            notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"));
          }
          return;
        }
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"));
      }
    } catch (err) {
      log("error", `App exit handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed",
      });
    } finally {
      if (!handoffTransferred) {
        await postGameWatch?.cancel("exit_handler_cleanup");
      }
      await syncGlobalHistory();
    }
  };

  const steamLifecycleSource = createSteamLifecycleSource({
    onAppStart: async (session, instanceID) => {
      await handleAppStart(session.name, session.appID, instanceID);
    },
    onAppExit: async (session) => {
      await handleAppExit(session.name, session.appID);
    }
  });

  function start() {
    steamLifecycleSource.start();
  }

  function dispose() {
    lifecycleEpoch++;
    steamLifecycleSource.dispose();
    syncthingMonitor.dispose();
  }

  return {
    start,
    dispose,
  };
}
