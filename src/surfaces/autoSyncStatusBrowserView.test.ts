import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { log } from "../utils/logging";
import { createAutoSyncStatusBrowserView } from "./autoSyncStatusBrowserView";
import * as steamRuntime from "../utils/steamRuntime";

globalThis.window = globalThis as any;
(globalThis.window as any).setTimeout = setTimeout;
(globalThis.window as any).clearTimeout = clearTimeout;

vi.mock("@decky/ui", () => ({}));
vi.mock("@decky/api", () => ({}));

vi.mock("../utils/steam", () => ({
  getAutoSyncStatusBounds: vi.fn().mockReturnValue({ x: 0, y: 0, width: 100, height: 20 }),
}));

vi.mock("../utils/logging", () => ({
  log: vi.fn(),
}));

describe("autoSyncStatusBrowserView", () => {
  let mockGetSteamClient: any;
  let mockGetGamepadUIMainWindowInstance: any;

  beforeEach(() => {
    vi.useFakeTimers();
    mockGetSteamClient = vi.spyOn(steamRuntime, "getSteamClient");
    mockGetGamepadUIMainWindowInstance = vi.spyOn(steamRuntime, "getGamepadUIMainWindowInstance");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("logs bounded missing methods when candidate is invalid without enumerating all properties", () => {
    const fakeRoot = {
      CreateBrowserView: () => ({
        m_browserView: {
          loadURL: () => {},
          // Missing setBounds and setVisible
        },
      }),
    };

    mockGetGamepadUIMainWindowInstance.mockReturnValue(fakeRoot);
    mockGetSteamClient.mockReturnValue({});

    const api = createAutoSyncStatusBrowserView();
    api.sync({ status: "has_backup", visible: true, source: "hide" });

    // The normalize function should log that SetBounds and SetVisible are missing.
    // It should check the specific candidates and methods, rather than crashing or enumerating.
    expect(log).toHaveBeenCalledWith(
      "debug",
      expect.stringContaining("BrowserView candidate m_browserView missing methods: SetBounds,SetVisible"),
      "autosync_status"
    );
  });

  it("does not create a BrowserView for an invisible status on a fresh surface", () => {
    const createBrowserView = vi.fn();
    mockGetGamepadUIMainWindowInstance.mockReturnValue({ CreateBrowserView: createBrowserView });
    mockGetSteamClient.mockReturnValue({});

    const api = createAutoSyncStatusBrowserView();
    api.sync({ status: "has_backup", visible: false, source: "hide" });

    expect(createBrowserView).not.toHaveBeenCalled();
  });

  it("keeps the existing BrowserView hide path and reloads a status after hiding", () => {
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    const setBounds = vi.fn();
    const createBrowserView = vi.fn(() => ({
      m_browserView: {
        LoadURL: loadURL,
        SetBounds: setBounds,
        SetVisible: setVisible,
      },
    }));
    mockGetGamepadUIMainWindowInstance.mockReturnValue({ CreateBrowserView: createBrowserView });
    mockGetSteamClient.mockReturnValue({});

    const api = createAutoSyncStatusBrowserView();
    const visibleState = { status: "has_backup" as const, visible: true, source: "hide" as const };
    api.sync(visibleState);

    expect(createBrowserView).toHaveBeenCalledTimes(1);
    setVisible.mockClear();
    loadURL.mockClear();

    api.sync({ ...visibleState, visible: false });

    expect(createBrowserView).toHaveBeenCalledTimes(1);
    expect(setVisible).toHaveBeenCalledWith(false);
    expect(loadURL).toHaveBeenCalledWith("about:blank");

    loadURL.mockClear();
    api.sync(visibleState);

    expect(loadURL).toHaveBeenCalledOnce();
    expect(loadURL.mock.calls[0][0]).toMatch(/^data:text\/html/);
    api.clearShowTimeout();
  });
});
