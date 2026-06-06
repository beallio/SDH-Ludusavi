import { Router } from "@decky/ui";
import { IoMdCloudDownload, IoMdCloudUpload, IoMdCloudDone } from "react-icons/io";

import type {
  AutoSyncStatusBrowserView,
  AutoSyncStatusBrowserViewOwner,
  AutoSyncStatusKind,
  AutoSyncStatusSource,
  AutoSyncStatusState,
  LifecycleCheckResult,
  OperationResult,
  RpcStatus
} from "../types";
import { getAutoSyncStatusBounds, objectKeys } from "../utils/steam";
import { log } from "../utils/logging";

const autoSyncStatusText: Record<AutoSyncStatusKind, string> = {
  checking: "VERIFYING GAME SAVE",
  backing_up: "BACKING UP LOCAL SAVE",
  restoring: "RESTORING BACKUP SAVE",
  conflict: "SAVE CONFLICT",
  has_backup: "GAME SAVE UP TO DATE",
  unknown: "UNKNOWN",
  error: "UNABLE TO SYNC",
  syncthing_downloading: "SYNCTHING DOWNLOADING",
  syncthing_uploading: "SYNCTHING UPLOADING",
  syncthing_complete: "SYNCTHING COMPLETE"
};

let currentAutoSyncStatusState: AutoSyncStatusState = {
  status: "has_backup",
  visible: false,
  source: "hide"
};
let autoSyncStatusTimedOut = false;
let loadedAutoSyncStatus: AutoSyncStatusKind | null = null;
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

function isLudusaviRunningStatus(status: AutoSyncStatusKind): boolean {
  return status === "checking" || status === "backing_up" || status === "restoring";
}

function isSyncthingActiveStatus(status: AutoSyncStatusKind): boolean {
  return status === "syncthing_downloading" || status === "syncthing_uploading";
}

const svgAttributeMapping: Record<string, string> = {
  fillRule: "fill-rule",
  clipRule: "clip-rule",
  strokeWidth: "stroke-width",
  strokeLinecap: "stroke-linecap",
  strokeLinejoin: "stroke-linejoin",
};

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function serializeSvgNode(node: any): string {
  if (!node || typeof node !== "object") {
    return "";
  }
  const tag = node.type;
  if (tag !== "path" && tag !== "g") {
    log("warning", `Unsupported SVG tag: ${tag}`, "autosync_status");
    return "";
  }

  const props = node.props || {};
  let attributes = "";
  const allowedAttributes = [
    "d",
    "fill",
    "fillRule",
    "clipRule",
    "stroke",
    "strokeWidth",
    "strokeLinecap",
    "strokeLinejoin",
    "opacity",
    "transform",
  ];

  for (const attr of allowedAttributes) {
    if (props[attr] !== undefined && props[attr] !== null) {
      const svgAttr = svgAttributeMapping[attr] || attr;
      attributes += ` ${svgAttr}="${escapeHtml(String(props[attr]))}"`;
    }
  }

  let childrenMarkup = "";
  if (props.children) {
    if (Array.isArray(props.children)) {
      childrenMarkup = props.children.map(serializeSvgNode).join("");
    } else {
      childrenMarkup = serializeSvgNode(props.children);
    }
  }

  return `<${tag}${attributes}>${childrenMarkup}</${tag}>`;
}

function serializeIcon(Icon: any): string {
  try {
    const element = Icon({
      size: 18,
      "aria-hidden": true,
      focusable: false,
    });
    if (!element || typeof element !== "object" || !element.props) {
      return "";
    }
    const viewBox = element.props.attr?.viewBox || "0 0 512 512";
    let childrenMarkup = "";
    const children = element.props.children;
    if (children) {
      if (Array.isArray(children)) {
        childrenMarkup = children.map(serializeSvgNode).join("");
      } else {
        childrenMarkup = serializeSvgNode(children);
      }
    }
    return `<svg viewBox="${escapeHtml(viewBox)}" width="18" height="18" fill="currentColor" aria-hidden="true" focusable="false">${childrenMarkup}</svg>`;
  } catch (err) {
    log("warning", `Failed to serialize icon: ${err}`, "autosync_status");
    return '<svg viewBox="0 0 512 512" width="18" height="18" fill="currentColor" aria-hidden="true" focusable="false"></svg>';
  }
}

const serializedIconsCache: Record<string, string> = {};

function getSerializedIcon(status: AutoSyncStatusKind): string {
  if (serializedIconsCache[status]) {
    return serializedIconsCache[status];
  }

  let icon: any;
  if (status === "syncthing_downloading") {
    icon = IoMdCloudDownload;
  } else if (status === "syncthing_uploading") {
    icon = IoMdCloudUpload;
  } else if (status === "syncthing_complete") {
    icon = IoMdCloudDone;
  } else {
    return "";
  }

  const serialized = serializeIcon(icon);
  serializedIconsCache[status] = serialized;
  return serialized;
}

function iconSvgForAutoSyncStatus(status: AutoSyncStatusKind): string {
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
  if (status === "syncthing_downloading" || status === "syncthing_uploading" || status === "syncthing_complete") {
    return getSerializedIcon(status);
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
  const browserView = ensureAutoSyncStatusBrowserView();
  if (!browserView) {
    return;
  }
  if (!browserView.LoadURL || !browserView.SetBounds || !browserView.SetVisible) {
    log("warning", "Status strip BrowserView is missing required methods", "autosync_status");
    return;
  }

  const bounds = getAutoSyncStatusBounds();

  if (!state.visible) {
    clearAutoSyncStatusShowTimeout();
    browserView.SetVisible(false);
    try {
      browserView.LoadURL?.("about:blank");
    } catch (err) {
      log("debug", `Could not navigate BrowserView to blank: ${err}`, "autosync_status");
    }
    loadedAutoSyncStatus = null;
    return;
  }

  if (state.status === loadedAutoSyncStatus) {
    try {
      browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);
      browserView.SetWindowStackingOrder?.(50);
      browserView.SetFocus?.(false);
      if (autoSyncStatusShowTimeoutID === null) {
        browserView.SetVisible(true);
      }
    } catch (err) {
      log("warning", `Could not update bounds for existing BrowserView: ${err}`, "autosync_status");
    }
    return;
  }

  // Changed status or initially unloaded
  clearAutoSyncStatusShowTimeout();
  const showGeneration = ++autoSyncStatusShowGeneration;

  try {
    const html = renderAutoSyncStatusHtml(state);
    const url = "data:text/html;charset=utf-8," + encodeURIComponent(html);

    log("debug", `Syncing BrowserView (changed status): bounds=${JSON.stringify(bounds)}`, "autosync_status");

    browserView.SetVisible(false);
    browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);
    browserView.LoadURL(url);
    loadedAutoSyncStatus = state.status;

    autoSyncStatusShowTimeoutID = window.setTimeout(() => {
      autoSyncStatusShowTimeoutID = null;
      if (showGeneration !== autoSyncStatusShowGeneration || !currentAutoSyncStatusState.visible) {
        return;
      }
      browserView.SetVisible?.(true);
      browserView.SetWindowStackingOrder?.(50);
      browserView.SetFocus?.(false);
    }, AUTO_SYNC_STATUS_SHOW_DELAY);
  } catch (err) {
    loadedAutoSyncStatus = null;
    log("warning", `Could not update status strip BrowserView: ${err}`, "autosync_status");
  }
}

export function destroyAutoSyncStatusBrowserView() {
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

export function clearAutoSyncStatusHideTimeout() {
  if (autoSyncStatusHideTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusHideTimeoutID);
  autoSyncStatusHideTimeoutID = null;
}

export function clearAutoSyncStatusShowTimeout() {
  if (autoSyncStatusShowTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusShowTimeoutID);
  autoSyncStatusShowTimeoutID = null;
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
  const isSyncthingActive = isSyncthingActiveStatus(state.status);
  const useTenSecondWatchdog = isRunning || isSyncthingActive;

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
  }, useTenSecondWatchdog ? 10000 : 2000);
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
  logAutoSyncStatusChange(currentAutoSyncStatusState);
  if (shouldResetSurface) {
    syncAutoSyncStatusBrowserViewDeferred(currentAutoSyncStatusState);
    return;
  }
  clearAutoSyncStatusSyncTimeout();
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
  scheduleAutoSyncStatusHide(currentAutoSyncStatusState);
}

export function hideAutoSyncStatus(options: Partial<AutoSyncStatusPublishOptions> = {}) {
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

export function resetAutoSyncStatusSurface() {
  currentAutoSyncStatusState = {
    status: "has_backup",
    visible: false,
    source: "hide"
  };
  loadedAutoSyncStatus = null;
  clearAutoSyncStatusHideTimeout();
  clearAutoSyncStatusSyncTimeout();
  clearAutoSyncStatusShowTimeout();
  destroyAutoSyncStatusBrowserView();
}
