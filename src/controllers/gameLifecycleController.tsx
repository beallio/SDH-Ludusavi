

import { createPauseLease, type PauseLeaseHandle } from "./launchGateLease";
import type {
  ConflictResolution,
  LifecycleCheckResult,
  OperationResult,
  ProcessSignalResult,
  PauseGameProcessResult,
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

import {
  evaluateStartCheck,
  evaluateStartRestore,
  evaluateStartConflictResolution,
  getStartCleanup,
  evaluateExitCheck,
  evaluateExitBackup,
  evaluateExitHandoff,
  getExitCleanup,
  type StartState,
  type ExitState,
  type LifecycleCommand,
} from "./gameLifecycleDecision";


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
  pauseGameProcess: (pid: number) => Promise<RpcResult<PauseGameProcessResult>>;
  resumeGameProcess: (pid: number) => Promise<RpcResult<ProcessSignalResult>>;
  renewGameProcessPause: (pid: number, leaseId: string) => Promise<RpcResult<import("../types").RenewGameProcessPauseResult>>;
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
  const { startSyncthingActivityWatch: startWatch, getSyncthingActivity: pollWatch, stopSyncthingActivityWatch: stopWatch, checkGameStart, restoreGameOnStart, resolveGameStartConflict, checkGameExit, backupGameOnExit, pauseGameProcess, resumeGameProcess } = rpc;
  const { publish: rawPublish } = statusSurface;
  let lifecycleEpoch = 0;
  let activeMonitorEpoch = 0;

  const syncthingRpc: SyncthingRpc = { startWatch, pollWatch, stopWatch };

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
    if (ludusaviStore.getSnapshot().trackingReadiness === "cold") {
      await ensureStateReady();
    }
    const epoch = ++lifecycleEpoch;
    void syncthingMonitor.stop();
    const {
      publish: publishAutoSyncStatus,
      complete: completeAutoSyncStatus,
      hide: hideAutoSyncStatus,
    } = createEpochGuardedSurface(statusSurface, epoch, () => lifecycleEpoch);

    const isTrackingFailed = ludusaviStore.getSnapshot().trackingReadiness === "failed";
    const tracked = isTrackingFailed ? true : isTracked(name, appID);
    log("info", `App started: ${name} (${appID}) tracked=${tracked}`);

    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", { source: "lifecycle_start", gameName: name, appID, tracked });
    } else {
      logPreRpcStatusBarSuppressed("start", name, tracked);
    }

    const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
    let preGameWatch: SyncthingWatchSession | null = null;
    let state: StartState = {
      name, appID, instanceID, tracked, autoSyncEnabled,
      paused: false, watchActive: false, retainPreGameWatch: false
    };

    let pauseHandle: PauseLeaseHandle | undefined;
    try {
      const shouldPauseLaunch = autoSyncEnabled && tracked && typeof instanceID === "number" && instanceID > 1;
      if (shouldPauseLaunch) {
        const pauseResult = await pauseGameProcess(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
          state.paused = true;
          // type cast rpc because createPauseLease expects LudusaviRpc but LifecycleRpc has the needed methods
          pauseHandle = createPauseLease(rpc as any, instanceID, pauseResult.lease_id, { warn: (msg) => log("warning", msg), error: (msg, e) => log("error", msg + String(e)) });
        }
      }

      if (autoSyncEnabled && tracked) {
        activeMonitorEpoch = epoch;
        preGameWatch = syncthingMonitor.start("pre_game", name, appID);
        state.watchActive = true;
      }
      
      const execCmds = (cmds: LifecycleCommand[]) => {
        for (const cmd of cmds) {
          if (cmd.type === "publishStatus") publishAutoSyncStatus(cmd.status as any, { source: "lifecycle_start", gameName: name, appID, tracked, resultStatus: cmd.resultStatus as any });
          else if (cmd.type === "hideStatus") hideAutoSyncStatus({ source: "hide", gameName: name, appID, tracked, resultStatus: cmd.resultStatus as any });
          else if (cmd.type === "completeStatus") completeAutoSyncStatus(cmd.result, { gameName: name, appID, tracked });
          else if (cmd.type === "notifyFailure") notifyFailure("SDH-Ludusavi Auto-sync", cmd.result ? summarizeOperationResult(cmd.result, "Auto-sync") : (cmd.fallbackMessage || "Operation failed"));
        }
      };

      let checkResult: RpcResult<LifecycleCheckResult>;
      if (isTrackingFailed) {
        checkResult = { status: "conflict", reason: "startup_tracking_hydration_failed", message: "Failed to load tracking data during startup" };
      } else {
        checkResult = await checkGameStart(name, appID);
      }
      log("info", `check_game_start result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      
      const dec1 = evaluateStartCheck(state, checkResult);
      execCmds(dec1.commands);
      Object.assign(state, dec1.stateUpdates);

      if (dec1.nextRpc === "restore") {
        const restoreRes = await restoreGameOnStart(name, appID);
        log("info", `restore_game_on_start result for ${name} (${appID}): ${JSON.stringify(restoreRes)}`, "lifecycle", name);
        const dec2 = evaluateStartRestore(state, restoreRes);
        execCmds(dec2.commands);
        Object.assign(state, dec2.stateUpdates);
      } else if (dec1.nextRpc === "conflict") {
        await preGameWatch?.cancel("conflict_resolution_pending");
        preGameWatch = null;
        state.watchActive = false;
        
        const resolution = await resolveConflict(checkResult);
        const dec3 = evaluateStartConflictResolution(state, resolution);
        execCmds(dec3.commands);
        Object.assign(state, dec3.stateUpdates);
        
        if (resolution) {
          if (autoSyncEnabled && tracked) {
            activeMonitorEpoch = epoch;
            preGameWatch = syncthingMonitor.start("pre_game", name, appID);
            state.watchActive = true;
          }
          let conflictRes: RpcResult<OperationResult>;
          if (isTrackingFailed) {
             conflictRes = { status: "failed", reason: "startup_tracking_hydration_failed", message: "Cannot apply resolution because tracking data is missing" };
          } else {
             conflictRes = await resolveGameStartConflict(name, appID, resolution);
          }
          const dec4 = evaluateStartConflictResolution(state, resolution, conflictRes);
          execCmds(dec4.commands);
          Object.assign(state, dec4.stateUpdates);
        }
      }
    } catch (err) {
      log("error", `App start handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({ source: "hide", gameName: name, appID, tracked, resultStatus: "failed" });
    } finally {
      const cleanup = getStartCleanup(state);
      for (const cmd of cleanup) {
        if (cmd.type === "cancelWatch") await preGameWatch?.cancel(cmd.reason);
        else if (cmd.type === "resumeProcess") {
          if (pauseHandle) { await pauseHandle.release(); }
          else { try { await resumeGameProcess(cmd.instanceID); } catch (err) { log("error", `Failed to resume process: ${err}`); } }
        } else if (cmd.type === "syncHistory") await syncGlobalHistory();
      }
    }
  };

  const handleAppExit = async (name: string, appID: string) => {
    if (ludusaviStore.getSnapshot().trackingReadiness === "cold") {
      await ensureStateReady();
    }
    const epoch = ++lifecycleEpoch;
    void syncthingMonitor.stop();
    const {
      publish: publishAutoSyncStatus,
      complete: completeAutoSyncStatus,
      hide: hideAutoSyncStatus,
    } = createEpochGuardedSurface(statusSurface, epoch, () => lifecycleEpoch);

    const isTrackingFailed = ludusaviStore.getSnapshot().trackingReadiness === "failed";
    const tracked = isTrackingFailed ? true : isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);

    const autoSyncEnabledExit = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
    let postGameWatch: SyncthingWatchSession | null = null;
    let state: ExitState = {
      name, appID, tracked, autoSyncEnabled: autoSyncEnabledExit,
      watchActive: false, handoffTransferred: false
    };

    if (autoSyncEnabledExit) {
      activeMonitorEpoch = epoch;
      postGameWatch = syncthingMonitor.start("post_game", name, appID);
      state.watchActive = true;
    }

    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", { source: "lifecycle_exit", gameName: name, appID, tracked });
    } else {
      logPreRpcStatusBarSuppressed("exit", name, tracked);
    }
    
    const execCmds = (cmds: LifecycleCommand[]) => {
      for (const cmd of cmds) {
        if (cmd.type === "publishStatus") publishAutoSyncStatus(cmd.status as any, { source: cmd.status.startsWith("syncthing") ? "lifecycle_exit" : "lifecycle_exit", gameName: name, appID, tracked, resultStatus: cmd.resultStatus as any });
        else if (cmd.type === "hideStatus") hideAutoSyncStatus({ source: "hide", gameName: name, appID, tracked, resultStatus: cmd.resultStatus as any });
        else if (cmd.type === "completeStatus") completeAutoSyncStatus(cmd.result, { gameName: name, appID, tracked });
        else if (cmd.type === "notifyFailure") notifyFailure("SDH-Ludusavi Auto-sync", cmd.result ? summarizeOperationResult(cmd.result, "Auto-sync") : (cmd.fallbackMessage || "Operation failed"));
      }
    };

    try {
      let checkResult: RpcResult<LifecycleCheckResult>;
      if (isTrackingFailed) {
        checkResult = { status: "skipped", reason: "startup_tracking_hydration_failed", message: "Failed to load tracking data during startup" };
      } else {
        checkResult = await checkGameExit(name, appID);
      }
      log("info", `check_game_exit result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      
      const dec1 = evaluateExitCheck(state, checkResult);
      execCmds(dec1.commands);
      Object.assign(state, dec1.stateUpdates);

      if (dec1.nextRpc === "backup") {
        const backupResult = await backupGameOnExit(name, appID);
        log("info", `backup_game_on_exit result for ${name} (${appID}): ${JSON.stringify(backupResult)}`, "lifecycle", name);
        
        const dec2 = evaluateExitBackup(state, backupResult);
        execCmds(dec2.commands);
        Object.assign(state, dec2.stateUpdates);

        if (dec2.nextRpc === "handoff") {
          const handoff = postGameWatch === null
            ? { status: "unavailable" as const, reason: "watch_not_started" }
            : await postGameWatch.activatePostGameHandoff(750);
            
          if (epoch !== lifecycleEpoch) return;

          const mappedStatus = handoff.status === "unavailable" ? mapSyncthingFailureReason(handoff.reason) : null;
          const dec3 = evaluateExitHandoff(state, handoff, backupResult, mappedStatus);
          
          for (const cmd of dec3.commands) {
            if (cmd.type === "publishStatus") {
               publishAutoSyncStatus(cmd.status, {
                 source: mappedStatus ? "rpc_result" : "lifecycle_exit",
                 gameName: name, appID, tracked, resultStatus: cmd.resultStatus as any
               });
            } else if (cmd.type === "completeStatus") {
               completeAutoSyncStatus(cmd.result, { gameName: name, appID, tracked });
            }
          }
          Object.assign(state, dec3.stateUpdates);
        }
      }
    } catch (err) {
      log("error", `App exit handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({ source: "hide", gameName: name, appID, tracked, resultStatus: "failed" });
    } finally {
      const cleanup = getExitCleanup(state);
      for (const cmd of cleanup) {
        if (cmd.type === "cancelWatch") await postGameWatch?.cancel(cmd.reason);
        else if (cmd.type === "syncHistory") await syncGlobalHistory();
      }
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
