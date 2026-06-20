import { vi, describe, it, expect } from "vitest";
import { runOperationFinalize } from "./manualOperationFinalize";
import type { RefreshResult, OperationStatus, LogEntry, GameOperationHistory } from "../../types";

describe("manualOperationFinalize", () => {
  it("fetches updates and applies them when mounted", async () => {
    const mockRefreshResult = { games: [], aliases: {} } as unknown as RefreshResult;
    const mockOperationStatus: OperationStatus = { is_running: false, name: null, game_name: null, last_result: null, last_error: null };
    const mockRecentLogs = [{ level: "info", message: "test", timestamp: "123" }] as unknown as LogEntry[];
    const mockGameHistory: Record<string, GameOperationHistory> = {};

    const refreshGamesCall = vi.fn().mockResolvedValue(mockRefreshResult);
    const getOperationStatus = vi.fn().mockResolvedValue(mockOperationStatus);
    const getRecentLogs = vi.fn().mockResolvedValue(mockRecentLogs);
    const getGameHistoryCall = vi.fn().mockResolvedValue(mockGameHistory);
    const applyRefreshResult = vi.fn();
    const setOperation = vi.fn();
    const setLogs = vi.fn();
    const setGameHistory = vi.fn();
    const isMounted = vi.fn().mockReturnValue(true);
    const isRpcStatus = vi.fn().mockReturnValue(false);

    await runOperationFinalize({
      selectedGame: "Test Game",
      refreshGamesCall,
      getOperationStatus,
      getRecentLogs,
      getGameHistoryCall,
      applyRefreshResult,
      setOperation,
      setLogs,
      setGameHistory,
      isMounted,
      isRpcStatus,
    });

    expect(refreshGamesCall).toHaveBeenCalledWith(false);
    expect(getOperationStatus).toHaveBeenCalled();
    expect(getRecentLogs).toHaveBeenCalled();
    expect(getGameHistoryCall).toHaveBeenCalled();

    expect(applyRefreshResult).toHaveBeenCalledWith(mockRefreshResult, "Test Game");
    expect(setOperation).toHaveBeenCalledWith(mockOperationStatus);
    expect(setLogs).toHaveBeenCalledWith(mockRecentLogs);
    expect(setGameHistory).toHaveBeenCalledWith(mockGameHistory);
  });

  it("skips state updates when unmounted", async () => {
    const applyRefreshResult = vi.fn();
    const setOperation = vi.fn();
    const setLogs = vi.fn();
    const setGameHistory = vi.fn();

    await runOperationFinalize({
      selectedGame: null,
      refreshGamesCall: vi.fn().mockResolvedValue({ games: [] }),
      getOperationStatus: vi.fn().mockResolvedValue({}),
      getRecentLogs: vi.fn().mockResolvedValue([]),
      getGameHistoryCall: vi.fn().mockResolvedValue({}),
      applyRefreshResult,
      setOperation,
      setLogs,
      setGameHistory,
      isMounted: vi.fn().mockReturnValue(false),
      isRpcStatus: vi.fn().mockReturnValue(false),
    });

    expect(applyRefreshResult).toHaveBeenCalled();
    expect(setOperation).not.toHaveBeenCalled();
    expect(setLogs).not.toHaveBeenCalled();
    expect(setGameHistory).not.toHaveBeenCalled();
  });
});
