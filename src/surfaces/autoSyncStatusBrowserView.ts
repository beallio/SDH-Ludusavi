
import type { AutoSyncStatusBrowserView, AutoSyncStatusBrowserViewOwner, AutoSyncStatusState } from "../types";
import { getAutoSyncStatusBounds } from "../utils/steam";
import { log } from "../utils/logging";
import { renderAutoSyncStatusHtml, type NativePostGameAppearance } from "./autoSyncStatusRenderer";
import { getSteamClient, asRecord, getGamepadMainWindow, getGamepadUIMainWindowInstance } from "../utils/steamRuntime";

const NATIVE_BOLD_FONT_URL = "https://steamloopback.host/custom_fonts/clientui.uifont?MotivaSans-Bold";

export type AutoSyncStatusBrowserViewApi = {
  setContext(state: AutoSyncStatusState): void;
  sync(state: AutoSyncStatusState): void;
  destroy(): void;
  clearShowTimeout(): void;
};

export function createAutoSyncStatusBrowserView(): AutoSyncStatusBrowserViewApi {
  let currentAutoSyncStatusState: AutoSyncStatusState = { status: "has_backup", visible: false, source: "hide" };
  let currentPresentationKey = presentationKey(currentAutoSyncStatusState);
  let loadedAutoSyncStatusKey: string | null = null;
  let pendingAutoSyncStatusKey: string | null = null;
  let nativeBoldFontDataUrlPromise: Promise<string | null> | null = null;

  let autoSyncStatusShowTimeoutID: number | null = null;
  let presentationGeneration = 0;
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

  function presentationKey(state: AutoSyncStatusState): string {
    return `${state.lifecycle === "lifecycle_exit" ? "exit" : "startup"}:${state.status}:${state.appID ?? ""}`;
  }

  function updateContext(state: AutoSyncStatusState) {
    const key = presentationKey(state);
    const changedPresentation = key !== currentPresentationKey
      || state.visible !== currentAutoSyncStatusState.visible;
    currentAutoSyncStatusState = state;
    currentPresentationKey = key;
    if (!changedPresentation) {
      return;
    }

    presentationGeneration += 1;
    pendingAutoSyncStatusKey = null;
    clearAutoSyncStatusShowTimeout();
    try {
      autoSyncStatusBrowserView?.SetVisible?.(false);
    } catch (err) {
      log("debug", `Could not hide changed BrowserView presentation: ${err}`, "autosync_status");
    }
  }

  function loadNativeBoldFontDataUrl(): Promise<string | null> {
    if (nativeBoldFontDataUrlPromise) {
      return nativeBoldFontDataUrlPromise;
    }

    const request = (async () => {
      const response = await fetch(NATIVE_BOLD_FONT_URL);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const blob = await response.blob();
      return await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          if (typeof reader.result === "string") {
            resolve(reader.result);
          } else {
            reject(new Error("Font data URL was not produced"));
          }
        };
        reader.onerror = () => reject(reader.error ?? new Error("Font data URL encoding failed"));
        reader.onabort = () => reject(new Error("Font data URL encoding was aborted"));
        try {
          reader.readAsDataURL(blob);
        } catch (err) {
          reject(err);
        }
      });
    })().catch((err: unknown) => {
      log("warning", `Could not load native MotivaSans-Bold font: ${err}`, "autosync_status");
      if (nativeBoldFontDataUrlPromise === request) {
        nativeBoldFontDataUrlPromise = null;
      }
      return null;
    });
    nativeBoldFontDataUrlPromise = request;
    return request;
  }

  function nativeRowBackgroundColor(state: AutoSyncStatusState): string {
    if (!state.appID) {
      return "transparent";
    }
    try {
      const document = getGamepadMainWindow()?.document;
      if (!document) {
        return "transparent";
      }
      for (const row of document.querySelectorAll<HTMLElement>("[data-sdh-ludusavi-status-row]")) {
        if (row.getAttribute("data-sdh-ludusavi-status-appid") !== state.appID) continue;
        const color = row.ownerDocument?.defaultView?.getComputedStyle?.(row).backgroundColor;
        return typeof color === "string" && color ? color : "transparent";
      }
      return "transparent";
    } catch {
      return "transparent";
    }
  }

  function isCurrentPresentation(
    browserView: AutoSyncStatusBrowserView,
    key: string,
    generation: number,
  ): boolean {
    return generation === presentationGeneration
      && autoSyncStatusBrowserView === browserView
      && currentAutoSyncStatusState.visible
      && currentPresentationKey === key;
  }

  function scheduleAutoSyncStatusReveal(
    browserView: AutoSyncStatusBrowserView,
    key: string,
    generation: number,
  ) {
    autoSyncStatusShowTimeoutID = window.setTimeout(() => {
      autoSyncStatusShowTimeoutID = null;
      if (!isCurrentPresentation(browserView, key, generation)) {
        return;
      }
      browserView.SetVisible?.(true);
      browserView.SetWindowStackingOrder?.(50);
      browserView.SetFocus?.(false);
    }, AUTO_SYNC_STATUS_SHOW_DELAY);
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
      updateContext(state);
    },

    sync(state: AutoSyncStatusState) {
      updateContext(state);
      if (!state.visible && !autoSyncStatusBrowserView) {
        clearAutoSyncStatusShowTimeout();
        loadedAutoSyncStatusKey = null;
        pendingAutoSyncStatusKey = null;
        return;
      }
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
        pendingAutoSyncStatusKey = null;
        browserView.SetVisible(false);
        try {
          browserView.LoadURL("about:blank");
        } catch (err) {
          log("debug", `Could not navigate BrowserView to blank: ${err}`, "autosync_status");
        }
        loadedAutoSyncStatusKey = null;
        return;
      }

      const key = currentPresentationKey;
      if (pendingAutoSyncStatusKey === key) {
        try {
          browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);
          browserView.SetWindowStackingOrder?.(50);
          browserView.SetFocus?.(false);
        } catch (err) {
          log("warning", `Could not update bounds for existing BrowserView: ${err}`, "autosync_status");
        }
        return;
      }
      if (key === loadedAutoSyncStatusKey) {
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

      clearAutoSyncStatusShowTimeout();
      const generation = presentationGeneration;
      const presentationState = { ...state };

      try {
        log("debug", `Syncing BrowserView (changed status): bounds=${JSON.stringify(bounds)}`, "autosync_status");
        browserView.SetVisible(false);
        browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);
        loadedAutoSyncStatusKey = null;

        if (state.lifecycle === "lifecycle_exit") {
          pendingAutoSyncStatusKey = key;
          void loadNativeBoldFontDataUrl().then((fontDataUrl) => {
            if (!isCurrentPresentation(browserView, key, generation)) {
              return;
            }
            const appearance: NativePostGameAppearance = {
              fontDataUrl,
              backgroundColor: nativeRowBackgroundColor(presentationState),
            };
            const html = renderAutoSyncStatusHtml(presentationState, appearance);
            browserView.LoadURL?.("data:text/html;charset=utf-8," + encodeURIComponent(html));
            loadedAutoSyncStatusKey = key;
            pendingAutoSyncStatusKey = null;
            scheduleAutoSyncStatusReveal(browserView, key, generation);
          }).catch((err: unknown) => {
            if (!isCurrentPresentation(browserView, key, generation)) {
              return;
            }
            pendingAutoSyncStatusKey = null;
            loadedAutoSyncStatusKey = null;
            log("warning", `Could not update status strip BrowserView: ${err}`, "autosync_status");
          });
          return;
        }

        const html = renderAutoSyncStatusHtml(presentationState);
        browserView.LoadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
        loadedAutoSyncStatusKey = key;
        scheduleAutoSyncStatusReveal(browserView, key, generation);
      } catch (err) {
        pendingAutoSyncStatusKey = null;
        loadedAutoSyncStatusKey = null;
        log("warning", `Could not update status strip BrowserView: ${err}`, "autosync_status");
      }
    },

    destroy() {
      presentationGeneration += 1;
      pendingAutoSyncStatusKey = null;
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
        loadedAutoSyncStatusKey = null;
      }
    },

    clearShowTimeout() {
      presentationGeneration += 1;
      pendingAutoSyncStatusKey = null;
      clearAutoSyncStatusShowTimeout();
    }
  };
}
