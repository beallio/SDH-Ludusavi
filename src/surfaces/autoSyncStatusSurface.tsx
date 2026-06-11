import type {
  AutoSyncStatusKind,
  AutoSyncStatusSource,
  AutoSyncStatusState,
  LifecycleCheckResult,
  OperationResult,
  RpcStatus
} from "../types";
import { log } from "../utils/logging";
import { autoSyncStatusText, isSyncthingActiveStatus, shouldAutoHideStatus, iconSvgForAutoSyncStatus, isLudusaviRunningStatus } from "./autoSyncStatusRenderer";
import { syncAutoSyncStatusBrowserView, destroyAutoSyncStatusBrowserView, setBrowserViewSyncStateContext } from "./autoSyncStatusBrowserView";

export { autoSyncStatusText, isSyncthingActiveStatus, shouldAutoHideStatus, iconSvgForAutoSyncStatus };

let currentAutoSyncStatusState: AutoSyncStatusState = {
  status: "has_backup",
  visible: false,
  source: "hide"
};
let autoSyncStatusTimedOut = false;
let autoSyncStatusHideTimeoutID: number | null = null;
let autoSyncStatusSyncTimeoutID: number | null = null;
type AutoSyncStatusPublishOptions = {
  source: AutoSyncStatusSource;
  gameName?: string;
  appID?: string;
  tracked?: boolean;
  resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];
};

function logAutoSyncStatusChange(state: AutoSyncStatusState) {
  log(
    "info",
    `Status update: source=${state.source} status=${state.status} visible=${state.visible} game=${state.gameName ?? "unknown"} app_id=${state.appID ?? "unknown"} tracked=${state.tracked ?? "unknown"} result=${state.resultStatus ?? "none"}`,
    "autosync_status",
    state.gameName
  );
}

export function clearAutoSyncStatusHideTimeout() {
  if (autoSyncStatusHideTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusHideTimeoutID);
  autoSyncStatusHideTimeoutID = null;
}

export function clearAutoSyncStatusSyncTimeout() {
  if (autoSyncStatusSyncTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusSyncTimeoutID);
  autoSyncStatusSyncTimeoutID = null;
}

function shouldResetStatusStripSurfaceBeforeVerification(
  status: AutoSyncStatusKind,
  options: AutoSyncStatusPublishOptions
) {
  return (
    status === "checking" &&
    (options.source === "lifecycle_start" || options.source === "lifecycle_exit")
  );
}

function resetStatusStripSurfaceBeforeVerification() {
  destroyAutoSyncStatusBrowserView();
}

function scheduleAutoSyncStatusHide(state: AutoSyncStatusState) {
  clearAutoSyncStatusHideTimeout();
  if (!state.visible) {
    return;
  }

  const isRunning = isLudusaviRunningStatus(state.status);
  if (!shouldAutoHideStatus(state.status)) {
    return;
  }

  const hideDelay = isRunning ? 10000 : 2000;
  log(
    "debug",
    `Auto-hide scheduled in ${hideDelay}ms for status=${state.status}`,
    "autosync_status",
    state.gameName
  );
  autoSyncStatusHideTimeoutID = window.setTimeout(() => {
    if (isRunning) {
      autoSyncStatusTimedOut = true;
      log(
        "info",
        `Status bar timed out after ${hideDelay}ms while still '${currentAutoSyncStatusState.status}'; the final operation result will not be displayed`,
        "autosync_status",
        currentAutoSyncStatusState.gameName
      );
    }
    hideAutoSyncStatus({
      source: "timeout",
      gameName: currentAutoSyncStatusState.gameName,
      appID: currentAutoSyncStatusState.appID,
      tracked: currentAutoSyncStatusState.tracked,
      resultStatus: currentAutoSyncStatusState.resultStatus
    });
  }, hideDelay);
}

function syncAutoSyncStatusBrowserViewDeferred(state: AutoSyncStatusState) {
  clearAutoSyncStatusSyncTimeout();
  autoSyncStatusSyncTimeoutID = window.setTimeout(() => {
    autoSyncStatusSyncTimeoutID = null;
    if (state !== currentAutoSyncStatusState || !state.visible) {
      return;
    }
    syncAutoSyncStatusBrowserView(state);
    scheduleAutoSyncStatusHide(state);
  }, 0);
}

export function publishAutoSyncStatus(status: AutoSyncStatusKind, options: AutoSyncStatusPublishOptions) {
  const shouldResetSurface = shouldResetStatusStripSurfaceBeforeVerification(status, options);
  if (status === "backing_up" || status === "restoring") {
    autoSyncStatusTimedOut = false;
  }

  if (shouldResetSurface) {
    resetStatusStripSurfaceBeforeVerification();
  }

  currentAutoSyncStatusState = {
    status,
    visible: true,
    source: options.source,
    gameName: options.gameName,
    appID: options.appID,
    tracked: options.tracked,
    resultStatus: options.resultStatus
  };
  setBrowserViewSyncStateContext(currentAutoSyncStatusState);
  logAutoSyncStatusChange(currentAutoSyncStatusState);
  if (shouldResetSurface) {
    syncAutoSyncStatusBrowserViewDeferred(currentAutoSyncStatusState);
    return;
  }
  clearAutoSyncStatusSyncTimeout();
  setBrowserViewSyncStateContext(currentAutoSyncStatusState);
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
  scheduleAutoSyncStatusHide(currentAutoSyncStatusState);
}

export function hideAutoSyncStatus(options: Partial<AutoSyncStatusPublishOptions> = {}) {
  clearAutoSyncStatusSyncTimeout();
  clearAutoSyncStatusHideTimeout();
  
  setBrowserViewSyncStateContext(currentAutoSyncStatusState);
  currentAutoSyncStatusState = {
    ...currentAutoSyncStatusState,
    visible: false,
    source: options.source ?? "hide",
    gameName: options.gameName ?? currentAutoSyncStatusState.gameName,
    appID: options.appID ?? currentAutoSyncStatusState.appID,
    tracked: options.tracked ?? currentAutoSyncStatusState.tracked,
    resultStatus: options.resultStatus ?? currentAutoSyncStatusState.resultStatus
  };
  logAutoSyncStatusChange(currentAutoSyncStatusState);
  setBrowserViewSyncStateContext(currentAutoSyncStatusState);
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
}

export function completeAutoSyncStatus(
  result: OperationResult | LifecycleCheckResult,
  options: Omit<AutoSyncStatusPublishOptions, "source" | "resultStatus">
) {
  if (result.status === "failed") {
    publishAutoSyncStatus("error", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
    return;
  }

  if (result.status === "conflict") {
    publishAutoSyncStatus("conflict", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
    return;
  }

  if (autoSyncStatusTimedOut) {
    log(
      "info",
      `Final status for result '${result.status}' suppressed: status bar already timed out during the operation`,
      "autosync_status",
      options.gameName
    );
    return;
  }

  if (result.status === "backed_up" || result.status === "restored") {
    publishAutoSyncStatus("has_backup", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
    return;
  }

  if (result.status === "skipped") {
    if (result.reason === "local_current") {
      publishAutoSyncStatus("has_backup", {
        ...options,
        source: "rpc_result",
        resultStatus: result.status
      });
      return;
    }

    if (["ambiguous_recency", "game_error", "preview_failed"].includes(result.reason ?? "")) {
      publishAutoSyncStatus("error", {
        ...options,
        source: "rpc_result",
        resultStatus: result.status
      });
      return;
    }

    publishAutoSyncStatus("unknown", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
    return;
  }

  log(
    "debug",
    `No status bar update for unhandled result status '${result.status}'`,
    "autosync_status",
    options.gameName
  );
}

export function resetAutoSyncStatusSurface() {
  setBrowserViewSyncStateContext(currentAutoSyncStatusState);
  currentAutoSyncStatusState = {
    status: "has_backup",
    visible: false,
    source: "hide"
  };
  
  clearAutoSyncStatusHideTimeout();
  clearAutoSyncStatusSyncTimeout();
  
  destroyAutoSyncStatusBrowserView();
}
