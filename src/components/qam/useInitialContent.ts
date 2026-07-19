import { useEffect } from "react";
import type { RpcResult, RpcStatus, Settings, RefreshResult, OperationStatus, GameStatus } from "../../types";
import { log, logUiEvent } from "../../utils/logging";

import { getInstalledAppIdsString } from "../../utils/steam";

export type InitialContentDependencies = {
  isMounted: () => boolean;
  isWarmed: boolean;
  installedAppIds: string | undefined;
  cachedGames: readonly GameStatus[] | null;
  initPromise: Promise<OperationStatus> | null;
  metadataPromise: Promise<void> | null;
  setInitPromise: (promise: Promise<OperationStatus> | null) => void;
  setMetadataPromise: (promise: Promise<void> | null) => void;
  getOperationStatus: () => Promise<OperationStatus>;
  getVersions: () => Promise<any>;
  getLudusaviCommandCall: () => Promise<any>;
  getSettings: () => Promise<RpcResult<Settings>>;
  getGameHistoryCall: () => Promise<any>;
  isGameCacheCurrentCall: (appIds: string) => Promise<any>;
  refreshGamesCall: (force: boolean, appIds?: string) => Promise<RpcResult<RefreshResult>>;
  applySettings: (settings: Settings) => void;
  hydrateDisplayedGame: (gameName: string) => void;
  setGameHistory: (history: any) => void;
  setVersions: (versions: any) => void;
  setLudusaviCommand: (command: any) => void;
  applyRefreshResult: (result: RpcResult<RefreshResult>, preferredGame?: string, allowSteamContextSelection?: boolean) => boolean;
  applyCachedRefreshResult: (preferredGame?: string, allowSteamContextSelection?: boolean) => boolean;
  setInstalledAppIds: (appIds: string | undefined) => void;
  setOperation: (status: OperationStatus) => void;
  setBackgroundRefreshBusy: (busy: boolean) => void;
  setBusyLabel: (label: string | null) => void;
  isRpcStatus: <T>(result: RpcResult<T>) => boolean;
  logRpcStatus: (result: any, operation: string) => void;
  logError: (message: string) => void;
};

export function useInitialContent(deps: InitialContentDependencies) {
  const fetchMetadata = () => {
    if (deps.metadataPromise) {
      return;
    }
    const metaP = (async () => {
      try {
        const [versionsResult, commandResult] = await Promise.allSettled([
          deps.getVersions(),
          deps.getLudusaviCommandCall()
        ]);

        if (versionsResult.status === "fulfilled") {
          const loadedVersions = versionsResult.value;
          log("debug", `Loaded versions: ${JSON.stringify(loadedVersions)}`);
          if (deps.isRpcStatus(loadedVersions)) {
            deps.logRpcStatus(loadedVersions, "versions");
            deps.setVersions({ message: loadedVersions.message || "Error" });
          } else {
            deps.setVersions(loadedVersions);
          }
        } else {
          log("error", `Background load of versions failed: ${versionsResult.reason}`);
          deps.setVersions({ message: "Error" });
        }

        if (commandResult.status === "fulfilled") {
          const loadedCommand = commandResult.value;
          log("debug", `Loaded command: ${JSON.stringify(loadedCommand)}`);
          if (deps.isRpcStatus(loadedCommand)) {
            deps.logRpcStatus(loadedCommand, "command discovery");
          } else {
            deps.setLudusaviCommand(loadedCommand);
          }
        } else {
          log("error", `Background load of command failed: ${commandResult.reason}`);
        }
      } catch (err) {
        log("error", `fetchMetadata failed: ${err}`);
      } finally {
        deps.setMetadataPromise(null);
      }
    })();
    deps.setMetadataPromise(metaP);
  };

  const fetchInitialState = async (): Promise<RpcResult<Settings>> => {
    const [settingsResult, historyResult] = await Promise.allSettled([
      deps.getSettings(),
      deps.getGameHistoryCall()
    ]);
    const failedResult = (operation: string, reason: unknown): RpcStatus => {
      deps.logError(`Initial ${operation} request failed: ${reason}`);
      return { status: "failed", reason: "exception", message: String(reason) };
    };
    const loadedSettings = settingsResult.status === "fulfilled"
      ? settingsResult.value
      : failedResult("settings", settingsResult.reason);
    const loadedHistory = historyResult.status === "fulfilled"
      ? historyResult.value
      : failedResult("history", historyResult.reason);

    log("debug", `Loaded settings: ${JSON.stringify(loadedSettings)}`);
    if (deps.isRpcStatus(loadedSettings)) {
      deps.logRpcStatus(loadedSettings, "settings");
    } else {
      deps.applySettings(loadedSettings as Settings);
      deps.hydrateDisplayedGame((loadedSettings as Settings).selected_game);
    }

    if (deps.isRpcStatus(loadedHistory)) {
      deps.logRpcStatus(loadedHistory, "history");
    } else {
      deps.setGameHistory(loadedHistory);
    }

    return loadedSettings;
  };

  const synchronizeGameList = async (isWarmed: boolean, loadedSettings: RpcResult<Settings>) => {
    log("debug", "Initializing game list (cached)");
    const installedAppIds = await getInstalledAppIdsString();
    const installedAppIdsChanged = deps.installedAppIds !== installedAppIds;

    const cacheCurrentResult =
      isWarmed && !installedAppIdsChanged
        ? await deps.isGameCacheCurrentCall(installedAppIds || "")
        : false;

    const cacheCurrent = !deps.isRpcStatus(cacheCurrentResult) && cacheCurrentResult === true;
    const preferredGame = deps.isRpcStatus(loadedSettings) ? undefined : (loadedSettings as Settings).selected_game;
    logUiEvent("game_list_source_selected", {
      cache_current: cacheCurrent,
      installed_app_ids_changed: installedAppIdsChanged,
      preferred_game: preferredGame,
      warmed: isWarmed,
    });

    if (cacheCurrent && deps.cachedGames) {
      deps.applyCachedRefreshResult(preferredGame, true);
      logUiEvent("game_list_loaded_from_cache", {
        game_count: deps.cachedGames.length,
      }, "info");
    } else {
      const refreshed = await deps.refreshGamesCall(false, installedAppIds);
      if (deps.applyRefreshResult(refreshed, preferredGame, true)) {
        deps.setInstalledAppIds(installedAppIds);
        logUiEvent("game_list_refreshed", {
          game_count: deps.isRpcStatus(refreshed) ? 0 : (refreshed as RefreshResult).games.length,
          reason: installedAppIdsChanged ? "installed_apps_changed" : "cache_stale_or_cold",
        }, "info");
      }
    }
  };

  const loadInitial = async () => {
    const isWarmed = deps.isWarmed;
    if (!deps.isMounted()) return;
    const startedAt = performance.now();
    logUiEvent(
      "initial_load_started",
      {
        cached_game_count: deps.cachedGames?.length ?? 0,
        warmed: isWarmed,
      },
      "info",
    );
    if (!isWarmed) {
      deps.setBusyLabel("Loading");
    }
    deps.setBackgroundRefreshBusy(isWarmed);

    fetchMetadata();

    let activeInit = deps.initPromise;
    if (!activeInit) {
      log("debug", `Creating new initialization promise (warmed=${isWarmed})`);
      activeInit = (async () => {
        const loadedSettings = await fetchInitialState();
        await synchronizeGameList(isWarmed, loadedSettings);
        return deps.getOperationStatus();
      })();
      deps.setInitPromise(activeInit);
    } else {
      log("debug", "Reusing in-flight initialization promise");
    }

    try {
      const loadedOperation = await activeInit;
      if (deps.isMounted()) {
        deps.setOperation(loadedOperation);
      }
      logUiEvent(
        "initial_load_completed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          operation_running: loadedOperation.is_running,
          warmed: isWarmed,
        },
        "info",
      );
    } catch (error) {
      logUiEvent(
        "initial_load_failed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          message: error instanceof Error ? error.message : String(error),
          warmed: isWarmed,
        },
        "error",
      );
      log("error", `Initial load failed: ${error}`);
    } finally {
      deps.setInitPromise(null);
      if (deps.isMounted()) {
        deps.setBackgroundRefreshBusy(false);
        deps.setBusyLabel(null);
      }
    }
  };

  useEffect(() => {
    void loadInitial();
  }, []);

  return { loadInitial };
}
