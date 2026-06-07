import { Router } from "@decky/ui";

import type {
  AppLifetimeNotification,
  ConflictResolution,
  LifecycleCheckResult,
  OperationResult,
  ProcessSignalResult,
  RpcResult,
  RpcStatus,
  RunningSession,
  AutoSyncStatusKind,
  SyncthingWatchStartResult,
  SyncthingPollResult,
} from "../types";
import type { LudusaviStateStore } from "../state/ludusaviState";
import { summarizeOperationResult } from "../formatting/operationText";
import { log } from "../utils/logging";
import { isRpcStatus } from "../utils/rpc";
import {
  getMainRunningSession,
  sessionFromAppOverview,
} from "../utils/steam";
import { SyncthingMonitor, type SyncthingRpc } from "./syncthingMonitor";

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
};

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
  const {
    publish: rawPublish,
    hide: rawHide,
    complete: rawComplete,
  } = statusSurface;
  const activeSessions = new Map<number, RunningSession>();
  let fallbackIntervalID: number | null = null;
  let fallbackPreviousAppID: string | null = null;
  let fallbackPreviousAppName: string | null = null;
  let lifecycleRegistration: unknown = null;
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

  const handleAppStart = async (name: string, appID: string, instanceID?: number) => {
    const epoch = ++lifecycleEpoch;
    void syncthingMonitor.stop();

    const publishAutoSyncStatus = (
      status: AutoSyncStatusKind,
      options: Parameters<AutoSyncStatusSurface["publish"]>[1],
    ) => {
      if (epoch === lifecycleEpoch) {
        rawPublish(status, options);
      }
    };

    const completeAutoSyncStatus = (
      result: Parameters<AutoSyncStatusSurface["complete"]>[0],
      options: Parameters<AutoSyncStatusSurface["complete"]>[1],
    ) => {
      if (epoch === lifecycleEpoch) {
        rawComplete(result, options);
      }
    };

    const hideAutoSyncStatus = (
      options?: Parameters<AutoSyncStatusSurface["hide"]>[0],
    ) => {
      if (epoch === lifecycleEpoch) {
        rawHide(options);
      }
    };

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
    }

    const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
    let preGameWatch: any = null;

    const cancelWatch = async (reason: string) => {
      if (preGameWatch) {
        await syncthingMonitor.cancelGeneration(preGameWatch.generation, reason);
      }
    };

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
        await cancelWatch("start_silent_skip");
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
          await cancelWatch("restore_failed_unpaused");
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
          await cancelWatch("restore_failed");
          notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"));
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
          await cancelWatch("conflict_unpaused");
          notifyFailure(
            "SDH-Ludusavi Auto-sync",
            "Launch gate unavailable; conflict resolution skipped while game is loading.",
          );
          return;
        }
        await cancelWatch("conflict_resolution_pending");
        const resolution = await resolveConflict(checkResult);
        if (!resolution) {
          await cancelWatch("conflict_unresolved");
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
          await cancelWatch("conflict_resolution_failed");
          notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"));
        }
        return;
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        await cancelWatch("start_check_failed");
        notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"));
      }
    } catch (err) {
      log("error", `App start handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      await cancelWatch("start_exception");
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed",
      });
    } finally {
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
    const epoch = ++lifecycleEpoch;
    void syncthingMonitor.stop();

    const publishAutoSyncStatus = (
      status: AutoSyncStatusKind,
      options: Parameters<AutoSyncStatusSurface["publish"]>[1],
    ) => {
      if (epoch === lifecycleEpoch) {
        rawPublish(status, options);
      }
    };

    const completeAutoSyncStatus = (
      result: Parameters<AutoSyncStatusSurface["complete"]>[0],
      options: Parameters<AutoSyncStatusSurface["complete"]>[1],
    ) => {
      if (epoch === lifecycleEpoch) {
        rawComplete(result, options);
      }
    };

    const hideAutoSyncStatus = (
      options?: Parameters<AutoSyncStatusSurface["hide"]>[0],
    ) => {
      if (epoch === lifecycleEpoch) {
        rawHide(options);
      }
    };

    const tracked = isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);

    const autoSyncEnabledExit = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
    let postGameWatch: any = null;
    if (autoSyncEnabledExit && tracked) {
      activeMonitorEpoch = epoch;
      postGameWatch = syncthingMonitor.start("post_game", name, appID);
    }

    const cancelWatch = async (reason: string) => {
      if (postGameWatch) {
        await syncthingMonitor.cancelGeneration(postGameWatch.generation, reason);
      }
    };

    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_exit",
        gameName: name,
        appID,
        tracked,
      });
    }

    try {
      log("info", `Calling check_game_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameExitCall(name, appID);
      log("info", `check_game_exit result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        await cancelWatch("exit_silent_skip");
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
          const generation = postGameWatch?.generation ?? null;
          const handoff = generation === null
            ? { status: "unavailable" as const, generation: -1, reason: "watch_not_started" }
            : await syncthingMonitor.activatePostGameHandoff(
                generation,
                750, // SYNCTHING_HANDOFF_CONFIRMATION_MS
                8000, // SYNCTHING_PENDING_ACTIVITY_MS
              );

          if (epoch !== lifecycleEpoch) {
            return;
          }

          switch (handoff.status) {
            case "pending":
              publishAutoSyncStatus("syncthing_pending_upload", {
                source: "lifecycle_exit",
                gameName: name,
                appID,
                tracked,
              });
              return;
            case "uploading":
              publishAutoSyncStatus("syncthing_uploading", {
                source: "lifecycle_exit",
                gameName: name,
                appID,
                tracked,
              });
              return;
            case "complete":
              publishAutoSyncStatus("syncthing_complete", {
                source: "lifecycle_exit",
                gameName: name,
                appID,
                tracked,
              });
              return;
            case "unavailable":
            case "stale":
              completeAutoSyncStatus(result, { gameName: name, appID, tracked });
              return;
          }
        } else {
          await cancelWatch("backup_failed");
          completeAutoSyncStatus(result, { gameName: name, appID, tracked });
          if (result.status === "failed") {
            notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"));
          }
          return;
        }
      }

      await cancelWatch("no_backup_needed");
      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notifyFailure("SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"));
      }
    } catch (err) {
      log("error", `App exit handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      await cancelWatch("exit_exception");
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed",
      });
    } finally {
      await syncGlobalHistory();
    }
  };

  const findRunningSessionByAppID = (appID: string): RunningSession | null => {
    const runningApps = (Router as any).RunningApps; // Router.RunningApps
    if (Array.isArray(runningApps)) {
      for (const app of runningApps) {
        const session = sessionFromAppOverview(app);
        if (session?.appID === appID) {
          return session;
        }
      }
    }

    const mainSession = getMainRunningSession();
    if (mainSession?.appID === appID) {
      return mainSession;
    }

    return null;
  };

  const findStartupSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const startupSession = activeSessions.get(-1) ?? null;
    if (!startupSession) {
      return null;
    }
    if (notification.unAppID === 0 || startupSession.appID === String(notification.unAppID)) {
      return startupSession;
    }
    return null;
  };

  const resolveLifetimeSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const existingSession = activeSessions.get(notification.nInstanceID);
    if (existingSession) {
      return existingSession;
    }

    if (!notification.bRunning) {
      const startupSession = findStartupSession(notification);
      if (startupSession) {
        return startupSession;
      }
    }

    if (notification.unAppID > 0) {
      const appID = String(notification.unAppID);
      const runningSession = findRunningSessionByAppID(appID);
      if (runningSession) {
        return runningSession;
      }
      return { appID, name: "" };
    }

    // unAppID may be 0 for non-Steam shortcuts, so fall back to Router state.
    return getMainRunningSession();
  };

  const handleLifetimeNotification = (notification: AppLifetimeNotification) => {
    try {
      const session = resolveLifetimeSession(notification);
      if (!session?.name) {
        log(
          "warning",
          `Could not resolve app lifetime notification: ${JSON.stringify(notification)}`,
          "lifecycle",
        );
        return;
      }

      if (notification.bRunning) {
        const startupSession = findStartupSession(notification);
        if (startupSession?.appID === session.appID) {
          activeSessions.delete(-1);
          activeSessions.set(notification.nInstanceID, session);
          log(
            "debug",
            `Promoted startup session for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name,
          );
          return;
        }

        if (activeSessions.has(notification.nInstanceID)) {
          log(
            "debug",
            `Duplicate app start ignored for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name,
          );
          return;
        }

        activeSessions.set(notification.nInstanceID, session);
        void handleAppStart(session.name, session.appID, notification.nInstanceID);
        return;
      }

      activeSessions.delete(notification.nInstanceID);
      const startupSession = activeSessions.get(-1);
      if (startupSession?.appID === session.appID) {
        activeSessions.delete(-1);
      }
      void handleAppExit(session.name, session.appID);
    } catch (err) {
      console.error("SDH-Ludusavi: app lifetime notification failed", err);
    }
  };

  const checkMainApp = () => {
    try {
      const mainApp = (Router as any).MainRunningApp;
      const currentAppID = mainApp?.appid ? String(mainApp.appid) : null;
      const currentAppName = mainApp?.display_name || null;

      if (currentAppID !== fallbackPreviousAppID) {
        if (fallbackPreviousAppID && fallbackPreviousAppName) {
          void handleAppExit(fallbackPreviousAppName, fallbackPreviousAppID);
        }
        if (currentAppID && currentAppName) {
          void handleAppStart(currentAppName, currentAppID);
        }

        fallbackPreviousAppID = currentAppID;
        fallbackPreviousAppName = currentAppName;
      }
    } catch (err) {
      console.error("SDH-Ludusavi: watcher loop failed", err);
    }
  };

  const startFallbackPolling = () => {
    log("warning", "Steam app lifetime notifications unavailable; using Router polling", "lifecycle");
    fallbackIntervalID = window.setInterval(checkMainApp, 1000);
  };

  const reconcileStartupSession = () => {
    const session = getMainRunningSession();
    if (!session) {
      return;
    }

    activeSessions.set(-1, session);
    void handleAppStart(session.name, session.appID);
  };

  const unregisterLifecycleNotifications = () => {
    const registration = lifecycleRegistration as
      | { unregister?: () => void; Unregister?: () => void }
      | (() => void)
      | null;
    if (!registration) {
      return;
    }

    if (typeof registration === "function") {
      registration();
    } else if (typeof registration.unregister === "function") {
      registration.unregister();
    } else if (typeof registration.Unregister === "function") {
      registration.Unregister();
    }
  };

  function start() {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    const gameSessions = steamClient?.GameSessions;
    const registerLifetime = gameSessions?.RegisterForAppLifetimeNotifications;
    if (typeof registerLifetime === "function") {
      lifecycleRegistration = registerLifetime.call(gameSessions, (notification: AppLifetimeNotification) => {
        handleLifetimeNotification(notification);
      });
      reconcileStartupSession();
    } else {
      startFallbackPolling();
    }
  }

  function dispose() {
    lifecycleEpoch++;
    unregisterLifecycleNotifications();
    if (fallbackIntervalID !== null) {
      window.clearInterval(fallbackIntervalID);
      fallbackIntervalID = null;
    }
    activeSessions.clear();
    syncthingMonitor.dispose();
  }

  return {
    start,
    dispose,
  };
}
