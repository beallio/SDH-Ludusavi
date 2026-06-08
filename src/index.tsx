import { showModal } from "@decky/ui";
import { definePlugin, toaster } from "@decky/api";
import { FaExclamationTriangle } from "react-icons/fa";

import {
  backupGameOnExitCall,
  checkGameExitCall,
  checkGameStartCall,
  getGameHistoryCall,
  getSettings,
  pauseGameProcessCall,
  resolveGameStartConflictCall,
  restoreGameOnStartCall,
  resumeGameProcessCall,
  startSyncthingActivityWatchCall,
  getSyncthingActivityCall,
  stopSyncthingActivityWatchCall
} from "./api/ludusaviRpc";

import {
  NotificationCategory,
  ConflictResolution,
  LifecycleCheckResult,
  RpcStatus,
} from "./types";
import { ConflictResolutionModal } from "./components/modals/ConflictResolutionModal";
import {
  LudusaviContent,
  resetLudusaviContentLoadState
} from "./components/qam/LudusaviContent";
import { createGameLifecycleController } from "./controllers/gameLifecycleController";
import { isRpcStatus } from "./utils/rpc";
import { log } from "./utils/logging";
import {
  LudusaviStateProvider,
  LudusaviStateStore,
  createLudusaviStateStore
} from "./state/ludusaviState";
import {
  applySettingsGlobal,
  resetSettingsMutationController,
  setActiveSettingsStore
} from "./settings/settingsMutationController";
import {
  completeAutoSyncStatus,
  hideAutoSyncStatus,
  publishAutoSyncStatus,
  resetAutoSyncStatusSurface
} from "./surfaces/autoSyncStatusSurface";




async function syncGlobalHistory(store: LudusaviStateStore) {
  try {
    const historyRes = await getGameHistoryCall();
    if (!isRpcStatus(historyRes)) {
      store.setGameHistory(historyRes);
    }
  } catch (err) {
    log("error", `Failed to sync global history: ${err}`);
  }
}

function PluginIcon() {
  return (
    <svg
      viewBox="0 0 1536 1536"
      role="img"
      aria-label="SDH-Ludusavi"
      fill="currentColor"
      width="1em"
      height="1em"
      style={{ display: "block" }}
    >
      <circle cx="191" cy="192" r="71" />
      <circle cx="192" cy="478" r="71" />
      <rect x="120" y="708" width="144" height="707" rx="72" ry="72" />
      <rect x="120" y="1265" width="1332" height="150" rx="75" ry="75" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M496 216H1256C1304.6 216 1344 255.4 1344 304V1064C1344 1112.6 1304.6 1152 1256 1152H496C447.4 1152 408 1112.6 408 1064V304C408 255.4 447.4 216 496 216ZM552 360V1008H1200V360H552Z"
      />
      <circle cx="719" cy="527" r="71" />
      <circle cx="1031" cy="528" r="71" />
      <circle cx="719" cy="840" r="71" />
      <circle cx="1031" cy="840" r="71" />
    </svg>
  );
}

function showConflictResolutionModal(
  conflict: LifecycleCheckResult
): Promise<ConflictResolution | null> {
  return new Promise((resolve) => {
    let settled = false;
    const settle = (resolution: ConflictResolution | null) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(resolution);
    };
    showModal(
      <ConflictResolutionModal
        conflict={conflict}
        onChoose={(resolution) => settle(resolution)}
        onDismiss={() => settle(null)}
      />
    );
  });
}

function notify(
  store: LudusaviStateStore,
  category: NotificationCategory,
  title: string,
  body: string,
  logo?: any
) {
  log("debug", `notify call: category=${category}, title=${title}, body=${body}`, "autosync_status");
  if (!store.shouldShowNotification(category)) {
    log("debug", "notify skipped: disabled by settings", "autosync_status");
    return;
  }
  try {
    const toastObj = {
      title,
      body,
      duration: 3000,
      ...(logo ? { logo } : {})
    };
    toaster.toast(toastObj);
    log("debug", "notify successful: toast dispatched", "autosync_status");
  } catch (err) {
    log("error", `notify failed: ${err}`, "autosync_status");
  }
}


function logRpcStatus(result: RpcStatus, operation: string) {
  const level = result.status === "failed" ? "error" : "warning";
  const reason = result.reason ? ` (${result.reason})` : "";
  const message = result.message ?? `${operation} ${result.status}${reason}`;
  log(level, message, operation);
}

const dropdownStyleEl = document.createElement("style");
dropdownStyleEl.textContent = `
  /*
   * Temporary SteamOS workaround for the QAM dropdown long-name regression.
   * Scoped to prevent broad wildcard descendant side effects on Decky icons.
   * This workaround should be removed via git revert 9b3f9022319c8f628c2a78927f464bbb8d7bfb56 when SteamOS no longer requires it.
   */
  .sdh-ludusavi-game-dropdown {
    width: 100%;
    max-width: 100% !important;
    min-width: 0 !important;
  }
  .sdh-ludusavi-game-dropdown button {
    max-width: 100% !important;
    width: 100% !important;
    min-width: 0 !important;
  }
  .sdh-ludusavi-game-dropdown [class*="DropdownField" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownControl" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownButton" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownMenu" i],
  .sdh-ludusavi-game-dropdown [class*="dropdown" i],
  .sdh-ludusavi-game-dropdown [class*="button" i],
  .sdh-ludusavi-game-dropdown [focusable="true"],
  .sdh-ludusavi-game-dropdown [role="button"],
  .sdh-ludusavi-game-dropdown div {
    max-width: 100% !important;
    min-width: 0 !important;
  }
  .sdh-ludusavi-game-dropdown [class*="DropdownField" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownControl" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownButton" i],
  .sdh-ludusavi-game-dropdown [class*="DropdownMenu" i],
  .sdh-ludusavi-game-dropdown [class*="dropdown" i],
  .sdh-ludusavi-game-dropdown [class*="button" i],
  .sdh-ludusavi-game-dropdown [focusable="true"],
  .sdh-ludusavi-game-dropdown [role="button"] {
    width: 100% !important;
  }
  .sdh-ludusavi-game-dropdown-value {
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    display: inline-block !important;
  }
  .sdh-ludusavi-game-dropdown svg,
  .sdh-ludusavi-game-dropdown [class*="icon" i],
  .sdh-ludusavi-game-dropdown [class*="chevron" i],
  .sdh-ludusavi-game-dropdown [class*="arrow" i] {
    flex-shrink: 0 !important;
    min-width: fit-content !important;
    max-width: none !important;
  }
`;




export default definePlugin(() => {
  console.log("SDH-Ludusavi plugin initializing");

  if (!dropdownStyleEl.parentNode) {
    document.head.appendChild(dropdownStyleEl);
  }

  const ludusaviStore = createLudusaviStateStore();
  setActiveSettingsStore(ludusaviStore, (title, body) => {
    notify(ludusaviStore, "failures_errors", title, body, <FaExclamationTriangle />);
  });
  const lifecycleStateReady = (async () => {
    try {
      const settings = await getSettings();
      if (isRpcStatus(settings)) {
        logRpcStatus(settings, "startup settings");
        return;
      }
      if (ludusaviStore.getSnapshot().settings !== null) {
        log("debug", "Startup settings hydration skipped because state is already populated");
        return;
      }
      applySettingsGlobal(ludusaviStore, settings);
      log("info", "Lifecycle settings hydrated at plugin startup");
    } catch (err) {
      log("error", `Failed to hydrate lifecycle settings at plugin startup: ${err}`);
    }
  })();
  const lifecycleController = createGameLifecycleController({
    store: ludusaviStore,
    rpc: {
      checkGameStart: checkGameStartCall,
      restoreGameOnStart: restoreGameOnStartCall,
      resolveGameStartConflict: resolveGameStartConflictCall,
      checkGameExit: checkGameExitCall,
      backupGameOnExit: backupGameOnExitCall,
      pauseGameProcess: pauseGameProcessCall,
      resumeGameProcess: resumeGameProcessCall,
      startSyncthingActivityWatch: startSyncthingActivityWatchCall,
      getSyncthingActivity: getSyncthingActivityCall,
      stopSyncthingActivityWatch: stopSyncthingActivityWatchCall
    },
    statusSurface: {
      publish: publishAutoSyncStatus,
      hide: hideAutoSyncStatus,
      complete: completeAutoSyncStatus
    },
    resolveConflict: showConflictResolutionModal,
    notifyFailure: (title, body) => {
      notify(ludusaviStore, "failures_errors", title, body, <FaExclamationTriangle />);
    },
    syncGlobalHistory: () => syncGlobalHistory(ludusaviStore),
    ensureStateReady: () => lifecycleStateReady
  });
  lifecycleController.start();

  return {
    name: "SDH-Ludusavi",
    titleView: <div className="sdh-ludusavi-title">SDH-Ludusavi</div>,
    content: (
      <LudusaviStateProvider store={ludusaviStore}>
        <LudusaviContent
          dropdownCssText={dropdownStyleEl.textContent}
          notify={notify}
          isRpcStatus={isRpcStatus}
          logRpcStatus={logRpcStatus}
        />
      </LudusaviStateProvider>
    ),
    icon: <PluginIcon />,
    alwaysRender: true,
    onDismount() {
      lifecycleController.dispose();
      resetAutoSyncStatusSurface();

      if (dropdownStyleEl.parentNode) {
        dropdownStyleEl.parentNode.removeChild(dropdownStyleEl);
      }

      resetSettingsMutationController();
      resetLudusaviContentLoadState();

      console.log("SDH-Ludusavi unloading");
    },
  };
});
