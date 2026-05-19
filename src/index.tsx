import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  showModal,
  staticClasses,
  ToggleField,
  Spinner,
  Router,
  findModuleChild,
  EUIComposition
} from "@decky/ui";
import {
  callable,
  definePlugin,
  routerHook,
  toaster
} from "@decky/api";
import React, { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { FaSave, FaDownload, FaExclamationTriangle } from "react-icons/fa";
import {
  FaCircle,
  FaCircleArrowUp,
  FaCircleCheck,
  FaCircleExclamation,
  FaFloppyDisk
} from "react-icons/fa6";
import { IoMdRefresh } from "react-icons/io";
import { LuDatabaseBackup } from "react-icons/lu";

import { launchLudusavi, LudusaviLaunchCommand } from "./ludusaviLauncher";

type NotificationSettings = {
  enabled: boolean;
  manual_operations: boolean;
  refresh_status: boolean;
  failures_errors: boolean;
};

type NotificationCategory = keyof Omit<NotificationSettings, "enabled">;

type Settings = {
  auto_sync_enabled: boolean;
  selected_game: string;
  notifications: NotificationSettings;
};

type GameOperationHistoryEntry = {
  operation: "backup" | "restore" | "start" | "exit";
  trigger: "manual_backup" | "manual_restore" | "auto_start" | "auto_exit";
  status: "backed_up" | "restored" | "skipped" | "failed";
  reason: string | null;
  message: string | null;
  timestamp: string;
};

type GameOperationHistory = {
  last_backup: GameOperationHistoryEntry | null;
  last_restore: GameOperationHistoryEntry | null;
  last_skip: GameOperationHistoryEntry | null;
  last_failure: GameOperationHistoryEntry | null;
  last_operation: GameOperationHistoryEntry | null;
};

type GameStatus = {
  name: string;
  configured: boolean;
  has_backup: boolean;
  needs_first_backup: boolean;
  error: string | null;
  status: "configured" | "has_backup" | "needs_first_backup" | "error";
};

type RefreshResult = {
  games: GameStatus[];
  aliases: Record<string, string>;
  history: Record<string, GameOperationHistory>;
  dependency_error: string | null;
};

type OperationStatus = {
  is_running: boolean;
  name: string | null;
  game_name: string | null;
  last_result: string | null;
  last_error: string | null;
};

type OperationResult = {
  status: "backed_up" | "restored" | "skipped" | "failed";
  game?: string;
  reason?: string;
  message?: string;
};

type AppLifetimeNotification = {
  unAppID: number;
  nInstanceID: number;
  bRunning: boolean;
};

type RunningSession = {
  appID: string;
  name: string;
};

type RpcStatus = {
  status: "skipped" | "failed";
  reason?: string;
  message?: string;
};

type RpcResult<T> = T | RpcStatus;

type AutoSyncStatusKind = "backing_up" | "restoring" | "has_backup" | "needs_backup" | "error";

type AutoSyncStatusState = {
  status: AutoSyncStatusKind;
  visible: boolean;
};

type AutoSyncStatusListener = (state: AutoSyncStatusState) => void;

type UseUIComposition = (composition: EUIComposition) => { releaseComposition: () => void };

type AutoSyncStatusBrowserView = {
  LoadURL?: (url: string) => void;
  SetBounds?: (x: number, y: number, width: number, height: number) => void;
  SetFocus?: (value: boolean) => void;
  SetName?: (name: string) => void;
  SetVisible?: (value: boolean) => void;
  SetWindowStackingOrder?: (value: number) => void;
  Destroy?: () => void;
};

type Versions = {
  sdh_ludusavi?: string;
  ludusavi?: string;
  pyludusavi?: string;
  rclone?: string;
  status?: string;
  message?: string;
};

type LogEntry = {
  level: string;
  message: string;
  timestamp: string;
  operation: string | null;
  game_name: string | null;
};

type LogModalProps = {
  logs: LogEntry[];
  closeModal?: () => void;
};

type LudusaviLogModalProps = {
  logs: string;
  closeModal?: () => void;
};

const getSettings = callable<[], RpcResult<Settings>>("get_settings");
const setAutoSyncEnabled = callable<[enabled: boolean], RpcResult<Settings>>("set_auto_sync_enabled");
const setNotificationSettings = callable<[settings: NotificationSettings], RpcResult<Settings>>("set_notification_settings");
const setSelectedGameCall = callable<[gameName: string], RpcResult<Settings>>("set_selected_game");
const refreshGamesCall = callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>("refresh_games");
const forceBackupCall = callable<[gameName: string], RpcResult<OperationResult>>("force_backup");
const forceRestoreCall = callable<[gameName: string], RpcResult<OperationResult>>("force_restore");
const getVersions = callable<[], RpcResult<Versions>>("get_versions");
const getOperationStatus = callable<[], OperationStatus>("get_operation_status");
const getRecentLogs = callable<[], LogEntry[]>("get_recent_logs");
const getLudusaviLogs = callable<[], RpcResult<string>>("get_ludusavi_logs");
const logCall = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");
const getLudusaviCommandCall = callable<[], RpcResult<LudusaviLaunchCommand | null>>("get_ludusavi_command");
const handleGameStartCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("handle_game_start");
const handleGameExitCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("handle_game_exit");

const getInstalledAppIdsString = async (): Promise<string | undefined> => {
  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    if (!steamClient?.Apps?.GetInstalledApps) {
      return undefined;
    }
    const appsResult = steamClient.Apps.GetInstalledApps();
    const apps = appsResult instanceof Promise ? await appsResult : appsResult;
    
    if (!Array.isArray(apps)) return undefined;
    
    const appIds = apps
      .map((app: any) => parseInt(app?.appid ?? app?.nAppID ?? app?.unAppID ?? app?.id, 10))
      .filter((id: number) => !isNaN(id));
      
    appIds.sort((a, b) => a - b);
    return appIds.join(",");
  } catch (err) {
    return undefined;
  }
};

const log = (level: "info" | "debug" | "warning" | "error", message: string, operation?: string, gameName?: string) => {
  const prefix = `SDH-ludusavi${operation ? `:${operation}` : ""}${gameName ? ` [${gameName}]` : ""}`;
  const fullMsg = `${prefix}: ${message}`;
  
  console.log(fullMsg);

  void logCall(level, message, operation, gameName);
};

const statusLabels: Record<GameStatus["status"], string> = {
  configured: "Configured",
  has_backup: "Backup ready",
  needs_first_backup: "Needs first backup",
  error: "Error"
};

const defaultNotificationSettings: NotificationSettings = {
  enabled: true,
  manual_operations: true,
  refresh_status: true,
  failures_errors: true
};

const defaultSettings = (): Settings => ({
  auto_sync_enabled: false,
  selected_game: "",
  notifications: { ...defaultNotificationSettings }
});

function normalizeNotificationSettings(settings?: Partial<NotificationSettings>): NotificationSettings {
  return {
    enabled: typeof settings?.enabled === "boolean" ? settings.enabled : true,
    manual_operations: typeof settings?.manual_operations === "boolean" ? settings.manual_operations : true,
    refresh_status: typeof settings?.refresh_status === "boolean" ? settings.refresh_status : true,
    failures_errors: typeof settings?.failures_errors === "boolean" ? settings.failures_errors : true
  };
}

function normalizeSettings(settings: Settings): Settings {
  return {
    ...settings,
    notifications: normalizeNotificationSettings(settings.notifications)
  };
}

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

const autoSyncStatusText: Record<AutoSyncStatusKind, string> = {
  backing_up: "BACKUP: BACKING UP",
  restoring: "BACKUP: RESTORING",
  has_backup: "BACKUP: UP TO DATE",
  needs_backup: "BACKUP: NEEDED",
  error: "BACKUP: ERROR"
};

const autoSyncStatusListeners = new Set<AutoSyncStatusListener>();
const AUTO_SYNC_STATUS_COMPONENT = "sdh-ludusavi-autosync-status-strip";
let currentAutoSyncStatusState: AutoSyncStatusState = {
  status: "has_backup",
  visible: false
};
let autoSyncStatusTimedOut = false;
let autoSyncStatusBrowserView: AutoSyncStatusBrowserView | null = null;

const useUICompositionHook = findModuleChild((module: any) => {
  if (typeof module !== "object" || module === null) {
    return undefined;
  }

  for (const prop in module) {
    const candidate = module[prop];
    if (
      typeof candidate === "function" &&
      candidate.toString().includes("AddMinimumCompositionStateRequest") &&
      candidate.toString().includes("ChangeMinimumCompositionStateRequest") &&
      candidate.toString().includes("RemoveMinimumCompositionStateRequest") &&
      !candidate.toString().includes("m_mapCompositionStateRequests")
    ) {
      return candidate;
    }
  }

  return undefined;
});

if (useUICompositionHook) {
  log("info", "Composition hook found", "autosync_status");
} else {
  log("warning", "Composition hook NOT found; in-game overlay may fail", "autosync_status");
}

const useUIComposition: UseUIComposition =
  (useUICompositionHook as any) ??
  (() => ({
    releaseComposition: () => undefined
  }));

function getAutoSyncStatusBounds() {
  const rootWindow = (Router as any).WindowStore?.GamepadUIMainWindowInstance?.BrowserWindow;
  const viewWindow = rootWindow ?? window;
  const pixelRatio = window.devicePixelRatio || 1;
  const rawWidth = viewWindow?.innerWidth || viewWindow?.outerWidth || 1280;
  const rawHeight = viewWindow?.innerHeight || viewWindow?.outerHeight || 800;
  
  const width = Math.floor(rawWidth * pixelRatio);
  const viewHeight = Math.floor(rawHeight * pixelRatio);
  const height = Math.floor(24 * pixelRatio);
  
  log("debug", `Window dimensions: raw=${rawWidth}x${rawHeight}, ratio=${pixelRatio}, physical=${width}x${viewHeight}`, "autosync_status");

  return {
    x: 0,
    y: Math.floor(400 * pixelRatio), // Middle of screen for Strategy B
    width,
    height,
    pixelRatio
  };
}

function ensureAutoSyncStatusBrowserView(): AutoSyncStatusBrowserView | null {
  if (autoSyncStatusBrowserView) {
    return autoSyncStatusBrowserView;
  }

  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    const rootWindow = (Router as any).WindowStore?.GamepadUIMainWindowInstance;

    // Prefer SteamClient.BrowserView.Create as it returns the standard BrowserViewPopup
    if (steamClient?.BrowserView?.Create) {
      log("info", "Creating BrowserView via SteamClient.BrowserView.Create", "autosync_status");
      autoSyncStatusBrowserView = steamClient.BrowserView.Create({
        strInitialURL: "about:blank"
      }) as AutoSyncStatusBrowserView | null;
    } else if (rootWindow?.CreateBrowserView) {
      log("info", "Creating BrowserView via GamepadUIMainWindowInstance", "autosync_status");
      autoSyncStatusBrowserView = rootWindow.CreateBrowserView("sdh-ludusavi-autosync-status-strip") as AutoSyncStatusBrowserView;
    }

    if (!autoSyncStatusBrowserView) {
      log("error", "Failed to create BrowserView surface (no creation methods found)", "autosync_status");
      return null;
    }

    // Diagnostic logging for the created object
    log("info", `BrowserView created: type=${typeof autoSyncStatusBrowserView}, keys=${Object.keys(autoSyncStatusBrowserView).join(",")}`, "autosync_status");

    // Handle lowercase method fallbacks if necessary
    const view = autoSyncStatusBrowserView as any;
    if (!view.LoadURL && view.loadURL) view.LoadURL = view.loadURL;
    if (!view.SetBounds && view.setBounds) view.SetBounds = view.setBounds;
    if (!view.SetVisible && view.setVisible) view.SetVisible = view.setVisible;
    if (!view.Destroy && view.destroy) view.Destroy = view.destroy;

    autoSyncStatusBrowserView.SetName?.("sdh-ludusavi-autosync-status-strip");
    autoSyncStatusBrowserView.SetWindowStackingOrder?.(75);
    autoSyncStatusBrowserView.SetFocus?.(false);
    
    if (typeof (autoSyncStatusBrowserView as any).AddGlass === "function") {
      log("debug", "Applying AddGlass to BrowserView", "autosync_status");
      try {
        (autoSyncStatusBrowserView as any).AddGlass(true, "GlassAppearance_Standard");
      } catch (err) {
        log("warning", `AddGlass failed: ${err}`, "autosync_status");
      }
    }

    autoSyncStatusBrowserView.SetVisible?.(false);
    
    if (typeof (autoSyncStatusBrowserView as any).SetTopmost === "function") {
      (autoSyncStatusBrowserView as any).SetTopmost(true);
    }

    return autoSyncStatusBrowserView;
  } catch (err) {
    log("warning", `Could not create status strip BrowserView: ${err}`, "autosync_status");
    autoSyncStatusBrowserView = null;
    return null;
  }
}

function iconSvgForAutoSyncStatus(status: AutoSyncStatusKind) {
  if (status === "has_backup") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M6 10.2 8.5 12.7 14.2 7" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  if (status === "needs_backup") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M6 5h7l2 2v8H6z" fill="#0b151f"/><path d="M8 5h5v4H8z" fill="currentColor"/><path d="M8 12h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
  }
  if (status === "error") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M10 5.2v6.4" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/><circle cx="10" cy="15" r="1.2" fill="#0b151f"/></svg>';
  }

  const rotation = status === "restoring" ? ' style="transform: rotate(180deg); transform-origin: 50% 50%;"' : "";
  return `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"${rotation}><circle cx="10" cy="10" r="8.8" fill="currentColor"/><path d="M10 5.3v8.3" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/><path d="M6.8 8.4 10 5.2l3.2 3.2" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function renderAutoSyncStatusHtml(state: AutoSyncStatusState) {
  const color = state.status === "error" ? "rgba(255, 210, 210, 1.0)" : "rgba(255, 255, 255, 1.0)";
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; }
body {
  color: ${color};
  font-family: "Motiva Sans", Arial, sans-serif;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
  white-space: nowrap;
}
.bar {
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 0, 0, 0.85); /* RED DEBUG MIDDLE */
  pointer-events: none;
  border-top: 2px solid white;
  border-bottom: 2px solid white;
}
.rule { height: 4px; flex: 1; background: white; }
.content { min-width: 245px; display: flex; align-items: center; justify-content: center; gap: 12px; }
.icon { width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center; }
.text { font-size: 18px; line-height: 1; }
</style>
</head>
<body>
<div class="bar"><div class="rule"></div><div class="content"><span class="icon">${iconSvgForAutoSyncStatus(state.status)}</span><span class="text">STRATEGY B (RED): ${autoSyncStatusText[state.status]}</span></div><div class="rule"></div></div>
</body>
</html>`;
}

function syncAutoSyncStatusBrowserView(state: AutoSyncStatusState) {
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
    
    log("debug", `Syncing BrowserView: visible=${state.visible}, bounds=${JSON.stringify(bounds)}, htmlLen=${html.length}`, "autosync_status");

    // Hardened sequence: Bounds -> Load -> Visible
    browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);
    browserView.LoadURL(url);
    
    if (state.visible) {
      // Force visibility update
      browserView.SetVisible?.(false);
      setTimeout(() => {
        browserView.SetVisible?.(true);
        browserView.SetFocus?.(false);
      }, 150);
    } else {
      browserView.SetVisible(false);
    }
  } catch (err) {
    log("warning", `Could not update status strip BrowserView: ${err}`, "autosync_status");
  }
}

function destroyAutoSyncStatusBrowserView() {
  try {
    const browserView = autoSyncStatusBrowserView;
    if (!browserView) {
      return;
    }
    browserView.SetVisible?.(false);
    if (typeof browserView.Destroy === "function") {
      browserView.Destroy();
    } else {
      const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
      steamClient?.BrowserView?.Destroy?.(browserView);
    }
  } catch (err) {
    log("warning", `Could not destroy status strip BrowserView: ${err}`, "autosync_status");
  } finally {
    autoSyncStatusBrowserView = null;
  }
}

function publishAutoSyncStatus(status: AutoSyncStatusKind) {
  if (status === "backing_up" || status === "restoring") {
    autoSyncStatusTimedOut = false;
  }
  currentAutoSyncStatusState = { status, visible: true };
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
  for (const listener of autoSyncStatusListeners) {
    listener(currentAutoSyncStatusState);
  }
}

function hideAutoSyncStatus() {
  currentAutoSyncStatusState = { ...currentAutoSyncStatusState, visible: false };
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
  for (const listener of autoSyncStatusListeners) {
    listener(currentAutoSyncStatusState);
  }
}

function completeAutoSyncStatus(result: OperationResult) {
  if (result.status === "failed") {
    publishAutoSyncStatus("error");
    return;
  }

  if (autoSyncStatusTimedOut) {
    return;
  }

  if (result.status === "backed_up" || result.status === "restored") {
    publishAutoSyncStatus("has_backup");
    return;
  }

  if (result.status === "skipped") {
    publishAutoSyncStatus("needs_backup");
  }
}

function AutoSyncStatusIcon({ status }: { status: AutoSyncStatusKind }) {
  if (status === "backing_up" || status === "restoring") {
    return (
      <span style={{ transform: status === "restoring" ? "rotate(180deg)" : undefined }}>
        <FaCircleArrowUp />
      </span>
    );
  }

  if (status === "has_backup") {
    return <FaCircleCheck />;
  }

  if (status === "needs_backup") {
    return (
      <span style={{ position: "relative", width: "18px", height: "18px", display: "block" }}>
        <span style={{ position: "absolute", inset: 0, width: "18px", height: "18px" }}>
          <FaCircle />
        </span>
        <span
          style={{
            position: "absolute",
            inset: "4px",
            width: "10px",
            height: "10px",
            color: "rgba(0, 0, 0, 0.74)"
          }}
        >
          <FaFloppyDisk />
        </span>
      </span>
    );
  }

  return <FaCircleExclamation />;
}

function AutoSyncStatusComposition() {
  useUIComposition(EUIComposition.Notification);
  return null;
}

function AutoSyncStatusStrip() {
  const [state, setState] = useState<AutoSyncStatusState>(currentAutoSyncStatusState);

  useEffect(() => {
    const listener: AutoSyncStatusListener = (nextState) => {
      setState(nextState);
    };
    autoSyncStatusListeners.add(listener);
    return () => {
      autoSyncStatusListeners.delete(listener);
    };
  }, []);

  useEffect(() => {
    if (!state.visible) {
      return;
    }

    const isRunning = state.status === "backing_up" || state.status === "restoring";
    const timeout = window.setTimeout(() => {
      if (isRunning) {
        autoSyncStatusTimedOut = true;
      }
      currentAutoSyncStatusState = { ...currentAutoSyncStatusState, visible: false };
      syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
      setState((current) => ({ ...current, visible: false }));
    }, isRunning ? 10000 : 2000);

    return () => window.clearTimeout(timeout);
  }, [state.status, state.visible]);

  return (
    <>
      {state.visible && <AutoSyncStatusComposition />}
      {createPortal(
        <div
          style={{
            position: "fixed",
            top: "100px", // Top for Strategy A
            left: "0",
            width: "100vw",
            zIndex: 99999,
            pointerEvents: "none",
            transform: state.visible ? "translateY(0)" : "translateY(-100%)",
            transition: "transform 300ms ease-out",
          }}
        >
          <div
            style={{
              height: "40px",
              display: "flex",
              alignItems: "center",
              gap: "10px",
              background: "rgba(0, 0, 255, 0.85)", // BLUE DEBUG TOP
              borderBottom: "2px solid white",
              padding: "0 20px",
              color: "white",
              fontFamily: '"Motiva Sans", "Arial", sans-serif',
              fontSize: "18px",
              fontWeight: 800,
              textTransform: "uppercase",
            }}
          >
            <div style={{ height: "4px", flex: 1, background: "white" }} />
            <div
              style={{
                minWidth: "300px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "12px",
              }}
            >
              <AutoSyncStatusIcon status={state.status} />
              <div style={{ lineHeight: 1 }}>STRATEGY A (BLUE): {autoSyncStatusText[state.status]}</div>
            </div>
            <div style={{ height: "4px", flex: 1, background: "white" }} />
          </div>
        </div>,
        document.body
      )}
    </>
  );
}

function LogModal({ logs, closeModal }: LogModalProps) {
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Plugin Logs"
      onOK={closeModal}
      onCancel={closeModal}
    >
      <div
        style={{
          maxHeight: "60vh",
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          backgroundColor: "rgba(0, 0, 0, 0.3)",
          padding: "10px",
          borderRadius: "4px",
          userSelect: "text",
        }}
      >
        {logs.length === 0 ? "No recent logs" : logs.map(formatLogEntry).join("\n")}
      </div>
    </ConfirmModal>
  );
}

function LudusaviLogModal({ logs, closeModal }: LudusaviLogModalProps) {
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Ludusavi Logs"
      onOK={closeModal}
      onCancel={closeModal}
    >
      <div
        style={{
          maxHeight: "60vh",
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          backgroundColor: "rgba(0, 0, 0, 0.3)",
          padding: "10px",
          borderRadius: "4px",
          userSelect: "text",
        }}
      >
        {logs || "No Ludusavi logs available"}
      </div>
    </ConfirmModal>
  );
}

let trackedAppIDs = new Set<string>();
let trackedNames = new Set<string>();
let autoSyncNotificationsEnabled = false;
let notificationSettingsMirror: NotificationSettings = { ...defaultNotificationSettings };

/** Normalize a game name for fuzzy matching, mirroring backend _normalize. */
function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9.-]+/g, " ").trim();
}

function shouldShowNotification(category: NotificationCategory): boolean {
  return notificationSettingsMirror.enabled && notificationSettingsMirror[category];
}

function notify(category: NotificationCategory, title: string, body: string, logo?: any) {
  if (!shouldShowNotification(category)) {
    return;
  }
  try {
    log("debug", `Showing toast: ${title} - ${body}`);
    const toastObj = { 
      title, 
      body, 
      logo: logo ? React.cloneElement(logo, { size: 40 }) : undefined,
      duration: 2000 
    };
    
    // Attempt standard toaster
    toaster.toast(toastObj);
    
  } catch (err) {
    log("error", `Failed to show toast: ${err}`);
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

let globalSettings: Settings | null = null;
let globalGames: GameStatus[] | null = null;
let globalGameHistory: Record<string, GameOperationHistory> | null = null;
let globalVersions: Versions | null = null;
let globalLudusaviCommand: LudusaviLaunchCommand | null = null;

function Content() {
  const [settings, setSettings] = useState<Settings>(globalSettings ?? defaultSettings());
  const [games, setGames] = useState<GameStatus[]>(globalGames ?? []);
  const [gameHistory, setGameHistory] = useState<Record<string, GameOperationHistory>>(globalGameHistory ?? {});
  const [selectedGame, setSelectedGame] = useState(globalSettings?.selected_game ?? "");
  const [versions, setVersions] = useState<Versions>(globalVersions ?? {});
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
  const [ludusaviCommand, setLudusaviCommand] = useState<LudusaviLaunchCommand | null>(globalLudusaviCommand);

  const applySettings = (nextSettings: Settings) => {
    const normalized = normalizeSettings(nextSettings);
    setSettings(normalized);
    globalSettings = normalized;
    autoSyncNotificationsEnabled = normalized.auto_sync_enabled;
    notificationSettingsMirror = normalized.notifications;
    return normalized;
  };

  const syncSelectedGameCache = (nextSelectedGame: string) => {
    setSettings((current) => {
      const nextSettings = { ...current, selected_game: nextSelectedGame };
      globalSettings = globalSettings
        ? { ...globalSettings, selected_game: nextSelectedGame }
        : nextSettings;
      return nextSettings;
    });
  };

  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const selectedHistory = useMemo(() => {
    const history = gameHistory[selectedGame];
    return history?.last_operation ?? null;
  }, [gameHistory, selectedGame]);
  const isBusy = operation.is_running || busyLabel !== null || backgroundRefreshBusy;

  useEffect(() => {
    log("info", "Plugin mounted, starting initial load");
    void loadInitial();
  }, []);

  const loadInitial = async () => {
    const isWarmed = globalSettings !== null && globalGames !== null;
    if (!isWarmed) {
      setBusyLabel("Loading");
    }
    setBackgroundRefreshBusy(isWarmed);

    try {
      log("debug", `Starting initial load (warmed=${isWarmed})`);
      const [loadedSettings, loadedVersions, loadedCommand] = await Promise.all([
        getSettings(),
        getVersions(),
        getLudusaviCommandCall()
      ]);

      log("debug", `Loaded settings: ${JSON.stringify(loadedSettings)}`);
      if (isRpcStatus(loadedSettings)) {
        logRpcStatus(loadedSettings, "settings");
      } else {
        const normalizedSettings = applySettings(loadedSettings);
        if (normalizedSettings.selected_game) {
          setSelectedGame(normalizedSettings.selected_game);
        }
      }

      log("debug", `Loaded versions: ${JSON.stringify(loadedVersions)}`);
      if (isRpcStatus(loadedVersions)) {
        logRpcStatus(loadedVersions, "versions");
      } else {
        setVersions(loadedVersions);
        globalVersions = loadedVersions;
      }

      log("debug", `Loaded command: ${JSON.stringify(loadedCommand)}`);
      if (isRpcStatus(loadedCommand)) {
        // If discovery failed, keep existing cached command if any.
        logRpcStatus(loadedCommand, "command discovery");
      } else {
        globalLudusaviCommand = loadedCommand;
        setLudusaviCommand(loadedCommand);
      }

      log("debug", "Initializing game list (cached)");
      const installedAppIds = await getInstalledAppIdsString();
      const refreshed = await refreshGamesCall(false, installedAppIds);
      applyRefreshResult(refreshed, isRpcStatus(loadedSettings) ? undefined : loadedSettings.selected_game);

      const loadedOperation = await getOperationStatus();
      setOperation(loadedOperation);
      const loadedLogs = await getRecentLogs();
      setLogs(loadedLogs);
    } catch (error) {
      log("error", `Initial load failed: ${error}`);
      setLogs(await getRecentLogs().catch(() => []));
    } finally {
      setBackgroundRefreshBusy(false);
      setBusyLabel(null);
    }
  };

  const applyRefreshResult = (result: RpcResult<RefreshResult>, preferredGame?: string): boolean => {
    if (isRpcStatus(result)) {
      logRpcStatus(result, "refresh");
      return false;
    }

    if (result.dependency_error) {
      log("error", `Ludusavi refresh failed: ${result.dependency_error}`, "refresh");
      notify("failures_errors", "SDH-ludusavi refresh failed", result.dependency_error, <FaExclamationTriangle />);
      return false;
    }

    log("debug", `Applying refresh result (${result.games.length} games, ${Object.keys(result.aliases || {}).length} aliases)`);
    setGames(result.games);
    setGameHistory(result.history ?? {});
    globalGames = result.games;
    globalGameHistory = result.history ?? {};
    
    // Update global tracking sets for toast filtering
    trackedAppIDs = new Set(result.games.map(g => (g as any).steam_id).filter(id => !!id) as string[]);
    
    const names = new Set<string>();
    result.games.forEach(g => names.add(normalize(g.name)));
    Object.entries(result.aliases || {}).forEach(([alias, target]) => {
      names.add(normalize(alias));
      names.add(normalize(target));
    });
    trackedNames = names;
    
    log("info", `Tracked ${trackedNames.size} game names/aliases`);

    const target = preferredGame || selectedGame;
    if (target && result.games.some((game) => game.name === target)) {
      setSelectedGame(target);
      syncSelectedGameCache(target);
    } else {
      const firstGame = result.games[0]?.name ?? "";
      log("debug", `Defaulting selected game to ${firstGame}`);
      setSelectedGame(firstGame);
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
      if (applyRefreshResult(result)) {
        setOperation(await getOperationStatus());
        setLogs(await getRecentLogs());
        notify("refresh_status", "SDH-ludusavi", "Ludusavi game status refreshed", <IoMdRefresh />);
      }
    } catch (error) {
      log("error", `Manual refresh failed: ${error}`);
    } finally {
      setBusyLabel(null);
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
      notify("failures_errors", "SDH-ludusavi", "Failed to fetch Ludusavi logs", <FaExclamationTriangle />);
    }
  };

  const toggleAutoSync = async (enabled: boolean) => {
    log("info", `Toggling auto-sync to ${enabled}`);
    const previous = settings.auto_sync_enabled;
    setBusyLabel("Updating settings");
    
    // Optimistic update
    setSettings(s => ({ ...s, auto_sync_enabled: enabled }));
    autoSyncNotificationsEnabled = enabled;

    try {
      const result = await setAutoSyncEnabled(enabled);
      if (isRpcStatus(result)) {
        throw new Error(result.message || result.status);
      }
      applySettings(result);
    } catch (error) {
      log("error", `Failed to toggle auto-sync: ${error}`);
      // Rollback
      setSettings(s => ({ ...s, auto_sync_enabled: previous }));
      autoSyncNotificationsEnabled = previous;
      notify("failures_errors", "SDH-ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

  const toggleNotificationSetting = async (key: keyof NotificationSettings, enabled: boolean) => {
    log("info", `Toggling notification setting ${key} to ${enabled}`);
    const previous = settings.notifications;
    const nextNotifications = { ...previous, [key]: enabled };
    setBusyLabel("Updating settings");
    setSettings(s => ({ ...s, notifications: nextNotifications }));
    notificationSettingsMirror = nextNotifications;

    try {
      const result = await setNotificationSettings(nextNotifications);
      if (isRpcStatus(result)) {
        throw new Error(result.message || result.status);
      }
      applySettings(result);
    } catch (error) {
      log("error", `Failed to update notification settings: ${error}`);
      setSettings(s => ({ ...s, notifications: previous }));
      notificationSettingsMirror = previous;
      notify("failures_errors", "SDH-ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

  const onGameChange = async (data: any) => {
    const value = typeof data === 'object' ? data?.data : data;
    log("info", `Selected game changed to ${value}`);
    const previous = selectedGame;
    setBusyLabel("Updating settings");
    
    // Optimistic update
    setSelectedGame(value);

    try {
      const result = await setSelectedGameCall(value);
      if (isRpcStatus(result)) {
        throw new Error(result.message || result.status);
      }
      applySettings(result);
      setSelectedGame(result.selected_game);
    } catch (error) {
      log("error", `Failed to persist selected game: ${error}`);
      // Rollback
      setSelectedGame(previous);
      notify("failures_errors", "SDH-ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

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
    notify("manual_operations", `SDH-ludusavi ${label}`, `${label} started for ${selectedGame}`, icon);
    try {
      const result = await operationCall(selectedGame);
      log("info", `Force ${label} completed: ${JSON.stringify(result)}`, label, selectedGame);
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      const category = result.status === "failed" ? "failures_errors" : "manual_operations";
      notify(category, `SDH-ludusavi ${label}`, summarizeOperationResult(result, label), resultIcon);
      const refreshed = await refreshGamesCall(false);
      applyRefreshResult(refreshed);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
    } catch (error) {
      log("error", `Force ${label} failed: ${error}`, label, selectedGame);
      notify("failures_errors", `SDH-ludusavi ${label} failed`, error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

  return (
    <>
      <PanelSection title="Sync">
        <ToggleField
          label="Automatic Sync"
          checked={settings.auto_sync_enabled}
          disabled={isBusy}
          onChange={(enabled: boolean) => void toggleAutoSync(enabled)}
        />

        <PanelSectionRow>
          <DropdownItem
            menuLabel="Select Game"
            disabled={isBusy}
            rgOptions={games.map((game) => ({
              label: game.name,
              data: game.name
            }))}
            selectedOption={selectedGame}
            onChange={(data: any) => void onGameChange(data)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <div style={{ color: "#cbd5e1", fontSize: "14px", margin: "12px 0", padding: "0 4px" }}>
            <span style={{ color: "#64748b", fontWeight: "bold", marginRight: "8px" }}>Status:</span>
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
        </PanelSectionRow>

        {selectedHistory && !isBusy && (
          <PanelSectionRow>
            <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", fontSize: "12px", padding: "0 4px", opacity: 0.8, marginBottom: "8px" }}>
              <div style={{ fontWeight: "bold" }}>Last Operation:</div>
              <div style={{ textAlign: "right" }}>
                <span style={{ 
                  color: selectedHistory.status === "failed" ? "#f87171" : "#94a3b8" 
                }}>
                  {selectedHistory.status === "failed" ? "Failed" : 
                   selectedHistory.status === "backed_up" ? "Backed up" :
                   selectedHistory.status === "restored" ? "Restored" :
                   `Skipped${selectedHistory.reason ? ` (${selectedHistory.reason.replace(/_/g, " ")})` : ""}`}
                </span>
                <span style={{ marginLeft: "8px", fontSize: "10px", opacity: 0.6 }}>
                  {selectedHistory.timestamp.split(/[T ]/)[1]?.split(".")[0]}
                </span>
              </div>
            </div>
          </PanelSectionRow>
        )}

        <PanelSectionRow>
          <SpinnerButton 
            layout="below" 
            disabled={isBusy} 
            loading={busyLabel === "Refreshing games"}
            onClick={() => void refreshGames()}
          >
            Refresh Games
          </SpinnerButton>
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
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
            disabled={isBusy || selectedStatus?.status !== "has_backup"}
            loading={busyLabel === "Restore running"}
            onClick={() => void runForceOperation("Restore", forceRestoreCall)}
          >
            Force Restore
          </SpinnerButton>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Notifications">
        <ToggleField
          label="All Notifications"
          checked={settings.notifications.enabled}
          disabled={isBusy}
          onChange={(enabled: boolean) => void toggleNotificationSetting("enabled", enabled)}
        />
        <ToggleField
          label="Manual Operations"
          checked={settings.notifications.manual_operations}
          disabled={!settings.notifications.enabled || isBusy}
          onChange={(enabled: boolean) => void toggleNotificationSetting("manual_operations", enabled)}
        />
        <ToggleField
          label="Refresh Status"
          checked={settings.notifications.refresh_status}
          disabled={!settings.notifications.enabled || isBusy}
          onChange={(enabled: boolean) => void toggleNotificationSetting("refresh_status", enabled)}
        />
        <ToggleField
          label="Failures and Errors"
          checked={settings.notifications.failures_errors}
          disabled={!settings.notifications.enabled || isBusy}
          onChange={(enabled: boolean) => void toggleNotificationSetting("failures_errors", enabled)}
        />
      </PanelSection>

      <LudusaviPanel ludusaviCommand={ludusaviCommand} isLoading={busyLabel === "Loading"} />

      <PanelSection title="Logs">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<LogModal logs={logs} />)}>
            View Logs
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void showLudusaviLogs()}>
            View Ludusavi Logs
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Versions">
        <PanelSectionRow>
          <div style={{ color: "#cbd5e1", fontSize: "14px", display: "flex", flexDirection: "column", gap: "4px", padding: "12px", backgroundColor: "rgba(30, 41, 59, 0.3)", borderRadius: "4px" }}>
            <div>SDH-ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>
            <div>Ludusavi: {versions.ludusavi ?? versions.message ?? "Unknown"}</div>
            <div>pyludusavi: {versions.pyludusavi ?? "Unknown"}</div>
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

function summarizeOperationResult(result: OperationResult, label: string) {
  if (result.status === "skipped") {
    switch (result.reason) {
      case "auto_sync_disabled": return `Auto-sync skipped: feature disabled`;
      case "operation_running": return `Auto-sync skipped: another operation is running`;
      case "unmatched_game": return `Auto-sync skipped: could not match game name`;
      case "not_processed": return `Auto-sync skipped: game is deselected in Ludusavi`;
      case "no_backup": return `Auto-sync skipped: no backup found for ${result.game}`;

      case "local_current": return `Auto-sync skipped: local save is already current`;
      case "ambiguous_recency": return `Auto-sync skipped: recency is ambiguous`;
      default: return `${label} skipped: ${result.reason ?? "unknown reason"}`;
    }
  }
  if (result.status === "failed") {
    return `${label} failed: ${result.message ?? "unknown error"}`;
  }
  const action = result.status === "backed_up" ? "Backup" : "Restore";
  return `${action} completed for ${result.game}`;
}

function formatLogEntry(entry: LogEntry) {
  const game = entry.game_name ? ` ${entry.game_name}` : "";
  return `[${entry.timestamp}] [${entry.level}]${game} ${entry.message}`;
}

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
  console.log("SDH-ludusavi plugin initializing");

  const activeSessions = new Map<number, RunningSession>();
  let fallbackIntervalID: number | null = null;
  let fallbackPreviousAppID: string | null = null;
  let fallbackPreviousAppName: string | null = null;
  let lifecycleRegistration: unknown = null;

  const isTracked = (name: string, appID: string) => {
    if (trackedAppIDs.has(appID)) {
      log("debug", `Match found via AppID: ${appID}`);
      return true;
    }
    
    const normalizedInput = normalize(name);
    if (trackedNames.has(normalizedInput)) {
      log("debug", `Match found via exact name: ${normalizedInput}`);
      return true;
    }

    // Substring matching (mirroring backend fuzzy logic)
    for (const trackedName of Array.from(trackedNames)) {
      if (
        (normalizedInput.length > 4 && trackedName.includes(normalizedInput)) ||
        (trackedName.length > 4 && normalizedInput.includes(trackedName))
      ) {
        log("debug", `Match found via substring: ${normalizedInput} <-> ${trackedName}`);
        return true;
      }
    }

    log("debug", `No match for ${name} (${appID}) [normalized: ${normalizedInput}]`);
    return false;
  };

  function shouldPublishAutoSyncStatusBeforeRpc(tracked: boolean) {
    const trackingCacheEmpty = trackedAppIDs.size === 0 && trackedNames.size === 0;
    return (globalSettings === null || autoSyncNotificationsEnabled) && (tracked || trackingCacheEmpty);
  }

  const handleAppStart = async (name: string, appID: string) => {
    const tracked = isTracked(name, appID);
    log("info", `App started: ${name} (${appID}) tracked=${tracked}`);
    
    if (shouldPublishAutoSyncStatusBeforeRpc(tracked)) {
      publishAutoSyncStatus("restoring");
    }
    
    const result = await handleGameStartCall(name, appID);
    // Show result toast for all outcomes (restored, failed, or skipped)
    // unless auto-sync is completely disabled, another operation is running,
    // or the game simply isn't managed by Ludusavi (unmatched or ignored).
    const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
    if (result.status === "skipped" && silentReasons.includes(result.reason ?? "")) {
      hideAutoSyncStatus();
    }
    if (result.status !== "skipped" || !silentReasons.includes(result.reason ?? "")) {
      completeAutoSyncStatus(result);
      if (result.status === "failed") {
        notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
      }
    }
  };

  const handleAppExit = async (name: string, appID: string) => {
    const tracked = isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);
    
    if (shouldPublishAutoSyncStatusBeforeRpc(tracked)) {
      publishAutoSyncStatus("backing_up");
    }
    
    const result = await handleGameExitCall(name, appID);
    const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
    if (result.status === "skipped" && silentReasons.includes(result.reason ?? "")) {
      hideAutoSyncStatus();
    }
    if (result.status !== "skipped" || !silentReasons.includes(result.reason ?? "")) {
      if (result.status !== "skipped" || result.reason === "local_current") {
        completeAutoSyncStatus(result);
        if (result.status === "failed") {
          notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
      }
    }
  };

  const sessionFromAppOverview = (app: any): RunningSession | null => {
    const appID = app?.appid ? String(app.appid) : null;
    const name = app?.display_name || null;
    if (!appID || !name) {
      return null;
    }
    return { appID, name };
  };

  const getMainRunningSession = (): RunningSession | null => {
    return sessionFromAppOverview((Router as any).MainRunningApp);
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
        void handleAppStart(session.name, session.appID);
        return;
      }

      activeSessions.delete(notification.nInstanceID);
      const startupSession = activeSessions.get(-1);
      if (startupSession?.appID === session.appID) {
        activeSessions.delete(-1);
      }
      void handleAppExit(session.name, session.appID);
    } catch (err) {
      console.error("SDH-ludusavi: app lifetime notification failed", err);
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
      console.error("SDH-ludusavi: watcher loop failed", err);
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

  routerHook.addGlobalComponent(AUTO_SYNC_STATUS_COMPONENT, AutoSyncStatusStrip);

  return {
    name: "SDH-ludusavi",
    titleView: <div className={staticClasses.Title}>SDH-ludusavi</div>,
    content: <Content />,
    icon: <LuDatabaseBackup />,
    alwaysRender: true,
    onDismount() {
      unregisterLifecycleNotifications();
      routerHook.removeGlobalComponent(AUTO_SYNC_STATUS_COMPONENT);
      if (fallbackIntervalID !== null) {
        window.clearInterval(fallbackIntervalID);
      }
      activeSessions.clear();
      autoSyncStatusListeners.clear();
      currentAutoSyncStatusState = { status: "has_backup", visible: false };
      destroyAutoSyncStatusBrowserView();
      console.log("SDH-ludusavi unloading");
    },
  };
});
