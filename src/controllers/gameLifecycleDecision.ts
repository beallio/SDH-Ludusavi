import type {
  LifecycleCheckResult,
  OperationResult,
  ConflictResolution,
  AutoSyncStatusKind,
} from "../types";
import type { PostGameHandoffResult } from "./syncthingMonitor";

export const SILENT_SKIPPED_REASONS = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];

export type LifecycleCommand =
  | { type: "publishStatus"; status: AutoSyncStatusKind; resultStatus?: string }
  | { type: "hideStatus"; resultStatus?: string }
  | { type: "completeStatus"; result: OperationResult | LifecycleCheckResult }
  | { type: "notifyFailure"; result?: OperationResult | LifecycleCheckResult; fallbackMessage?: string };

export type CleanupCommand =
  | { type: "resumeProcess"; instanceID: number }
  | { type: "cancelWatch"; reason: string }
  | { type: "syncHistory" };

export type StartState = {
  name: string;
  appID: string;
  instanceID?: number;
  tracked: boolean;
  autoSyncEnabled: boolean;
  paused: boolean;
  watchActive: boolean;
  retainPreGameWatch: boolean;
};

export type ExitState = {
  name: string;
  appID: string;
  tracked: boolean;
  autoSyncEnabled: boolean;
  watchActive: boolean;
  handoffTransferred: boolean;
};

export type StartDecision = {
  commands: LifecycleCommand[];
  nextRpc?: "restore" | "conflict";
  stateUpdates: Partial<StartState>;
};

export type ExitDecision = {
  commands: LifecycleCommand[];
  nextRpc?: "backup" | "handoff";
  stateUpdates: Partial<ExitState>;
};

export function evaluateStartCheck(state: StartState, checkResult: LifecycleCheckResult): StartDecision {
  if (checkResult.status === "skipped" && SILENT_SKIPPED_REASONS.indexOf(checkResult.reason ?? "") !== -1) {
    return {
      commands: [{ type: "hideStatus", resultStatus: checkResult.status }],
      stateUpdates: {}
    };
  }

  if (checkResult.status === "needed" && checkResult.operation === "restore") {
    if (!state.paused) {
      const result: OperationResult = {
        status: "failed",
        game: state.name,
        message: "Launch gate unavailable; restore skipped while game is loading.",
      };
      return {
        commands: [
          { type: "completeStatus", result },
          { type: "notifyFailure", result }
        ],
        stateUpdates: {}
      };
    }
    return {
      commands: [{ type: "publishStatus", status: "restoring" }],
      nextRpc: "restore",
      stateUpdates: {}
    };
  }

  if (checkResult.status === "conflict") {
    if (!state.paused) {
      return {
        commands: [
          { type: "notifyFailure", fallbackMessage: "Launch gate unavailable; conflict resolution skipped while game is loading." }
        ],
        stateUpdates: {}
      };
    }
    return {
      commands: [{ type: "publishStatus", status: "conflict", resultStatus: checkResult.status }],
      nextRpc: "conflict",
      stateUpdates: {}
    };
  }

  const commands: LifecycleCommand[] = [{ type: "completeStatus", result: checkResult }];
  if (checkResult.status === "failed") {
    commands.push({ type: "notifyFailure", result: checkResult });
  }
  return {
    commands,
    stateUpdates: { retainPreGameWatch: checkResult.status !== "failed" }
  };
}

export function evaluateStartRestore(_state: StartState, result: OperationResult): StartDecision {
  const commands: LifecycleCommand[] = [{ type: "completeStatus", result }];
  if (result.status === "failed") {
    commands.push({ type: "notifyFailure", result });
  }
  return {
    commands,
    stateUpdates: { retainPreGameWatch: result.status !== "failed" }
  };
}

export function evaluateStartConflictResolution(state: StartState, resolution: ConflictResolution | null, result?: OperationResult): StartDecision {
  if (!resolution) {
    return {
      commands: [{ type: "completeStatus", result: { status: "skipped", game: state.name, reason: "conflict_unresolved" } }],
      stateUpdates: {}
    };
  }
  
  if (!result) {
    return {
      commands: [{ type: "publishStatus", status: resolution === "restore_backup" ? "restoring" : "backing_up" }],
      stateUpdates: {}
    };
  }
  
  const commands: LifecycleCommand[] = [{ type: "completeStatus", result }];
  if (result.status === "failed") {
    commands.push({ type: "notifyFailure", result });
  }
  return {
    commands,
    stateUpdates: { retainPreGameWatch: result.status !== "failed" }
  };
}

export function getStartCleanup(state: StartState): CleanupCommand[] {
  const cleanup: CleanupCommand[] = [];
  if (!state.retainPreGameWatch && state.watchActive) {
    cleanup.push({ type: "cancelWatch", reason: "start_handler_cleanup" });
  }
  if (state.paused && state.instanceID !== undefined) {
    cleanup.push({ type: "resumeProcess", instanceID: state.instanceID });
  }
  cleanup.push({ type: "syncHistory" });
  return cleanup;
}

export function evaluateExitCheck(_state: ExitState, checkResult: LifecycleCheckResult): ExitDecision {
  if (checkResult.status === "skipped" && SILENT_SKIPPED_REASONS.indexOf(checkResult.reason ?? "") !== -1) {
    return {
      commands: [{ type: "hideStatus", resultStatus: checkResult.status }],
      stateUpdates: {}
    };
  }

  if (checkResult.status === "needed" && checkResult.operation === "backup") {
    return {
      commands: [{ type: "publishStatus", status: "backing_up" }],
      nextRpc: "backup",
      stateUpdates: {}
    };
  }

  const commands: LifecycleCommand[] = [{ type: "completeStatus", result: checkResult }];
  if (checkResult.status === "failed") {
    commands.push({ type: "notifyFailure", result: checkResult });
  }
  return {
    commands,
    stateUpdates: {}
  };
}

export function evaluateExitBackup(_state: ExitState, result: OperationResult): ExitDecision {
  if (result.status === "backed_up") {
    return {
      commands: [{ type: "publishStatus", status: "has_backup" }],
      nextRpc: "handoff",
      stateUpdates: {}
    };
  }

  const commands: LifecycleCommand[] = [{ type: "completeStatus", result }];
  if (result.status === "failed") {
    commands.push({ type: "notifyFailure", result });
  }
  return {
    commands,
    stateUpdates: {}
  };
}

export function evaluateExitHandoff(
  _state: ExitState, 
  handoff: PostGameHandoffResult, 
  backupResult: OperationResult,
  mappedUnavailableStatus: AutoSyncStatusKind | null
): ExitDecision {
  switch (handoff.status) {
    case "pending":
      return {
        commands: [{ type: "publishStatus", status: "syncthing_pending_upload" }],
        stateUpdates: { handoffTransferred: true }
      };
    case "uploading":
      return {
        commands: [{ type: "publishStatus", status: "syncthing_uploading" }],
        stateUpdates: { handoffTransferred: true }
      };
    case "complete":
      return {
        commands: [{ type: "publishStatus", status: "syncthing_complete" }],
        stateUpdates: { handoffTransferred: true }
      };
    case "unavailable": {
      if (mappedUnavailableStatus) {
        return {
          commands: [{ type: "publishStatus", status: mappedUnavailableStatus, resultStatus: backupResult.status }],
          stateUpdates: {}
        };
      }
      return {
        commands: [{ type: "completeStatus", result: backupResult }],
        stateUpdates: {}
      };
    }
    case "stale":
      return {
        commands: [{ type: "completeStatus", result: backupResult }],
        stateUpdates: {}
      };
  }
  return { commands: [], stateUpdates: {} };
}

export function getExitCleanup(state: ExitState): CleanupCommand[] {
  const cleanup: CleanupCommand[] = [];
  if (!state.handoffTransferred && state.watchActive) {
    cleanup.push({ type: "cancelWatch", reason: "exit_handler_cleanup" });
  }
  cleanup.push({ type: "syncHistory" });
  return cleanup;
}
