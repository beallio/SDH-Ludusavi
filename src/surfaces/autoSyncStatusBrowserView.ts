import { Router } from "@decky/ui";
import type { AutoSyncStatusBrowserView, AutoSyncStatusBrowserViewOwner, AutoSyncStatusKind, AutoSyncStatusState } from "../types";
import { getAutoSyncStatusBounds, objectKeys } from "../utils/steam";
import { log } from "../utils/logging";
import { renderAutoSyncStatusHtml } from "./autoSyncStatusRenderer";

// Add state reference injection so it can access currentAutoSyncStatusState.visible
let currentAutoSyncStatusState: AutoSyncStatusState = { status: "has_backup", visible: false, source: "hide" };
export function setBrowserViewSyncStateContext(state: AutoSyncStatusState) {
    currentAutoSyncStatusState = state;
}

let loadedAutoSyncStatus: AutoSyncStatusKind | null = null;

let autoSyncStatusShowTimeoutID: number | null = null;
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
export function syncAutoSyncStatusBrowserView(state: AutoSyncStatusState) {
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
    loadedAutoSyncStatus = null;
  }
}
export function clearAutoSyncStatusShowTimeout() {
  if (autoSyncStatusShowTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusShowTimeoutID);
  autoSyncStatusShowTimeoutID = null;
}