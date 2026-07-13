
import type { AutoSyncStatusBrowserView, AutoSyncStatusBrowserViewOwner, AutoSyncStatusKind, AutoSyncStatusState } from "../types";
import { getAutoSyncStatusBounds } from "../utils/steam";
import { log } from "../utils/logging";
import { renderAutoSyncStatusHtml } from "./autoSyncStatusRenderer";
import { getSteamClient, asRecord, getGamepadUIMainWindowInstance } from "../utils/steamRuntime";

export type AutoSyncStatusBrowserViewApi = {
  setContext(state: AutoSyncStatusState): void;
  sync(state: AutoSyncStatusState): void;
  destroy(): void;
  clearShowTimeout(): void;
};

export function createAutoSyncStatusBrowserView(): AutoSyncStatusBrowserViewApi {
  let currentAutoSyncStatusState: AutoSyncStatusState = { status: "has_backup", visible: false, source: "hide" };
  let loadedAutoSyncStatus: AutoSyncStatusKind | null = null;

  let autoSyncStatusShowTimeoutID: number | null = null;
  let autoSyncStatusShowGeneration = 0;
  let autoSyncStatusBrowserView: AutoSyncStatusBrowserView | null = null;
  let autoSyncStatusBrowserViewOwner: AutoSyncStatusBrowserViewOwner | null = null;
  const AUTO_SYNC_STATUS_SHOW_DELAY = 100;

  function clearAutoSyncStatusShowTimeout() {
    if (autoSyncStatusShowTimeoutID === null) {
      return;
    }
    window.clearTimeout(autoSyncStatusShowTimeoutID);
    autoSyncStatusShowTimeoutID = null;
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
      const missingMethods: string[] = [];
      if (typeof view !== "object" || view === null) {
        missingMethods.push("not_object");
      } else {
        if (!("LoadURL" in view) && !("loadURL" in view)) missingMethods.push("LoadURL");
        if (!("SetBounds" in view) && !("setBounds" in view)) missingMethods.push("SetBounds");
        if (!("SetVisible" in view) && !("setVisible" in view)) missingMethods.push("SetVisible");
      }
      log(
        "debug",
        `BrowserView candidate ${source} missing methods: ${missingMethods.join(",")}`,
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
      const steamClient = asRecord(getSteamClient());
      const browserViewAPI = asRecord(steamClient?.BrowserView);
      const rootWindow = asRecord(getGamepadUIMainWindowInstance());

      if (typeof rootWindow?.CreateBrowserView === "function") {
        log("info", "Creating BrowserView via GamepadUIMainWindowInstance", "autosync_status");
        autoSyncStatusBrowserViewOwner = rootWindow.CreateBrowserView(
          "sdh-ludusavi-autosync-status-strip",
        ) as AutoSyncStatusBrowserViewOwner;
      } else if (typeof browserViewAPI?.Create === "function") {
        log("info", "Creating BrowserView via SteamClient.BrowserView.Create", "autosync_status");
        autoSyncStatusBrowserViewOwner = browserViewAPI.Create({
          strInitialURL: "about:blank"
        }) as AutoSyncStatusBrowserViewOwner | null;
      }

      if (!autoSyncStatusBrowserViewOwner) {
        log("error", "Failed to create BrowserView surface", "autosync_status");
        return null;
      }

      log(
        "info",
        `BrowserView created: type=${typeof autoSyncStatusBrowserViewOwner}`,
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

  return {
    setContext(state: AutoSyncStatusState) {
      currentAutoSyncStatusState = state;
    },

    sync(state: AutoSyncStatusState) {
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
    },

    destroy() {
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
          const steamClient = asRecord(getSteamClient());
          const browserViewAPI = asRecord(steamClient?.BrowserView);
          if (typeof browserViewAPI?.Destroy === "function") {
            browserViewAPI.Destroy(browserViewOwner);
          }
        }
      } catch (err) {
        log("warning", `Could not destroy status strip BrowserView: ${err}`, "autosync_status");
      } finally {
        autoSyncStatusBrowserView = null;
        autoSyncStatusBrowserViewOwner = null;
        loadedAutoSyncStatus = null;
      }
    },

    clearShowTimeout() {
      clearAutoSyncStatusShowTimeout();
    }
  };
}