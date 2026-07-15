import type {
  ConflictResolution,
  LifecycleCheckResult,
  OperationResult,
  PauseGameProcessResult,
  ProcessSignalResult,
  RenewGameProcessPauseResult,
  RpcResult,
  SyncthingPollResult,
  SyncthingWatchStartResult,
} from "../types";

export type LifecycleRpc = {
  checkGameStart: (gameName: string, appID?: string) => Promise<RpcResult<LifecycleCheckResult>>;
  restoreGameOnStart: (gameName: string, appID?: string) => Promise<RpcResult<OperationResult>>;
  resolveGameStartConflict: (
    gameName: string,
    appID: string | undefined,
    resolution: ConflictResolution,
    gatePid?: number,
    gateLeaseId?: string,
  ) => Promise<RpcResult<OperationResult>>;
  checkGameExit: (gameName: string, appID?: string) => Promise<RpcResult<LifecycleCheckResult>>;
  backupGameOnExit: (gameName: string, appID?: string) => Promise<RpcResult<OperationResult>>;
  pauseGameProcess: (pid: number) => Promise<RpcResult<PauseGameProcessResult>>;
  resumeGameProcess: (pid: number, leaseId?: string) => Promise<RpcResult<ProcessSignalResult>>;
  renewGameProcessPause: (pid: number, leaseId: string) => Promise<RpcResult<RenewGameProcessPauseResult>>;
  startSyncthingActivityWatch: (phase: string, gameName?: string, appID?: string) => Promise<RpcResult<SyncthingWatchStartResult>>;
  getSyncthingActivity: (watchID: string) => Promise<RpcResult<SyncthingPollResult>>;
  stopSyncthingActivityWatch: (watchID: string) => Promise<RpcResult<SyncthingPollResult>>;
};
