import { vi, describe, it, expect } from "vitest";
import { runOperationFinalize } from "./manualOperationFinalize";
import type { OperationFinalizeOptions } from "./manualOperationFinalize";
import type {
  RefreshResult,
  OperationStatus,
  LogEntry,
  GameOperationHistory,
  RpcResult,
} from "../../types";

type Deferred<Value> = {
  promise: Promise<Value>;
  resolve: (value: Value) => void;
};

function createDeferred<Value>(): Deferred<Value> {
  let resolve!: (value: Value) => void;
  const promise = new Promise<Value>((resolvePromise) => {
    resolve = resolvePromise;
  });

  return { promise, resolve };
}

function createDelayedFinalizeOptions(): OperationFinalizeOptions {
  const refreshResult = { games: [], aliases: {} } as unknown as RpcResult<RefreshResult>;
  const operationStatus: OperationStatus = {
    is_running: false,
    name: null,
    game_name: null,
    last_result: null,
    last_error: null,
  };
  const recentLogs: LogEntry[] = [];
  const gameHistory = {} as RpcResult<Record<string, GameOperationHistory>>;
  const afterTenMilliseconds = <Value>(value: Value) =>
    new Promise<Value>((resolve) => setTimeout(() => resolve(value), 10));

  return {
    selectedGame: null,
    refreshGamesCall: vi.fn(() => afterTenMilliseconds(refreshResult)),
    getOperationStatus: vi.fn(() => afterTenMilliseconds(operationStatus)),
    getRecentLogs: vi.fn(() => afterTenMilliseconds(recentLogs)),
    getGameHistoryCall: vi.fn(() => afterTenMilliseconds(gameHistory)),
    applyRefreshResult: vi.fn(),
    setOperation: vi.fn(),
    setLogs: vi.fn(),
    setGameHistory: vi.fn(),
    isMounted: vi.fn().mockReturnValue(true),
    isRpcStatus: vi.fn().mockReturnValue(false),
  };
}

async function measureTenFinalizations(): Promise<number> {
  const startedAt = Date.now();

  for (let iteration = 0; iteration < 10; iteration += 1) {
    const completion = runOperationFinalize(createDelayedFinalizeOptions());
    await vi.runAllTimersAsync();
    await completion;
  }

  return Date.now() - startedAt;
}

describe("manualOperationFinalize", () => {
  it("starts all independent reads before the first one settles", async () => {
    const refreshResult = createDeferred<RpcResult<RefreshResult>>();
    const operationStatus = createDeferred<OperationStatus>();
    const recentLogs = createDeferred<LogEntry[]>();
    const gameHistory = createDeferred<RpcResult<Record<string, GameOperationHistory>>>();
    const refreshGamesCall = vi.fn(() => refreshResult.promise);
    const getOperationStatus = vi.fn(() => operationStatus.promise);
    const getRecentLogs = vi.fn(() => recentLogs.promise);
    const getGameHistoryCall = vi.fn(() => gameHistory.promise);

    const completion = runOperationFinalize({
      selectedGame: null,
      refreshGamesCall,
      getOperationStatus,
      getRecentLogs,
      getGameHistoryCall,
      applyRefreshResult: vi.fn(),
      setOperation: vi.fn(),
      setLogs: vi.fn(),
      setGameHistory: vi.fn(),
      isMounted: vi.fn().mockReturnValue(true),
      isRpcStatus: vi.fn().mockReturnValue(false),
    });

    expect([
      refreshGamesCall,
      getOperationStatus,
      getRecentLogs,
      getGameHistoryCall,
    ].map((read) => read.mock.calls.length)).toEqual([1, 1, 1, 1]);

    refreshResult.resolve({ games: [], aliases: {} } as unknown as RpcResult<RefreshResult>);
    operationStatus.resolve({
      is_running: false,
      name: null,
      game_name: null,
      last_result: null,
      last_error: null,
    });
    recentLogs.resolve([]);
    gameHistory.resolve({} as RpcResult<Record<string, GameOperationHistory>>);
    await completion;
  });

  it("has a 100 ms virtual critical path for ten finalizations", async () => {
    vi.useFakeTimers();

    try {
      expect(await measureTenFinalizations()).toBe(100);
    } finally {
      vi.useRealTimers();
    }
  });

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
