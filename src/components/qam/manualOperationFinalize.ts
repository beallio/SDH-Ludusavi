import type {
  LogEntry,
  OperationStatus,
  RefreshResult,
  RpcResult,
  GameOperationHistory
} from "../../types";

export type OperationFinalizeOptions = {
  selectedGame: string | null;
  refreshGamesCall: (force: boolean) => Promise<RpcResult<RefreshResult>>;
  getOperationStatus: () => Promise<OperationStatus>;
  getRecentLogs: () => Promise<LogEntry[]>;
  getGameHistoryCall: () => Promise<RpcResult<Record<string, GameOperationHistory>>>;
  applyRefreshResult: (result: RpcResult<RefreshResult>, preferredGame?: string) => void;
  setOperation: (status: OperationStatus) => void;
  setLogs: (logs: LogEntry[]) => void;
  setGameHistory: (history: Record<string, GameOperationHistory>) => void;
  isMounted: () => boolean;
  isRpcStatus: <T>(result: RpcResult<T>) => boolean;
};

export async function runOperationFinalize({
  selectedGame,
  refreshGamesCall,
  getOperationStatus,
  getRecentLogs,
  getGameHistoryCall,
  applyRefreshResult,
  setOperation,
  setLogs,
  setGameHistory,
  isMounted,
  isRpcStatus
}: OperationFinalizeOptions): Promise<void> {
  const [refreshed, operationStatus, recentLogs, refreshedHistory] = await Promise.all([
    refreshGamesCall(false),
    getOperationStatus(),
    getRecentLogs(),
    getGameHistoryCall(),
  ]);

  applyRefreshResult(refreshed, selectedGame || undefined);

  if (isMounted()) {
    setOperation(operationStatus);
    setLogs(recentLogs);
    if (!isRpcStatus(refreshedHistory)) {
      setGameHistory(refreshedHistory as Record<string, GameOperationHistory>);
    }
  }
}
