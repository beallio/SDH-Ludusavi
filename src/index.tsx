import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  ToggleField,
  Spinner,
  Router,
  SingleDropdownOption
} from "@decky/ui";
import {
  callable,
  definePlugin,
  toaster,
  useQuickAccessVisible
} from "@decky/api";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FaSave, FaDownload, FaExclamationTriangle } from "react-icons/fa";
import { IoMdRefresh } from "react-icons/io";

import { launchLudusavi, LudusaviLaunchCommand } from "./ludusaviLauncher";

import {
  NotificationSettings,
  NotificationCategory,
  Settings,
  GameOperationHistory,
  GameStatus,
  RefreshResult,
  OperationStatus,
  OperationResult,
  ConflictResolution,
  LifecycleCheckResult,
  ProcessSignalResult,
  AppLifetimeNotification,
  RunningSession,
  RpcStatus,
  RpcResult,
  AutoSyncStatusKind,
  AutoSyncStatusSource,
  AutoSyncStatusState,
  AutoSyncStatusBrowserView,
  AutoSyncStatusBrowserViewOwner,
  Versions,
  LogEntry,
  UpdateChannel
} from "./types";
import { LogModal, LudusaviLogModal } from "./components/LogModal";
import { PluginUpdateSection } from "./components/PluginUpdateSection";
import { formatConflictTime, formatDateMDY, formatTime12h } from "./formatting/dateTime";
import { getLastOperationText, summarizeOperationResult } from "./formatting/operationText";
import { log } from "./utils/logging";
import {
  LudusaviStateProvider,
  LudusaviStateStore,
  createLudusaviStateStore,
  defaultNotificationSettings,
  defaultSettings,
  useLudusaviState,
  useLudusaviStateStore
} from "./state/ludusaviState";
import {
  getInstalledAppIdsString,
  sessionFromAppOverview,
  getMainRunningSession,
  captureSteamUiGameContext,
  getPreferredSteamGameSession,
  findGameForRunningSession,
  logCurrentGameSelection,
  logCurrentGameNoMatch,
  resetQuickAccessScroll,
  getAutoSyncStatusBounds,
  objectKeys
} from "./utils/steam";




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




const getSettings = callable<[], RpcResult<Settings>>("get_settings");
const getGameHistoryCall = callable<[], RpcResult<Record<string, GameOperationHistory>>>("get_game_history");
const setAutoSyncEnabled = callable<[enabled: boolean], RpcResult<Settings>>("set_auto_sync_enabled");
const setNotificationSettings = callable<[settings: NotificationSettings], RpcResult<Settings>>("set_notification_settings");
const setSelectedGameCall = callable<[gameName: string], RpcResult<Settings>>("set_selected_game");
const refreshGamesCall = callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>("refresh_games");
const isGameCacheCurrentCall = callable<[installed_app_ids?: string], boolean>("is_game_cache_current");
const forceBackupCall = callable<[gameName: string], RpcResult<OperationResult>>("force_backup");
const forceRestoreCall = callable<[gameName: string], RpcResult<OperationResult>>("force_restore");
const getVersions = callable<[], RpcResult<Versions>>("get_versions");
const getOperationStatus = callable<[], OperationStatus>("get_operation_status");
const getRecentLogs = callable<[], LogEntry[]>("get_recent_logs");
const getLudusaviLogs = callable<[], RpcResult<string>>("get_ludusavi_logs");
const setUpdateChannelCall = callable<[channel: string], RpcResult<Settings>>("set_update_channel");
const setAutomaticUpdateChecksCall = callable<[enabled: boolean], RpcResult<Settings>>("set_automatic_update_checks");

const getLudusaviCommandCall = callable<[], RpcResult<LudusaviLaunchCommand | null>>("get_ludusavi_command");
const pauseGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("pause_game_process");
const resumeGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("resume_game_process");
const checkGameStartCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_start");
const restoreGameOnStartCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("restore_game_on_start");
const resolveGameStartConflictCall = callable<[gameName: string, app_id: string | undefined, resolution: ConflictResolution], RpcResult<OperationResult>>("resolve_game_start_conflict");
const checkGameExitCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_exit");
const backupGameOnExitCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("backup_game_on_exit");



const EMPTY_GAMES: readonly GameStatus[] = Object.freeze([]);

const statusLabels: Record<GameStatus["status"], string> = {
  configured: "Configured",
  has_backup: "Backup ready",
  needs_first_backup: "Needs first backup",
  error: "Error"
};

function SpinnerButton({ children, loading, ...props }: any) {
  return (
    <ButtonItem {...props} disabled={props.disabled || loading}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "10px" }}>
        {loading && <Spinner style={{ width: "18px", height: "18px", color: "#1a9fff" }} />}
        {children}
      </div>
    </ButtonItem>
  );
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



const autoSyncStatusText: Record<AutoSyncStatusKind, string> = {
  checking: "VERIFYING GAME SAVE",
  backing_up: "BACKING UP LOCAL SAVE",
  restoring: "RESTORING BACKUP SAVE",
  conflict: "SAVE CONFLICT",
  has_backup: "GAME SAVE UP TO DATE",
  unknown: "UNKNOWN",
  error: "UNABLE TO SYNC"
};

let currentAutoSyncStatusState: AutoSyncStatusState = {
  status: "has_backup",
  visible: false,
  source: "hide"
};
let autoSyncStatusTimedOut = false;
let autoSyncStatusHideTimeoutID: number | null = null;
let autoSyncStatusShowTimeoutID: number | null = null;
let autoSyncStatusSyncTimeoutID: number | null = null;
let autoSyncStatusShowGeneration = 0;
let autoSyncStatusBrowserView: AutoSyncStatusBrowserView | null = null;
let autoSyncStatusBrowserViewOwner: AutoSyncStatusBrowserViewOwner | null = null;

const AUTO_SYNC_STATUS_SHOW_DELAY = 100;

function getPrototypeKeys(value: unknown): string {
  if (typeof value !== "object" || value === null) {
    return "none";
  }
  const prototype = Object.getPrototypeOf(value);
  if (typeof prototype !== "object" || prototype === null) {
    return "none";
  }
  return Object.getOwnPropertyNames(prototype).join(",");
}

function browserViewMethod<T extends (...args: any[]) => void>(
  raw: any,
  upperName: string,
  lowerName: string,
): T | null {
  const method = raw[upperName] ?? raw[lowerName];
  return typeof method === "function" ? method.bind(raw) : null;
}

function buildBrowserViewAdapter(
  raw: any,
  owner: AutoSyncStatusBrowserViewOwner,
): AutoSyncStatusBrowserView | null {
  const loadURL = browserViewMethod<(url: string) => void>(raw, "LoadURL", "loadURL");
  const setBounds = browserViewMethod<
    (x: number, y: number, width: number, height: number) => void
  >(raw, "SetBounds", "setBounds");
  const setVisible = browserViewMethod<(visible: boolean) => void>(
    raw,
    "SetVisible",
    "setVisible",
  );

  if (!loadURL || !setBounds || !setVisible) {
    return null;
  }

  return {
    LoadURL: loadURL,
    SetBounds: setBounds,
    SetVisible: setVisible,
    SetFocus: browserViewMethod(raw, "SetFocus", "setFocus") ?? undefined,
    SetName: browserViewMethod(raw, "SetName", "setName") ?? undefined,
    SetTopmost: browserViewMethod(raw, "SetTopmost", "setTopmost") ?? undefined,
    SetWindowStackingOrder:
      browserViewMethod(raw, "SetWindowStackingOrder", "setWindowStackingOrder") ?? undefined,
    Destroy:
      raw === owner
        ? undefined
        : browserViewMethod(raw, "Destroy", "destroy") ?? undefined,
  };
}

function normalizeAutoSyncStatusBrowserView(
  candidate: AutoSyncStatusBrowserViewOwner | null,
): AutoSyncStatusBrowserView | null {
  const candidates: Array<[string, AutoSyncStatusBrowserViewOwner | undefined | null]> = [
    ["root", candidate],
    ["m_browserView", candidate?.m_browserView],
    ["browserView", candidate?.browserView],
    ["BrowserView", candidate?.BrowserView],
    ["m_browserView.m_browserView", candidate?.m_browserView?.m_browserView],
  ];

  if (!candidate) {
    return null;
  }

  for (const [source, view] of candidates) {
    if (!view) {
      continue;
    }
    const adapter = buildBrowserViewAdapter(view, candidate);
    if (adapter) {
      log("info", `BrowserView normalized from ${source}`, "autosync_status");
      return adapter;
    }
    log(
      "debug",
      `BrowserView candidate ${source} missing methods; keys=${objectKeys(view)} prototype=${getPrototypeKeys(view)}`,
      "autosync_status",
    );
  }

  return null;
}

function ensureAutoSyncStatusBrowserView(): AutoSyncStatusBrowserView | null {
  if (autoSyncStatusBrowserView) {
    return autoSyncStatusBrowserView;
  }

  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    const rootWindow = (Router as any).WindowStore?.GamepadUIMainWindowInstance;

    if (rootWindow?.CreateBrowserView) {
      log("info", "Creating BrowserView via GamepadUIMainWindowInstance", "autosync_status");
      autoSyncStatusBrowserViewOwner = rootWindow.CreateBrowserView(
        "sdh-ludusavi-autosync-status-strip",
      ) as AutoSyncStatusBrowserViewOwner;
    } else if (steamClient?.BrowserView?.Create) {
      log("info", "Creating BrowserView via SteamClient.BrowserView.Create", "autosync_status");
      autoSyncStatusBrowserViewOwner = steamClient.BrowserView.Create({
        strInitialURL: "about:blank"
      }) as AutoSyncStatusBrowserViewOwner | null;
    }

    if (!autoSyncStatusBrowserViewOwner) {
      log("error", "Failed to create BrowserView surface", "autosync_status");
      return null;
    }

    log(
      "info",
      `BrowserView created: type=${typeof autoSyncStatusBrowserViewOwner}, keys=${objectKeys(autoSyncStatusBrowserViewOwner)} prototype=${getPrototypeKeys(autoSyncStatusBrowserViewOwner)}`,
      "autosync_status",
    );

    const normalized = normalizeAutoSyncStatusBrowserView(autoSyncStatusBrowserViewOwner);
    if (!normalized) {
      log("warning", "Status strip BrowserView is missing required methods", "autosync_status");
      return null;
    }

    normalized.SetName?.("sdh-ludusavi-autosync-status-strip");
    normalized.SetWindowStackingOrder?.(50);
    normalized.SetFocus?.(false);
    normalized.SetVisible?.(false);

    normalized.SetTopmost?.(true);

    autoSyncStatusBrowserView = normalized;
    return autoSyncStatusBrowserView;
  } catch (err) {
    log("warning", `Could not create status strip BrowserView: ${err}`, "autosync_status");
    autoSyncStatusBrowserView = null;
    autoSyncStatusBrowserViewOwner = null;
    return null;
  }
}

function iconSvgForAutoSyncStatus(status: AutoSyncStatusKind) {
  if (status === "has_backup") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M6 10.2 8.5 12.7 14.2 7" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  if (status === "unknown") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M6 5h7l2 2v8H6z" fill="#0b151f"/><path d="M8 5h5v4H8z" fill="currentColor"/><path d="M8 12h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
  }
  if (status === "error") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M10 5.2v6.4" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/><circle cx="10" cy="15" r="1.2" fill="#0b151f"/></svg>';
  }
  if (status === "checking") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="3" opacity="0.8"/><path d="M10 2a8 8 0 0 1 8 8" fill="none" stroke="#0b151f" stroke-width="3" stroke-linecap="round"/></svg>';
  }

  const rotation = status === "restoring" ? ' style="transform: rotate(180deg); transform-origin: 50% 50%;"' : "";
  return `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"${rotation}><circle cx="10" cy="10" r="8.8" fill="currentColor"/><path d="M10 5.3v8.3" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/><path d="M6.8 8.4 10 5.2l3.2 3.2" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function renderAutoSyncStatusHtml(state: AutoSyncStatusState) {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; }
body {
  color: #f8fafc;
  font-family: "Motiva Sans", Arial, sans-serif;
  font-size: 13px;
  font-weight: 800;
  text-transform: uppercase;
}
.bar {
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(0, 0, 0, 0.34);
  border-top: 1px solid rgba(255, 255, 255, 0.10);
  padding: 0 18px;
  box-sizing: border-box;
}
.text { display: flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-width: 245px; }
.icon { width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; color: ${state.status === "error" ? "#ef4444" : state.status === "unknown" ? "#f59e0b" : "#1a9fff"}; }
@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
.icon-spin svg {
  animation: spin 1s linear infinite;
  transform-origin: 50% 50%;
}
</style>
</head>
<body>
<div class="bar">
  <div class="text"><span class="icon${state.status === "checking" ? " icon-spin" : ""}">${iconSvgForAutoSyncStatus(state.status)}</span>${autoSyncStatusText[state.status]}</div>
</div>
</body>
</html>`;
}

function syncAutoSyncStatusBrowserView(state: AutoSyncStatusState) {
  clearAutoSyncStatusShowTimeout();
  const showGeneration = ++autoSyncStatusShowGeneration;
  const browserView = ensureAutoSyncStatusBrowserView();
  if (!browserView) {
    return;
  }
  if (!browserView.LoadURL || !browserView.SetBounds || !browserView.SetVisible) {
    log("warning", "Status strip BrowserView is missing required methods", "autosync_status");
    return;
  }

  try {
    const bounds = getAutoSyncStatusBounds();
    const html = renderAutoSyncStatusHtml(state);
    const url = "data:text/html;charset=utf-8," + encodeURIComponent(html);
    
    log("debug", `Syncing BrowserView: visible=${state.visible}, bounds=${JSON.stringify(bounds)}`, "autosync_status");

    if (state.visible) {
      browserView.SetVisible(false);
      browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);
      browserView.LoadURL(url);
      
      autoSyncStatusShowTimeoutID = window.setTimeout(() => {
        autoSyncStatusShowTimeoutID = null;
        if (showGeneration !== autoSyncStatusShowGeneration || !currentAutoSyncStatusState.visible) {
          return;
        }
        browserView.SetVisible?.(true);
        browserView.SetWindowStackingOrder?.(50);
        browserView.SetFocus?.(false);
      }, AUTO_SYNC_STATUS_SHOW_DELAY);
    } else {
      browserView.SetVisible(false);
      try {
        browserView.LoadURL?.("about:blank");
      } catch (err) {
        log("debug", `Could not navigate BrowserView to blank: ${err}`, "autosync_status");
      }
    }
  } catch (err) {
    log("warning", `Could not update status strip BrowserView: ${err}`, "autosync_status");
  }
}

function destroyAutoSyncStatusBrowserView() {
  clearAutoSyncStatusSyncTimeout();
  clearAutoSyncStatusShowTimeout();
  try {
    const browserView = autoSyncStatusBrowserView;
    const browserViewOwner = autoSyncStatusBrowserViewOwner;
    if (!browserView && !browserViewOwner) {
      return;
    }
    browserView?.SetVisible?.(false);
    let needsSteamClientDestroy = true;
    if (browserView && browserView !== browserViewOwner && typeof browserView.Destroy === "function") {
      browserView.Destroy();
      if (!browserViewOwner) {
        needsSteamClientDestroy = false;
      }
    }
    if (typeof browserViewOwner?.Destroy === "function") {
      browserViewOwner.Destroy();
      needsSteamClientDestroy = false;
    }
    if (needsSteamClientDestroy && browserViewOwner) {
      const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
      steamClient?.BrowserView?.Destroy?.(browserViewOwner);
    }
  } catch (err) {
    log("warning", `Could not destroy status strip BrowserView: ${err}`, "autosync_status");
  } finally {
    autoSyncStatusBrowserView = null;
    autoSyncStatusBrowserViewOwner = null;
  }
}

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

function clearAutoSyncStatusHideTimeout() {
  if (autoSyncStatusHideTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusHideTimeoutID);
  autoSyncStatusHideTimeoutID = null;
}

function clearAutoSyncStatusShowTimeout() {
  if (autoSyncStatusShowTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusShowTimeoutID);
  autoSyncStatusShowTimeoutID = null;
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
  destroyAutoSyncStatusBrowserView();
}

function scheduleAutoSyncStatusHide(state: AutoSyncStatusState) {
  clearAutoSyncStatusHideTimeout();
  if (!state.visible) {
    return;
  }

  const isRunning = state.status === "checking" || state.status === "backing_up" || state.status === "restoring";
  autoSyncStatusHideTimeoutID = window.setTimeout(() => {
    if (isRunning) {
      autoSyncStatusTimedOut = true;
    }
    hideAutoSyncStatus({
      source: "timeout",
      gameName: currentAutoSyncStatusState.gameName,
      appID: currentAutoSyncStatusState.appID,
      tracked: currentAutoSyncStatusState.tracked,
      resultStatus: currentAutoSyncStatusState.resultStatus
    });
  }, isRunning ? 10000 : 2000);
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

function publishAutoSyncStatus(status: AutoSyncStatusKind, options: AutoSyncStatusPublishOptions) {
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
  logAutoSyncStatusChange(currentAutoSyncStatusState);
  if (shouldResetSurface) {
    syncAutoSyncStatusBrowserViewDeferred(currentAutoSyncStatusState);
    return;
  }
  clearAutoSyncStatusSyncTimeout();
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
  scheduleAutoSyncStatusHide(currentAutoSyncStatusState);
}

function hideAutoSyncStatus(options: Partial<AutoSyncStatusPublishOptions> = {}) {
  clearAutoSyncStatusSyncTimeout();
  clearAutoSyncStatusHideTimeout();
  clearAutoSyncStatusShowTimeout();
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
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
}

function completeAutoSyncStatus(
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
  }
}



type ConflictResolutionModalProps = {
  conflict: LifecycleCheckResult;
  onChoose: (resolution: ConflictResolution) => void;
  onDismiss: () => void;
  closeModal?: () => void;
};

function ConflictResolutionModal({ conflict, onChoose, onDismiss, closeModal }: ConflictResolutionModalProps) {
  const choose = (resolution: ConflictResolution) => {
    closeModal?.();
    onChoose(resolution);
  };
  const dismiss = () => {
    closeModal?.();
    onDismiss();
  };
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Conflict Detected"
      onOK={dismiss}
      onCancel={dismiss}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px" }}>
        <div>
          Both your local save and backup save appear to have changed. Choose which version
          should be used before the game continues loading.
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <div>Keep Local Save: {formatConflictTime(conflict.localModifiedAt)}</div>
          <div>Restore Backup Save: {formatConflictTime(conflict.backupModifiedAt)}</div>
          {conflict.backupPath && <div>Backup path: {conflict.backupPath}</div>}
        </div>
        <ButtonItem layout="below" onClick={() => choose("keep_local")}>
          Keep Local Save
        </ButtonItem>
        <ButtonItem layout="below" onClick={() => choose("restore_backup")}>
          Restore Backup Save
        </ButtonItem>
      </div>
    </ConfirmModal>
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



function CompactFieldLabel({ children }: { children: ReactNode }) {
  return <span style={{ fontSize: "14px" }}>{children}</span>;
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

function isRpcStatus<T>(result: RpcResult<T>): result is RpcStatus {
  return (
    typeof result === "object" &&
    result !== null &&
    "status" in result &&
    ((result as RpcStatus).status === "skipped" || (result as RpcStatus).status === "failed")
  );
}

function logRpcStatus(result: RpcStatus, operation: string) {
  const level = result.status === "failed" ? "error" : "warning";
  const reason = result.reason ? ` (${result.reason})` : "";
  const message = result.message ?? `${operation} ${result.status}${reason}`;
  log(level, message, operation);
}

const settingsQueue: (() => Promise<void>)[] = [];
let settingsProcessing = false;
const queueListeners = new Set<(busy: boolean) => void>();

function subscribeQueue(listener: (busy: boolean) => void) {
  queueListeners.add(listener);
  try {
    listener(settingsProcessing || settingsQueue.length > 0);
  } catch (err) {
    log("error", `Initial queue listener call failed: ${err}`);
  }
  return () => {
    queueListeners.delete(listener);
  };
}

function notifyQueueListeners() {
  const busy = settingsProcessing || settingsQueue.length > 0;
  queueListeners.forEach((listener) => {
    try {
      listener(busy);
    } catch (err) {
      log("error", `Queue listener notification failed: ${err}`);
    }
  });
}

async function processSettingsQueue() {
  if (settingsProcessing) return;
  settingsProcessing = true;
  notifyQueueListeners();
  try {
    while (settingsQueue.length > 0) {
      const task = settingsQueue.shift();
      if (task) {
        try {
          await task();
        } catch (err) {
          log("error", `Settings update failed in queue: ${err}`);
          if (activeLudusaviStore) {
            notify(
              activeLudusaviStore,
              "failures_errors",
              "Settings Update Failed",
              err instanceof Error ? err.message : String(err),
              <FaExclamationTriangle />
            );
          }
        }
      }
      notifyQueueListeners();
    }
  } finally {
    settingsProcessing = false;
    notifyQueueListeners();
  }
}

function enqueueSettingsUpdate(task: () => Promise<void>) {
  settingsQueue.push(task);
  notifyQueueListeners();
  void processSettingsQueue();
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, errorMessage: string): Promise<T> {
  let timeoutId: number;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timeoutId = window.setTimeout(() => {
      reject(new Error(errorMessage));
    }, timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => {
    window.clearTimeout(timeoutId);
  });
}


let autoSyncSeq = 0;
let notificationSeq = 0;
let selectedGameSeq = 0;
let updateChannelSeq = 0;
let automaticUpdateChecksSeq = 0;
let lastPersistedAutoSync: boolean | null = null;
let lastPersistedNotifications: NotificationSettings | null = null;
let lastPersistedUpdateChannel: UpdateChannel | null = null;
let lastPersistedAutomaticUpdateChecks: boolean | null = null;
let lastPersistedSelectedGame: string | null = null;
let lastQueuedSelectedGame: string | null = null;
let activeLudusaviStore: LudusaviStateStore | null = null;

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

let activeInitPromise: Promise<OperationStatus> | null = null;
let activeMetadataPromise: Promise<void> | null = null;


function applySettingsGlobal(store: LudusaviStateStore, nextSettings: Settings) {
  activeLudusaviStore = store;
  const normalized = store.applySettings(nextSettings);
  if (normalized.auto_sync_enabled !== undefined) {
    lastPersistedAutoSync = normalized.auto_sync_enabled;
  }
  if (normalized.notifications) {
    lastPersistedNotifications = normalized.notifications;
  }
  if (normalized.selected_game !== undefined) {
    lastPersistedSelectedGame = normalized.selected_game;
  }
  if (normalized.update_channel !== undefined) {
    lastPersistedUpdateChannel = normalized.update_channel;
  }
  if (normalized.automatic_update_checks !== undefined) {
    lastPersistedAutomaticUpdateChecks = normalized.automatic_update_checks;
  }
  return normalized;
}

function Content() {
  const ludusaviState = useLudusaviState();
  const ludusaviStore = useLudusaviStateStore();
  const isQuickAccessVisible = useQuickAccessVisible();
  const qamContentRef = useRef<HTMLDivElement | null>(null);
  const wasQuickAccessVisible = useRef(false);
  const pendingCurrentGameSelection = useRef(false);
  const isMounted = useRef(true);
  const styleElement = useMemo(() => <style>{dropdownStyleEl.textContent}</style>, []);

  const settings = ludusaviState.settings ?? defaultSettings();
  const games = ludusaviState.games ?? EMPTY_GAMES;
  const gamesDropdownOptions = useMemo(() => {
    return games.map((game) => ({
      label: game.name,
      data: game.name
    }));
  }, [games]);
  const gameAliases = ludusaviState.gameAliases;
  const gameHistory = ludusaviState.gameHistory;
  const selectedGame = ludusaviState.selectedGame;
  const versions =
    ludusaviState.versions ?? {
      sdh_ludusavi: "Loading...",
      ludusavi: "Loading...",
      pyludusavi: "Loading...",
      decky: "Loading..."
    };
  const [operation, setOperation] = useState<OperationStatus>({
    is_running: false,
    name: null,
    game_name: null,
    last_result: null,
    last_error: null
  });
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [backgroundRefreshBusy, setBackgroundRefreshBusy] = useState(false);
  const [queueBusy, setQueueBusy] = useState(settingsProcessing || settingsQueue.length > 0);
  const ludusaviCommand = ludusaviState.ludusaviCommand;

  useEffect(() => {
    return subscribeQueue((busy) => {
      if (isMounted.current) {
        setQueueBusy(busy);
        if (!busy) {
          setBusyLabel((prev) => prev === "Updating settings" ? null : prev);
        }
      }
    });
  }, []);


  const syncSelectedGameCache = (nextSelectedGame: string) => {
    ludusaviStore.syncSelectedGameCache(nextSelectedGame);
  };

  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const selectedHistory = useMemo(() => {
    const history = gameHistory[selectedGame];
    return history?.last_operation ?? null;
  }, [gameHistory, selectedGame]);
  const isBusy = operation.is_running || busyLabel !== null || backgroundRefreshBusy || queueBusy;

  function selectCurrentSteamGameIfAvailable(
    currentGames: readonly GameStatus[],
    currentAliases: Record<string, string>
  ): boolean {
    const runningSession = getPreferredSteamGameSession();
    if (!runningSession) {
      logCurrentGameNoMatch(null, currentGames, currentAliases);
      return false;
    }

    const runningGame = findGameForRunningSession(currentGames, runningSession, currentAliases);
    if (!runningGame) {
      logCurrentGameNoMatch(runningSession, currentGames, currentAliases);
      return false;
    }

    ludusaviStore.setSelectedGame(runningGame.game.name);
    logCurrentGameSelection(
      runningSession,
      runningGame.game,
      runningGame.reason,
      currentGames,
      currentAliases
    );
    return true;
  }

  useEffect(() => {
    isMounted.current = true;
    lastQueuedSelectedGame = null;
    log("info", "Plugin mounted, starting initial load");
    void loadInitial();
    return () => {
      isMounted.current = false;
    };
  }, []);

  useEffect(() => {
    lastQueuedSelectedGame = selectedGame;
  }, [selectedGame]);

  useEffect(() => {
    if (isQuickAccessVisible && !wasQuickAccessVisible.current) {
      pendingCurrentGameSelection.current = true;
      const resetDelays = [50, 150, 350];
      resetQuickAccessScroll(qamContentRef.current);
      resetDelays.forEach((delay) => {
        window.setTimeout(() => resetQuickAccessScroll(qamContentRef.current, `qam_open_retry_${delay}`), delay);
      });
    }
    wasQuickAccessVisible.current = isQuickAccessVisible;
  }, [isQuickAccessVisible]);

  useEffect(() => {
    if (!isQuickAccessVisible || !pendingCurrentGameSelection.current || games.length === 0) {
      return;
    }

    selectCurrentSteamGameIfAvailable(games, gameAliases);
    pendingCurrentGameSelection.current = false;
  }, [gameAliases, games, isQuickAccessVisible]);

  useEffect(() => {
    if (isQuickAccessVisible) {
      return;
    }

    captureSteamUiGameContext();
    const contextIntervalID = window.setInterval(captureSteamUiGameContext, 500);
    return () => window.clearInterval(contextIntervalID);
  }, [isQuickAccessVisible]);

  const loadInitial = async () => {
    const isWarmed = ludusaviState.settings !== null && ludusaviState.games !== null;
    if (!isMounted.current) return;
    if (!isWarmed) {
      setBusyLabel("Loading");
    }
    setBackgroundRefreshBusy(isWarmed);

    fetchMetadata();

    if (!activeInitPromise) {
      log("debug", `Creating new initialization promise (warmed=${isWarmed})`);
      activeInitPromise = (async () => {
        const loadedSettings = await fetchInitialState();
        await synchronizeGameList(isWarmed, loadedSettings);
        return getOperationStatus();
      })();
    } else {
      log("debug", "Reusing in-flight initialization promise");
    }

    try {
      const loadedOperation = await activeInitPromise;
      if (isMounted.current) {
        setOperation(loadedOperation);
      }
    } catch (error) {
      log("error", `Initial load failed: ${error}`);
    } finally {
      activeInitPromise = null;
      if (isMounted.current) {
        setBackgroundRefreshBusy(false);
        setBusyLabel(null);
      }
    }
  };

  const fetchMetadata = () => {
    const snapshot = ludusaviStore.getSnapshot();
    if (snapshot.versions !== null && snapshot.ludusaviCommand !== null) {
      return;
    }
    if (activeMetadataPromise) {
      return;
    }
    // Load versions and commands in the background asynchronously.
    activeMetadataPromise = (async () => {
      try {
        const [versionsResult, commandResult] = await Promise.allSettled([
          getVersions(),
          getLudusaviCommandCall()
        ]);

        if (versionsResult.status === "fulfilled") {
          const loadedVersions = versionsResult.value;
          log("debug", `Loaded versions: ${JSON.stringify(loadedVersions)}`);
          if (isRpcStatus(loadedVersions)) {
            logRpcStatus(loadedVersions, "versions");
            ludusaviStore.setVersions({ message: loadedVersions.message || "Error" });
          } else {
            ludusaviStore.setVersions(loadedVersions);
          }
        } else {
          log("error", `Background load of versions failed: ${versionsResult.reason}`);
          ludusaviStore.setVersions({ message: "Error" });
        }

        if (commandResult.status === "fulfilled") {
          const loadedCommand = commandResult.value;
          log("debug", `Loaded command: ${JSON.stringify(loadedCommand)}`);
          if (isRpcStatus(loadedCommand)) {
            logRpcStatus(loadedCommand, "command discovery");
          } else {
            ludusaviStore.setLudusaviCommand(loadedCommand);
          }
        } else {
          log("error", `Background load of command failed: ${commandResult.reason}`);
        }
      } catch (err) {
        log("error", `fetchMetadata failed: ${err}`);
      } finally {
        activeMetadataPromise = null;
      }
    })();
  };

  const fetchInitialState = async (): Promise<RpcResult<Settings>> => {
    const [loadedSettings, loadedHistory] = await Promise.all([
        getSettings(),
        getGameHistoryCall()
      ]);

    log("debug", `Loaded settings: ${JSON.stringify(loadedSettings)}`);
    if (isRpcStatus(loadedSettings)) {
      logRpcStatus(loadedSettings, "settings");
    } else {
      applySettingsGlobal(ludusaviStore, loadedSettings);
    }

    if (isRpcStatus(loadedHistory)) {
      logRpcStatus(loadedHistory, "history");
    } else {
      ludusaviStore.setGameHistory(loadedHistory);
    }

    return loadedSettings;
  };

  const synchronizeGameList = async (isWarmed: boolean, loadedSettings: RpcResult<Settings>) => {
    log("debug", "Initializing game list (cached)");
    const installedAppIds = await getInstalledAppIdsString();
    const installedAppIdsChanged = ludusaviState.installedAppIds !== installedAppIds;

    const cacheCurrentResult = isWarmed && !installedAppIdsChanged ? await isGameCacheCurrentCall(installedAppIds) : false;

    const cacheCurrent = !isRpcStatus(cacheCurrentResult) && cacheCurrentResult === true;
    const preferredGame = isRpcStatus(loadedSettings) ? undefined : loadedSettings.selected_game;

    if (cacheCurrent && ludusaviState.games) {
      applyCachedRefreshResult(preferredGame);
    } else {
      const refreshed = await refreshGamesCall(false, installedAppIds);
      if (applyRefreshResult(refreshed, preferredGame)) {
        ludusaviStore.setInstalledAppIds(installedAppIds);
      }
    }
  };

  const applyCachedRefreshResult = (preferredGame?: string): boolean => {
    const cachedGames = ludusaviState.games;
    if (!cachedGames) {
      return false;
    }

    const cachedAliases = ludusaviState.gameAliases;

    if (selectCurrentSteamGameIfAvailable(cachedGames, cachedAliases)) {
      return true;
    }

    const target = preferredGame || selectedGame;
    if (target && cachedGames.some((game) => game.name === target)) {
      ludusaviStore.setSelectedGame(target);
      syncSelectedGameCache(target);
    } else {
      const firstGame = cachedGames[0]?.name ?? "";
      ludusaviStore.setSelectedGame(firstGame);
      syncSelectedGameCache(firstGame);
    }
    return true;
  };

  const applyRefreshResult = (result: RpcResult<RefreshResult>, preferredGame?: string): boolean => {
    if (isRpcStatus(result)) {
      logRpcStatus(result, "refresh");
      return false;
    }

    if (result.dependency_error) {
      log("error", `Ludusavi refresh failed: ${result.dependency_error}`, "refresh");
      notify(ludusaviStore, "failures_errors", "SDH-Ludusavi refresh failed", result.dependency_error, <FaExclamationTriangle />);
      return false;
    }

    log("debug", `Applying refresh result (${result.games.length} games, ${Object.keys(result.aliases || {}).length} aliases)`);
    ludusaviStore.applyRefreshResult(result);
    log("info", `Tracked ${ludusaviStore.getSnapshot().trackedNames.size} game names/aliases`);

    if (selectCurrentSteamGameIfAvailable(result.games, result.aliases || {})) {
      return true;
    }

    const target = preferredGame || selectedGame;
    if (target && result.games.some((game: GameStatus) => game.name === target)) {
      ludusaviStore.setSelectedGame(target);
      syncSelectedGameCache(target);
    } else {
      const firstGame = result.games[0]?.name ?? "";
      log("debug", `Defaulting selected game to ${firstGame}`);
      ludusaviStore.setSelectedGame(firstGame);
      syncSelectedGameCache(firstGame);
    }

    return true;
  };

  const refreshGames = async () => {
    log("info", "Manual refresh triggered");
    setBusyLabel("Refreshing games");
    try {
      const installedAppIds = await getInstalledAppIdsString();
      const result = await refreshGamesCall(true, installedAppIds);
      if (isRpcStatus(result)) {
        logRpcStatus(result, "refresh");
        notify(
          ludusaviStore,
          "failures_errors",
          "SDH-Ludusavi refresh failed",
          result.message || "Failed to refresh games",
          <FaExclamationTriangle />
        );
      } else if (applyRefreshResult(result)) {
        ludusaviStore.setInstalledAppIds(installedAppIds);
        notify(ludusaviStore, "refresh_status", "SDH-Ludusavi", "Ludusavi game status refreshed", <IoMdRefresh />);
        const operationStatus = await getOperationStatus();
        const recentLogs = await getRecentLogs();
        if (isMounted.current) {
          setOperation(operationStatus);
          setLogs(recentLogs);
        }
      }
    } catch (error) {
      log("error", `Manual refresh failed: ${error}`);
      notify(
        ludusaviStore,
        "failures_errors",
        "SDH-Ludusavi refresh failed",
        error instanceof Error ? error.message : String(error),
        <FaExclamationTriangle />
      );
    } finally {
      if (isMounted.current) {
        setBusyLabel(null);
      }
    }
  };

  const showLudusaviLogs = async () => {
    log("info", "Showing Ludusavi logs");
    try {
      const result = await getLudusaviLogs();
      const logs = typeof result === "string" ? result : result.message || `Failed to fetch logs: ${result.status}`;
      showModal(<LudusaviLogModal logs={logs} />);
    } catch (error) {
      log("error", `Failed to fetch Ludusavi logs: ${error}`);
      notify(ludusaviStore, "failures_errors", "SDH-Ludusavi", "Failed to fetch Ludusavi logs", <FaExclamationTriangle />);
    }
  };

  const showPluginLogs = async () => {
    try {
      log("debug", `Fetching plugin logs (cached=${logs.length})`, "logs");
      const currentLogs = await getRecentLogs();
      if (isMounted.current) {
        setLogs(currentLogs);
      }
      showModal(<LogModal logs={currentLogs} />);
    } catch (error) {
      log("error", `Failed to fetch plugin logs: ${error}`);
      notify(ludusaviStore, "failures_errors", "SDH-Ludusavi", "Failed to fetch plugin logs", <FaExclamationTriangle />);
    }
  };

  const toggleAutoSync = useCallback((enabled: boolean) => {
    const updateSeq = ++autoSyncSeq;
    ludusaviStore.setAutoSyncEnabled(enabled);
    if (isMounted.current) {
      setBusyLabel("Updating settings");
    }

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle auto-sync to ${enabled}`);
      let awaitFailed = false;
      const originalPromise = setAutoSyncEnabled(enabled).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setAutoSyncEnabled to ${enabled} succeeded`);
          if (updateSeq === autoSyncSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setAutoSyncEnabled to ${enabled}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting auto-sync timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === autoSyncSeq) {
          applySettingsGlobal(ludusaviStore, result);
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to toggle auto-sync: ${error}`);
        if (updateSeq === autoSyncSeq) {
          const fallback = lastPersistedAutoSync ?? false;
          ludusaviStore.setAutoSyncEnabled(fallback);
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
        }
      }
    });
  }, [ludusaviStore]);

  const toggleNotificationSetting = useCallback((key: keyof NotificationSettings, enabled: boolean) => {
    const updateSeq = ++notificationSeq;
    const previousNotifications = ludusaviStore.getSnapshot().settings?.notifications ?? defaultNotificationSettings;
    const nextNotifications = { ...previousNotifications, [key]: enabled };
    ludusaviStore.setNotificationSettings(nextNotifications);
    if (isMounted.current) {
      setBusyLabel("Updating settings");
    }

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle notification setting ${String(key)} to ${enabled}`);
      let awaitFailed = false;
      const originalPromise = setNotificationSettings(nextNotifications).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setNotificationSettings to ${JSON.stringify(nextNotifications)} succeeded`);
          if (updateSeq === notificationSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setNotificationSettings to ${JSON.stringify(nextNotifications)}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting notifications timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === notificationSeq) {
          applySettingsGlobal(ludusaviStore, result);
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to update notification settings: ${error}`);
        if (updateSeq === notificationSeq) {
          const fallback = lastPersistedNotifications ?? defaultNotificationSettings;
          ludusaviStore.setNotificationSettings(fallback);
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
        }
      }
    });
  }, [ludusaviStore]);

  const toggleUpdateChannel = useCallback((enabled: boolean) => {
    const channel = enabled ? "development" : "stable";
    const updateSeq = ++updateChannelSeq;
    ludusaviStore.setUpdateChannel(channel);
    if (isMounted.current) {
      setBusyLabel("Updating settings");
    }

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle update channel to ${channel}`);
      let awaitFailed = false;
      const originalPromise = setUpdateChannelCall(channel).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setUpdateChannel to ${channel} succeeded`);
          if (updateSeq === updateChannelSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setUpdateChannel to ${channel}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting update channel timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === updateChannelSeq) {
          applySettingsGlobal(ludusaviStore, result);
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to toggle update channel: ${error}`);
        if (updateSeq === updateChannelSeq) {
          const fallback = lastPersistedUpdateChannel ?? "stable";
          ludusaviStore.setUpdateChannel(fallback);
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
        }
      }
    });
  }, [ludusaviStore]);

  const toggleAutomaticUpdateChecks = useCallback((enabled: boolean) => {
    const updateSeq = ++automaticUpdateChecksSeq;
    ludusaviStore.setAutomaticUpdateChecks(enabled);
    if (isMounted.current) {
      setBusyLabel("Updating settings");
    }

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle automatic update checks to ${enabled}`);
      let awaitFailed = false;
      const originalPromise = setAutomaticUpdateChecksCall(enabled).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setAutomaticUpdateChecks to ${enabled} succeeded`);
          if (updateSeq === automaticUpdateChecksSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setAutomaticUpdateChecks to ${enabled}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting automatic checks timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === automaticUpdateChecksSeq) {
          applySettingsGlobal(ludusaviStore, result);
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to toggle automatic checks: ${error}`);
        if (updateSeq === automaticUpdateChecksSeq) {
          const fallback = lastPersistedAutomaticUpdateChecks ?? true;
          ludusaviStore.setAutomaticUpdateChecks(fallback);
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
        }
      }
    });
  }, [ludusaviStore]);

  const onGameChange = useCallback((data: SingleDropdownOption | string | null | undefined) => {
    const value = (typeof data === 'object' && data !== null) ? data.data : data;
    if (typeof value !== "string" || value.trim() === "") {
      log("warning", `onGameChange received invalid game selection value: ${String(value)}`);
      return;
    }
    const lastQueued = lastQueuedSelectedGame ?? ludusaviStore.getSnapshot().selectedGame;
    if (value === lastQueued) {
      return;
    }
    log("info", `Selected game changed to ${value}`);
    const updateSeq = ++selectedGameSeq;
    lastQueuedSelectedGame = value;
    ludusaviStore.setSelectedGame(value);
    if (isMounted.current) {
      setBusyLabel("Updating settings");
    }

    enqueueSettingsUpdate(async () => {
      log("info", `Executing selected game change to ${value}`);
      let awaitFailed = false;
      const originalPromise = setSelectedGameCall(value).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setSelectedGameCall to ${value} succeeded`);
          if (updateSeq === selectedGameSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setSelectedGameCall to ${value}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Selecting game timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === selectedGameSeq) {
          applySettingsGlobal(ludusaviStore, result);
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to persist selected game: ${error}`);
        if (updateSeq === selectedGameSeq) {
          const fallback = lastPersistedSelectedGame ?? "";
          ludusaviStore.setSelectedGame(fallback);
          lastQueuedSelectedGame = fallback;
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
        }
      }
    });
  }, [ludusaviStore]);

  const runForceOperation = async (
    label: "Backup" | "Restore",
    operationCall: (gameName: string) => Promise<RpcResult<OperationResult>>
  ) => {
    if (!selectedGame) {
      return;
    }
    log("info", `Triggering force ${label} for ${selectedGame}`, label, selectedGame);
    setBusyLabel(`${label} running`);
    const icon = label === "Backup" ? <FaSave /> : <FaDownload />;
    notify(ludusaviStore, "manual_operations", `SDH-Ludusavi ${label}`, `${label} started for ${selectedGame}`, icon);
    try {
      const result = await operationCall(selectedGame);
      log("info", `Force ${label} completed: ${JSON.stringify(result)}`, label, selectedGame);
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      const category = result.status === "failed" ? "failures_errors" : "manual_operations";
      notify(ludusaviStore, category, `SDH-Ludusavi ${label}`, summarizeOperationResult(result, label), resultIcon);
      const refreshed = await refreshGamesCall(false);
      const operationStatus = await getOperationStatus();
      const recentLogs = await getRecentLogs();
      
      applyRefreshResult(refreshed);
      if (isMounted.current) {
        setOperation(operationStatus);
        setLogs(recentLogs);
      }
    } catch (error) {
      log("error", `Force ${label} failed: ${error}`, label, selectedGame);
      notify(ludusaviStore, "failures_errors", `SDH-Ludusavi ${label} failed`, error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      if (isMounted.current) {
        setBusyLabel(null);
      }
    }
  };

  return (
    <div ref={qamContentRef} className="sdh-ludusavi-qam-container">
      {styleElement}

      <PanelSection title="GLOBAL">
        <PanelSectionRow>
          <ToggleField
            label="Automatic Sync"
            description="Runs Ludusavi automatically when configured games start or exit."
            bottomSeparator="none"
            checked={settings.auto_sync_enabled}
            disabled={isBusy}
            onChange={(enabled: boolean) => void toggleAutoSync(enabled)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            highlightOnFocus={true}
            disabled={isBusy}
            loading={busyLabel === "Refreshing games"}
            onClick={() => void refreshGames()}
          >
            Refresh Games
          </SpinnerButton>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="GAME">
        <PanelSectionRow>
          <div className="sdh-ludusavi-game-dropdown" style={{ width: "100%" }}>
            <DropdownItem
              layout="below"
              menuLabel="Select Game"
              highlightOnFocus={true}
              focusable={true}
              bottomSeparator="none"
              disabled={isBusy}
              rgOptions={gamesDropdownOptions}
              selectedOption={selectedGame}
              onChange={onGameChange}
              renderButtonValue={(value: any) => (
                <span className="sdh-ludusavi-game-dropdown-value">{value}</span>
              )}
            />
          </div>
        </PanelSectionRow>

        <PanelSectionRow>
          <Field
            highlightOnFocus={false}
            focusable={false}
            padding="standard"
            bottomSeparator="none"
            childrenLayout="below"
          >
            <div style={{ display: "flex", flexDirection: "column", gap: "6px", width: "100%" }}>
              {/* Status Row */}
              <div style={{ display: "flex", width: "100%", alignItems: "center", fontSize: "12px" }}>
                <span style={{ width: "110px", flexShrink: 0 }}>
                  <CompactFieldLabel>Status:</CompactFieldLabel>
                </span>
                <div style={{ flexGrow: 1, color: "#cbd5e1", minWidth: 0, textAlign: "left" }}>
                  {isBusy && busyLabel === "Loading" ? (
                    <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Loading game list...</span>
                  ) : isBusy && busyLabel === "Refreshing games" ? (
                    <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Game refresh in progress...</span>
                  ) : isBusy && busyLabel === "Backup running" ? (
                    <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Backup in progress...</span>
                  ) : isBusy && busyLabel === "Restore running" ? (
                    <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Restore in progress...</span>
                  ) : (
                    selectedStatus ? statusLabels[selectedStatus.status] : "No Ludusavi games found"
                  )}
                </div>
              </div>

              {/* Last Operation Row */}
              {selectedHistory && !isBusy && (
                <div style={{ display: "flex", width: "100%", alignItems: "baseline", fontSize: "12px" }}>
                  <span style={{ width: "110px", flexShrink: 0 }}>
                    <CompactFieldLabel>Last Operation:</CompactFieldLabel>
                  </span>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      flexGrow: 1,
                      minWidth: 0,
                      textAlign: "left"
                    }}
                  >
                    <div
                      style={{
                        color: selectedHistory.status === "failed" ? "#f87171" : "#cbd5e1",
                        whiteSpace: "normal",
                        wordBreak: "break-word"
                      }}
                    >
                      {getLastOperationText(
                        selectedHistory.status,
                        selectedHistory.reason,
                        selectedHistory.message
                      )}
                    </div>
                    {(() => {
                      if (!selectedHistory.timestamp) return null;
                      const parts = selectedHistory.timestamp.split(/[T ]/);
                      const timePart = parts[1]?.split(".")[0];
                      if (!timePart) return null;

                      return (
                        <div
                          style={{
                            fontSize: "12px",
                            opacity: 0.65,
                            marginTop: "2px",
                            fontVariantNumeric: "tabular-nums"
                          }}
                        >
                          ({formatDateMDY(selectedHistory.timestamp)} {formatTime12h(timePart)})
                        </div>
                      );
                    })()}
                  </div>
                </div>
              )}
            </div>
          </Field>
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            highlightOnFocus={true}
            bottomSeparator="none"
            disabled={isBusy || !selectedStatus}
            loading={busyLabel === "Backup running"}
            onClick={() => void runForceOperation("Backup", forceBackupCall)}
          >
            Force Backup
          </SpinnerButton>
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            highlightOnFocus={true}
            disabled={isBusy || selectedStatus?.status !== "has_backup"}
            loading={busyLabel === "Restore running"}
            onClick={() => void runForceOperation("Restore", forceRestoreCall)}
          >
            Force Restore
          </SpinnerButton>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Notifications">
        <PanelSectionRow>
          <ToggleField
            label="All Notifications"
            description="Enables or silences all SDH-Ludusavi toast notifications."
            bottomSeparator="standard"
            checked={settings.notifications.enabled}
            disabled={isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("enabled", enabled)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Manual Operations"
            description="Shows toasts for Force Backup and Force Restore results."
            bottomSeparator="standard"
            checked={settings.notifications.manual_operations}
            disabled={!settings.notifications.enabled || isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("manual_operations", enabled)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Refresh Status"
            description="Shows toasts when the game list refresh completes or fails."
            bottomSeparator="standard"
            checked={settings.notifications.refresh_status}
            disabled={!settings.notifications.enabled || isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("refresh_status", enabled)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Failures and Errors"
            description="Shows warning toasts when sync or Ludusavi operations fail."
            bottomSeparator="none"
            checked={settings.notifications.failures_errors}
            disabled={!settings.notifications.enabled || isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("failures_errors", enabled)}
          />
        </PanelSectionRow>
      </PanelSection>

      <LudusaviPanel ludusaviCommand={ludusaviCommand} isLoading={busyLabel === "Loading"} />

      <PanelSection title="Logs">
        <PanelSectionRow>
          <ButtonItem layout="below" bottomSeparator="none" onClick={() => void showPluginLogs()}>
            View Logs
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" bottomSeparator="standard" onClick={() => void showLudusaviLogs()}>
            View Ludusavi Logs
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PluginUpdateSection
        currentVersion={versions.sdh_ludusavi ?? "Unknown"}
        updateChannel={settings.update_channel}
        automaticUpdateChecks={settings.automatic_update_checks}
        onToggleUpdateChannel={toggleUpdateChannel}
        onToggleAutomaticUpdateChecks={toggleAutomaticUpdateChecks}
      />

      <PanelSection title="Versions">
        <PanelSectionRow>
          <Field highlightOnFocus={true} focusable={true} childrenLayout="below" padding="standard" bottomSeparator="none">
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-start",
                gap: "7px",
                minWidth: 0,
                textAlign: "left",
                fontSize: "14px",
                color: "#cbd5e1",
                paddingLeft: "10px"
              }}
            >
              <div>SDH-Ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>
              <div>Ludusavi: {versions.ludusavi ?? versions.message ?? "Unknown"}</div>
              <div>pyludusavi: {versions.pyludusavi ?? "Unknown"}</div>
              <div>Decky: {versions.decky ?? "Unknown"}</div>
            </div>
          </Field>
        </PanelSectionRow>
      </PanelSection>
    </div>
  );
};

function LudusaviPanel({ 
  ludusaviCommand,
  isLoading
}: { 
  ludusaviCommand: LudusaviLaunchCommand | null,
  isLoading: boolean
}) {
  const [status, setStatus] = useState<string | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);

  async function onLaunch() {
    try {
      setIsLaunching(true);
      setStatus("Launching Ludusavi...");

      if (!ludusaviCommand) {
        throw new Error("Ludusavi not found on system.");
      }

      await launchLudusavi(ludusaviCommand, { logger: log });

      setStatus("Ludusavi launch requested.");
      // Best-effort clear status after 3s
      setTimeout(() => setStatus(null), 3000);
    } catch (err) {
      console.error(err);
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLaunching(false);
    }
  }

  return (
    <PanelSection title="Ludusavi">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={onLaunch}
          disabled={isLaunching || !ludusaviCommand}
        >
          Launch
        </ButtonItem>
      </PanelSectionRow>

      {status && (
        <PanelSectionRow>
          <div style={{ color: "#60a5fa", fontSize: "14px", fontWeight: "bold", padding: "0 4px" }}>
            {status}
          </div>
        </PanelSectionRow>
      )}
      
      {!ludusaviCommand && !isLaunching && !isLoading && (
        <PanelSectionRow>
          <div style={{ color: "#ef4444", fontSize: "12px", padding: "0 4px" }}>
            Ludusavi not found. Please install it via Flatpak or add to PATH.
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

export default definePlugin(() => {
  console.log("SDH-Ludusavi plugin initializing");

  if (!dropdownStyleEl.parentNode) {
    document.head.appendChild(dropdownStyleEl);
  }

  const ludusaviStore = createLudusaviStateStore();
  activeLudusaviStore = ludusaviStore;
  const activeSessions = new Map<number, RunningSession>();
  let fallbackIntervalID: number | null = null;
  let fallbackPreviousAppID: string | null = null;
  let fallbackPreviousAppName: string | null = null;
  let lifecycleRegistration: unknown = null;

  const isTracked = (name: string, appID: string) => {
    return ludusaviStore.isTracked(
      name,
      appID,
      (reason, detail) => {
        if (reason === "appId") {
          log("debug", `Match found via AppID: ${detail}`);
        } else if (reason === "exact") {
          log("debug", `Match found via exact name: ${detail}`);
        } else if (reason === "substring") {
          log("debug", `Match found via substring: ${detail}`);
        }
      },
      (normalizedInput) => {
        log("debug", `No match for ${name} (${appID}) [normalized: ${normalizedInput}]`);
      }
    );
  };

  function shouldPublishAutoSyncStatusBeforeRpc(store: LudusaviStateStore, tracked: boolean) {
    return store.shouldPublishAutoSyncStatusBeforeRpc(tracked);
  }

  const handleAppStart = async (name: string, appID: string, instanceID?: number) => {
    const tracked = isTracked(name, appID);
    log("info", `App started: ${name} (${appID}) tracked=${tracked}`);
    let paused = false;
    
    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_start",
        gameName: name,
        appID,
        tracked
      });
    }

    try {
      const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
      const shouldPauseLaunch =
        autoSyncEnabled &&
        tracked &&
        typeof instanceID === "number" &&
        instanceID > 1;

      if (shouldPauseLaunch) {
        const pauseResult = await pauseGameProcessCall(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
          paused = true;
        }
      }

      log("info", `Calling check_game_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameStartCall(name, appID);
      log("info", `check_game_start result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      // Show result toast for all outcomes (restored, failed, conflict, or skipped)
      // unless auto-sync is completely disabled, another operation is running,
      // or the game simply isn't managed by Ludusavi (unmatched or ignored).
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        hideAutoSyncStatus({
          source: "hide",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        return;
      }

      if (checkResult.status === "needed" && checkResult.operation === "restore") {
        if (!paused) {
          const result: OperationResult = {
            status: "failed",
            game: name,
            message: "Launch gate unavailable; restore skipped while game is loading."
          };
          completeAutoSyncStatus(result, { gameName: name, appID, tracked });
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
          return;
        }
        publishAutoSyncStatus("restoring", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked
        });
        log("info", `Calling restore_game_on_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
        const result = await restoreGameOnStartCall(name, appID);
        log("info", `restore_game_on_start result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      if (checkResult.status === "conflict") {
        publishAutoSyncStatus("conflict", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        if (!paused) {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", "Launch gate unavailable; conflict resolution skipped while game is loading.", <FaExclamationTriangle />);
          return;
        }
        const resolution = await showConflictResolutionModal(checkResult);
        if (!resolution) {
          completeAutoSyncStatus({ status: "skipped", game: name, reason: "conflict_unresolved" }, { gameName: name, appID, tracked });
          return;
        }
        const result = await resolveGameStartConflictCall(checkResult.game ?? name, appID, resolution);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"), <FaExclamationTriangle />);
      }
    } catch (err) {
      log("error", `App start handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed"
      });
    } finally {
      if (paused && typeof instanceID === "number") {
        try {
          await resumeGameProcessCall(instanceID);
        } catch (err) {
          log("error", `Failed to resume game process ${instanceID}: ${err}`, "lifecycle", name);
        }
      }
      await syncGlobalHistory(ludusaviStore);
    }
  };

  const handleAppExit = async (name: string, appID: string) => {
    const tracked = isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);
    
    if (shouldPublishAutoSyncStatusBeforeRpc(ludusaviStore, tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_exit",
        gameName: name,
        appID,
        tracked
      });
    }
    
    try {
      log("info", `Calling check_game_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameExitCall(name, appID);
      log("info", `check_game_exit result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        hideAutoSyncStatus({
          source: "hide",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        return;
      }

      if (checkResult.status === "needed" && checkResult.operation === "backup") {
        publishAutoSyncStatus("backing_up", {
          source: "lifecycle_exit",
          gameName: name,
          appID,
          tracked
        });
        log("info", `Calling backup_game_on_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
        const result = await backupGameOnExitCall(name, appID);
        log("info", `backup_game_on_exit result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notify(ludusaviStore, "failures_errors", "SDH-Ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"), <FaExclamationTriangle />);
      }
    } catch (err) {
      log("error", `App exit handling failed for ${name} (${appID}): ${err}`, "lifecycle", name);
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: "failed"
      });
    } finally {
      await syncGlobalHistory(ludusaviStore);
    }
  };

  const findRunningSessionByAppID = (appID: string): RunningSession | null => {
    // Router.RunningApps lets Steam app lifetime events recover the display name.
    const runningApps = (Router as any).RunningApps;
    if (Array.isArray(runningApps)) {
      for (const app of runningApps) {
        const session = sessionFromAppOverview(app);
        if (session?.appID === appID) {
          return session;
        }
      }
    }

    const mainSession = getMainRunningSession();
    if (mainSession?.appID === appID) {
      return mainSession;
    }

    return null;
  };

  const findStartupSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const startupSession = activeSessions.get(-1) ?? null;
    if (!startupSession) {
      return null;
    }
    if (notification.unAppID === 0 || startupSession.appID === String(notification.unAppID)) {
      return startupSession;
    }
    return null;
  };

  const resolveLifetimeSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const existingSession = activeSessions.get(notification.nInstanceID);
    if (existingSession) {
      return existingSession;
    }

    if (!notification.bRunning) {
      const startupSession = findStartupSession(notification);
      if (startupSession) {
        return startupSession;
      }
    }

    if (notification.unAppID > 0) {
      const appID = String(notification.unAppID);
      const runningSession = findRunningSessionByAppID(appID);
      if (runningSession) {
        return runningSession;
      }
      return { appID, name: "" };
    }

    // unAppID may be 0 for non-Steam shortcuts, so fall back to Router state.
    return getMainRunningSession();
  };

  const handleLifetimeNotification = (notification: AppLifetimeNotification) => {
    try {
      const session = resolveLifetimeSession(notification);
      if (!session?.name) {
        log(
          "warning",
          `Could not resolve app lifetime notification: ${JSON.stringify(notification)}`,
          "lifecycle"
        );
        return;
      }

      if (notification.bRunning) {
        const startupSession = findStartupSession(notification);
        if (startupSession?.appID === session.appID) {
          activeSessions.delete(-1);
          activeSessions.set(notification.nInstanceID, session);
          log(
            "debug",
            `Promoted startup session for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name
          );
          return;
        }

        if (activeSessions.has(notification.nInstanceID)) {
          log(
            "debug",
            `Duplicate app start ignored for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name
          );
          return;
        }

        activeSessions.set(notification.nInstanceID, session);
        void handleAppStart(session.name, session.appID, notification.nInstanceID);
        return;
      }

      activeSessions.delete(notification.nInstanceID);
      const startupSession = activeSessions.get(-1);
      if (startupSession?.appID === session.appID) {
        activeSessions.delete(-1);
      }
      void handleAppExit(session.name, session.appID);
    } catch (err) {
      console.error("SDH-Ludusavi: app lifetime notification failed", err);
    }
  };

  const checkMainApp = () => {
    try {
      const mainApp = (Router as any).MainRunningApp;
      const currentAppID = mainApp?.appid ? String(mainApp.appid) : null;
      const currentAppName = mainApp?.display_name || null;

      if (currentAppID !== fallbackPreviousAppID) {
        // Change detected
        if (fallbackPreviousAppID && fallbackPreviousAppName) {
          void handleAppExit(fallbackPreviousAppName, fallbackPreviousAppID);
        }
        if (currentAppID && currentAppName) {
          void handleAppStart(currentAppName, currentAppID);
        }
        
        fallbackPreviousAppID = currentAppID;
        fallbackPreviousAppName = currentAppName;
      }
    } catch (err) {
      console.error("SDH-Ludusavi: watcher loop failed", err);
    }
  };

  const startFallbackPolling = () => {
    log("warning", "Steam app lifetime notifications unavailable; using Router polling", "lifecycle");
    fallbackIntervalID = window.setInterval(checkMainApp, 1000);
  };

  const reconcileStartupSession = () => {
    const session = getMainRunningSession();
    if (!session) {
      return;
    }

    activeSessions.set(-1, session);
    void handleAppStart(session.name, session.appID);
  };

  const unregisterLifecycleNotifications = () => {
    const registration = lifecycleRegistration as
      | { unregister?: () => void; Unregister?: () => void }
      | (() => void)
      | null;
    if (!registration) {
      return;
    }

    if (typeof registration === "function") {
      registration();
    } else if (typeof registration.unregister === "function") {
      registration.unregister();
    } else if (typeof registration.Unregister === "function") {
      registration.Unregister();
    }
  };

  const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
  const gameSessions = steamClient?.GameSessions;
  const registerLifetime = gameSessions?.RegisterForAppLifetimeNotifications;
  if (typeof registerLifetime === "function") {
    lifecycleRegistration = registerLifetime.call(gameSessions, (notification: AppLifetimeNotification) => {
      handleLifetimeNotification(notification);
    });
    reconcileStartupSession();
  } else {
    startFallbackPolling();
  }

  return {
    name: "SDH-Ludusavi",
    titleView: <div className="sdh-ludusavi-title">SDH-Ludusavi</div>,
    content: (
      <LudusaviStateProvider store={ludusaviStore}>
        <Content />
      </LudusaviStateProvider>
    ),
    icon: <PluginIcon />,
    alwaysRender: true,
    onDismount() {
      unregisterLifecycleNotifications();
      if (fallbackIntervalID !== null) {
        window.clearInterval(fallbackIntervalID);
      }
      activeSessions.clear();
      currentAutoSyncStatusState = {
        status: "has_backup",
        visible: false,
        source: "hide"
      };
      clearAutoSyncStatusHideTimeout();
      clearAutoSyncStatusSyncTimeout();
      clearAutoSyncStatusShowTimeout();
      destroyAutoSyncStatusBrowserView();

      if (dropdownStyleEl.parentNode) {
        dropdownStyleEl.parentNode.removeChild(dropdownStyleEl);
      }

      // Reset settings queue and tracking variables
      settingsQueue.length = 0;
      settingsProcessing = false;
      queueListeners.clear();
      autoSyncSeq = 0;
      notificationSeq = 0;
      selectedGameSeq = 0;
      updateChannelSeq = 0;
      automaticUpdateChecksSeq = 0;
      lastPersistedAutoSync = null;
      lastPersistedNotifications = null;
      lastPersistedUpdateChannel = null;
      lastPersistedAutomaticUpdateChecks = null;
      lastPersistedSelectedGame = null;
      lastQueuedSelectedGame = null;
      activeInitPromise = null;
      activeMetadataPromise = null;
      activeLudusaviStore = null;

      console.log("SDH-Ludusavi unloading");
    },
  };
});
