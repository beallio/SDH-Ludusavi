import { vi, describe, it, expect } from "vitest";
import { useGameRefresh } from "./useGameRefresh";

vi.mock("react", () => ({
  useCallback: (fn: any) => fn,
  useState: (initial: any) => [initial, vi.fn()],
  useRef: (initial: any) => ({ current: initial }),
  useEffect: (fn: any) => { fn(); },
}));

vi.mock("../../utils/logging", () => ({
  log: vi.fn(),
  logUiEvent: vi.fn()
}));

describe("useGameRefresh", () => {
  it("calls refreshGames and applies state on success", async () => {
    const getInstalledAppIdsString = vi.fn().mockResolvedValue("app1");
    const refreshGamesCall = vi.fn().mockResolvedValue({ games: [], aliases: {} });
    const getOperationStatus = vi.fn().mockResolvedValue({});
    const getRecentLogs = vi.fn().mockResolvedValue([]);
    const applyRefreshResult = vi.fn().mockReturnValue(true);
    const setInstalledAppIds = vi.fn();
    const setOperation = vi.fn();
    const setLogs = vi.fn();
    const setBusyLabel = vi.fn();
    const notifyFailure = vi.fn();
    const notifySuccess = vi.fn();
    const isMounted = vi.fn().mockReturnValue(true);
    const isRpcStatus = vi.fn().mockReturnValue(false);
    const logRpcStatus = vi.fn();

    const { refreshGames } = useGameRefresh({
      gamesCount: 0,
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
      icons: { refresh: null, warning: null }
    });

    await refreshGames();

    expect(refreshGamesCall).toHaveBeenCalledWith(true, "app1");
    expect(setInstalledAppIds).toHaveBeenCalledWith("app1");
    expect(notifySuccess).toHaveBeenCalled();
    expect(setOperation).toHaveBeenCalled();
    expect(setLogs).toHaveBeenCalled();
    expect(setBusyLabel).toHaveBeenCalledWith(null);
  });

  it("handles rpc status failure", async () => {
    const getInstalledAppIdsString = vi.fn().mockResolvedValue("app1");
    const refreshGamesCall = vi.fn().mockResolvedValue({ status: "error", message: "Oops" });
    const applyRefreshResult = vi.fn();
    const notifyFailure = vi.fn();
    const isRpcStatus = vi.fn().mockReturnValue(true);
    const logRpcStatus = vi.fn();
    const setBusyLabel = vi.fn();

    const { refreshGames } = useGameRefresh({
      gamesCount: 0,
      getInstalledAppIdsString,
      refreshGamesCall,
      getOperationStatus: vi.fn(),
      getRecentLogs: vi.fn(),
      applyRefreshResult,
      setInstalledAppIds: vi.fn(),
      setOperation: vi.fn(),
      setLogs: vi.fn(),
      setBusyLabel,
      notifyFailure,
      notifySuccess: vi.fn(),
      isMounted: vi.fn().mockReturnValue(true),
      isRpcStatus,
      logRpcStatus,
      icons: { refresh: null, warning: null }
    });

    await refreshGames();

    expect(notifyFailure).toHaveBeenCalled();
    expect(logRpcStatus).toHaveBeenCalled();
    expect(applyRefreshResult).not.toHaveBeenCalled();
    expect(setBusyLabel).toHaveBeenCalledWith(null);
  });
});
