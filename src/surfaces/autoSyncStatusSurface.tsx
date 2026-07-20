import type {
  AutoSyncStatusKind,
  AutoSyncStatusSource,
  AutoSyncStatusState,
  LifecycleCheckResult,
  OperationResult,
  RpcStatus
} from "../types";
import { log } from "../utils/logging";
import { autoSyncStatusText, isSyncthingActiveStatus, shouldAutoHideStatus, iconSvgForAutoSyncStatus, isLudusaviRunningStatus, isSyncthingStatus } from "./autoSyncStatusRenderer";
import type { AutoSyncStatusBrowserViewApi } from "./autoSyncStatusBrowserView";

export { autoSyncStatusText, isSyncthingActiveStatus, shouldAutoHideStatus, iconSvgForAutoSyncStatus };

export const RUNNING_STATUS_HIDE_CEILING_MS = 930000;
export const RESULT_HIDE_DELAY_MS = 2000;
export const HAS_BACKUP_MIN_DWELL_MS = 900;

export type AutoSyncStatusPublishOptions = {
  source: AutoSyncStatusSource;
  lifecycle?: "lifecycle_start" | "lifecycle_exit";
  gameName?: string;
  appID?: string;
  tracked?: boolean;
  resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];
};

export type AutoSyncStatusCompleteOptions = Omit<
  AutoSyncStatusPublishOptions,
  "source" | "resultStatus"
> & {
  lifecycle: "lifecycle_start" | "lifecycle_exit";
};

export function createAutoSyncStatusSurface(statusView: AutoSyncStatusBrowserViewApi) {
  let currentAutoSyncStatusState: AutoSyncStatusState = {
    status: "has_backup",
    visible: false,
    source: "hide"
  };
  let autoSyncStatusShownAt: number | null = null;
  let deferredAutoSyncStatusState: AutoSyncStatusState | null = null;
  let deferredAutoSyncStatusTimeoutID: number | null = null;
  let autoSyncStatusTimedOut = false;
  let autoSyncStatusHideTimeoutID: number | null = null;
  let autoSyncStatusSyncTimeoutID: number | null = null;
  let currentHasBackupLifecycle: "lifecycle_start" | "lifecycle_exit" | null = null;

  function clearDeferredAutoSyncStatus() {
    if (deferredAutoSyncStatusTimeoutID !== null) {
      window.clearTimeout(deferredAutoSyncStatusTimeoutID);
      deferredAutoSyncStatusTimeoutID = null;
    }
    deferredAutoSyncStatusState = null;
  }

  function logAutoSyncStatusChange(state: AutoSyncStatusState) {
    log(
      "info",
      `Status update: source=${state.source} status=${state.status} visible=${state.visible} game=${state.gameName ?? "unknown"} app_id=${state.appID ?? "unknown"} tracked=${state.tracked ?? "unknown"} result=${state.resultStatus ?? "none"}`,
      "autosync_status",
      state.gameName
    );
  }

  function clearAutoSyncStatusHideTimeout() {
    if (autoSyncStatusHideTimeoutID === null) {
      return;
    }
    window.clearTimeout(autoSyncStatusHideTimeoutID);
    autoSyncStatusHideTimeoutID = null;
  }

  function clearAutoSyncStatusSyncTimeout() {
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
    statusView.destroy();
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

    const hideDelay = isRunning ? RUNNING_STATUS_HIDE_CEILING_MS : RESULT_HIDE_DELAY_MS;
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
      api.hide({
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
      statusView.sync(state);
      scheduleAutoSyncStatusHide(state);
      autoSyncStatusShownAt = Date.now();
    }, 0);
  }

  const api = {
    publish(status: AutoSyncStatusKind, options: AutoSyncStatusPublishOptions) {
      if (
        isSyncthingStatus(status) &&
        options.source === "lifecycle_exit" &&
        currentAutoSyncStatusState.status === "has_backup" &&
        currentAutoSyncStatusState.resultStatus === "backed_up" &&
        currentHasBackupLifecycle === "lifecycle_exit" &&
        currentAutoSyncStatusState.visible &&
        autoSyncStatusShownAt !== null &&
        Date.now() - autoSyncStatusShownAt < HAS_BACKUP_MIN_DWELL_MS
      ) {
        deferredAutoSyncStatusState = {
          status,
          visible: true,
          source: options.source,
          gameName: options.gameName,
          appID: options.appID,
          tracked: options.tracked,
          resultStatus: options.resultStatus
        };
        if (deferredAutoSyncStatusTimeoutID === null) {
          const remaining = HAS_BACKUP_MIN_DWELL_MS - (Date.now() - autoSyncStatusShownAt);
          deferredAutoSyncStatusTimeoutID = window.setTimeout(() => {
            const stateToApply = deferredAutoSyncStatusState;
            clearDeferredAutoSyncStatus();
            if (!stateToApply) return;
            currentAutoSyncStatusState = stateToApply;
            currentHasBackupLifecycle = null;
            statusView.setContext(currentAutoSyncStatusState);
            logAutoSyncStatusChange(currentAutoSyncStatusState);
            statusView.sync(currentAutoSyncStatusState);
            scheduleAutoSyncStatusHide(currentAutoSyncStatusState);
            autoSyncStatusShownAt = Date.now();
          }, remaining);
        }
        return;
      }

      clearDeferredAutoSyncStatus();
      currentHasBackupLifecycle = status === "has_backup" ? (options.lifecycle ?? null) : null;

      const shouldResetSurface = shouldResetStatusStripSurfaceBeforeVerification(status, options);
      if (isLudusaviRunningStatus(status)) {
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
      statusView.setContext(currentAutoSyncStatusState);
      logAutoSyncStatusChange(currentAutoSyncStatusState);
      if (shouldResetSurface) {
        syncAutoSyncStatusBrowserViewDeferred(currentAutoSyncStatusState);
        return;
      }
      clearAutoSyncStatusSyncTimeout();
      statusView.setContext(currentAutoSyncStatusState);
      statusView.sync(currentAutoSyncStatusState);
      scheduleAutoSyncStatusHide(currentAutoSyncStatusState);
      autoSyncStatusShownAt = Date.now();
    },

    hide(options: Partial<AutoSyncStatusPublishOptions> = {}) {
      clearDeferredAutoSyncStatus();
      currentHasBackupLifecycle = null;
      clearAutoSyncStatusSyncTimeout();
      clearAutoSyncStatusHideTimeout();
      
      statusView.setContext(currentAutoSyncStatusState);
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
      statusView.setContext(currentAutoSyncStatusState);
      statusView.sync(currentAutoSyncStatusState);
    },

    complete(
      result: OperationResult | LifecycleCheckResult,
      options: AutoSyncStatusCompleteOptions
    ) {
      if (result.status === "failed") {
        api.publish("error", {
          ...options,
          source: "rpc_result",
          resultStatus: result.status
        });
        return;
      }

      if (result.status === "conflict") {
        api.publish("conflict", {
          ...options,
          source: "rpc_result",
          resultStatus: result.status
        });
        return;
      }

      if (
        options.lifecycle === "lifecycle_start" &&
        result.status === "skipped" &&
        result.reason === "local_current" &&
        currentAutoSyncStatusState.visible &&
        (currentAutoSyncStatusState.status === "syncthing_downloading" ||
          currentAutoSyncStatusState.status === "syncthing_uploading")
      ) {
        log(
          "info",
          `Final status for result 'local_current' suppressed: active pre-game Syncthing status has precedence`,
          "autosync_status",
          options.gameName,
        );
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
        api.publish("has_backup", {
          ...options,
          source: "rpc_result",
          resultStatus: result.status
        });
        return;
      }

      if (result.status === "skipped") {
        if (result.reason === "conflict_unresolved") {
          api.publish("conflict_unresolved", {
            ...options,
            source: "rpc_result",
            resultStatus: result.status,
          });
          return;
        }
        if (result.reason === "game_sync_disabled") {
          // Published on both start and exit: the exit notice confirms no
          // backup ran. The exit handler suppresses the pre-check "checking"
          // publish for disabled games, so this replaces that flash rather
          // than following it.
          api.publish("game_sync_disabled", {
            ...options,
            source: "rpc_result",
            resultStatus: result.status,
          });
          return;
        }
        if (result.reason === "local_current") {
          api.publish("has_backup", {
            ...options,
            source: "rpc_result",
            resultStatus: result.status
          });
          return;
        }

        if (["ambiguous_recency", "game_error", "preview_failed"].includes(result.reason ?? "")) {
          api.publish("error", {
            ...options,
            source: "rpc_result",
            resultStatus: result.status
          });
          return;
        }

        api.publish("unknown", {
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
    },

    dispose() {
      clearDeferredAutoSyncStatus();
      currentHasBackupLifecycle = null;
      statusView.setContext(currentAutoSyncStatusState);
      currentAutoSyncStatusState = {
        status: "has_backup",
        visible: false,
        source: "hide"
      };
      
      clearAutoSyncStatusHideTimeout();
      clearAutoSyncStatusSyncTimeout();
      
      statusView.destroy();
    }
  };

  return api;
}
