import { useCallback } from "react";
import type { LogEntry, OperationStatus, RefreshResult, RpcResult } from "../../types";
import { log, logUiEvent } from "../../utils/logging";

export type UseGameRefreshOptions = {
  gamesCount: number;
  getInstalledAppIdsString: () => Promise<string | undefined>;
  refreshGamesCall: (force: boolean, appIds?: string | undefined) => Promise<RpcResult<RefreshResult>>;
  getOperationStatus: () => Promise<OperationStatus>;
  getRecentLogs: () => Promise<LogEntry[]>;
  applyRefreshResult: (result: RpcResult<RefreshResult>, preferredGame?: string) => boolean;
  setInstalledAppIds: (appIds: string | undefined) => void;
  setOperation: (status: OperationStatus) => void;
  setLogs: (logs: LogEntry[]) => void;
  setBusyLabel: (label: string | null) => void;
  notifyFailure: (title: string, body: string, icon: any) => void;
  notifySuccess: (title: string, body: string, icon: any) => void;
  isMounted: () => boolean;
  isRpcStatus: <T>(result: RpcResult<T>) => boolean;
  logRpcStatus: (result: any, operation: string) => void;
  icons: { refresh: any; warning: any };
};

export function useGameRefresh({
  gamesCount,
  getInstalledAppIdsString,
  refreshGamesCall,
  getOperationStatus,
  getRecentLogs,
  applyRefreshResult,
  setInstalledAppIds,
  setOperation,
  setLogs,
  setBusyLabel,
  notifyFailure,
  notifySuccess,
  isMounted,
  isRpcStatus,
  logRpcStatus,
  icons,
}: UseGameRefreshOptions) {
  const refreshGames = useCallback(async () => {
    const startedAt = performance.now();
    logUiEvent("manual_refresh_started", { previous_game_count: gamesCount }, "info", "refresh");
    setBusyLabel("Refreshing games");
    try {
      const installedAppIds = await getInstalledAppIdsString();
      const result = await refreshGamesCall(true, installedAppIds);
      if (isRpcStatus(result)) {
        logRpcStatus(result, "refresh");
        notifyFailure(
          "SDH-Ludusavi refresh failed",
          (result as any).message || "Failed to refresh games",
          icons.warning
        );
      } else if (applyRefreshResult(result)) {
        setInstalledAppIds(installedAppIds);
        notifySuccess(
          "SDH-Ludusavi",
          "Ludusavi game status refreshed",
          icons.refresh
        );
        const operationStatus = await getOperationStatus();
        const recentLogs = await getRecentLogs();
        if (isMounted()) {
          setOperation(operationStatus);
          setLogs(recentLogs);
        }
        logUiEvent(
          "manual_refresh_completed",
          {
            elapsed_ms: Math.round(performance.now() - startedAt),
            game_count: (result as any).games.length,
            log_count: recentLogs.length,
          },
          "info",
          "refresh",
        );
      }
    } catch (error) {
      logUiEvent(
        "manual_refresh_failed",
        {
          elapsed_ms: Math.round(performance.now() - startedAt),
          message: error instanceof Error ? error.message : String(error),
        },
        "error",
        "refresh",
      );
      log("error", `Manual refresh failed: ${error}`);
      notifyFailure(
        "SDH-Ludusavi refresh failed",
        error instanceof Error ? error.message : String(error),
        icons.warning
      );
    } finally {
      if (isMounted()) {
        setBusyLabel(null);
      }
    }
  }, [
    gamesCount,
    getInstalledAppIdsString,
    refreshGamesCall,
    getOperationStatus,
    getRecentLogs,
    applyRefreshResult,
    setInstalledAppIds,
    setOperation,
    setLogs,
    setBusyLabel,
    notifyFailure,
    notifySuccess,
    isMounted,
    isRpcStatus,
    logRpcStatus,
    icons
  ]);

  return { refreshGames };
}
