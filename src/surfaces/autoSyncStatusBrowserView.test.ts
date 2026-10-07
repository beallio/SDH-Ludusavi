import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createAutoSyncStatusBrowserView } from "./autoSyncStatusBrowserView";
import { autoSyncStatusText } from "./autoSyncStatusRenderer";
import { parseHTML } from "linkedom";
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

function stubNativeFont(fetchImplementation: () => Promise<Response>) {
  const fetchFont = vi.fn(fetchImplementation);
  vi.stubGlobal("fetch", fetchFont);
  vi.stubGlobal("FileReader", class {
    result: string | null = null;
    error: Error | null = null;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    readAsDataURL() {
      this.result = "data:application/font-sfnt;base64,Zm9udA==";
      this.onload?.();
    }
  });
  return fetchFont;
}

function visiblePostGameMessage(url: string): string | null {
  const html = decodeURIComponent(url.slice(url.indexOf(",") + 1));
  return parseHTML(html).document.querySelector(".post-game-value")?.textContent ?? null;
}

describe("autoSyncStatusBrowserView", () => {
  let mockGetSteamClient: any;
  let mockGetGamepadUIMainWindowInstance: any;
  beforeEach(() => {
    vi.useFakeTimers();
    mockGetSteamClient = vi.spyOn(steamRuntime, "getSteamClient");
    mockGetGamepadUIMainWindowInstance = vi.spyOn(steamRuntime, "getGamepadUIMainWindowInstance");
    vi.spyOn(steamRuntime, "getGamepadMainWindow").mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    vi.unstubAllGlobals();
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

  it("cancels a delayed post-game reveal when presentation becomes hidden before font completion", async () => {
    let resolveFont!: (response: Response) => void;
    stubNativeFont(() => new Promise<Response>((resolve) => { resolveFont = resolve; }));
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    const createBrowserView = vi.fn(() => ({
      m_browserView: { LoadURL: loadURL, SetBounds: vi.fn(), SetVisible: setVisible },
    }));
    mockGetGamepadUIMainWindowInstance.mockReturnValue({ CreateBrowserView: createBrowserView });
    mockGetSteamClient.mockReturnValue({});
    const api = createAutoSyncStatusBrowserView();
    const state = {
      status: "backing_up" as const,
      visible: true,
      source: "lifecycle_exit" as const,
      lifecycle: "lifecycle_exit" as const,
      appID: "100",
    };

    api.setContext(state);
    api.sync(state);
    expect(loadURL).not.toHaveBeenCalled();
    api.setContext({ ...state, visible: false });
    api.sync({ ...state, visible: false });
    resolveFont(new Response(new Uint8Array([0, 1, 0, 0])));
    await vi.runAllTimersAsync();

    expect(loadURL).toHaveBeenLastCalledWith("about:blank");
    expect(setVisible).not.toHaveBeenLastCalledWith(true);
    api.destroy();
  });

  it("does not load a pending post-game document after the BrowserView is destroyed", async () => {
    let resolveFont!: (response: Response) => void;
    stubNativeFont(() => new Promise<Response>((resolve) => { resolveFont = resolve; }));
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    const createBrowserView = vi.fn(() => ({
      m_browserView: { LoadURL: loadURL, SetBounds: vi.fn(), SetVisible: setVisible },
    }));
    mockGetGamepadUIMainWindowInstance.mockReturnValue({ CreateBrowserView: createBrowserView });
    mockGetSteamClient.mockReturnValue({});
    const api = createAutoSyncStatusBrowserView();
    const state = {
      status: "backing_up" as const,
      visible: true,
      source: "lifecycle_exit" as const,
      lifecycle: "lifecycle_exit" as const,
      appID: "100",
    };

    api.setContext(state);
    api.sync(state);
    api.destroy();
    resolveFont(new Response(new Uint8Array([0, 1, 0, 0])));
    await vi.runAllTimersAsync();

    expect(createBrowserView).toHaveBeenCalledOnce();
    expect(loadURL).not.toHaveBeenCalled();
    expect(setVisible).not.toHaveBeenLastCalledWith(true);
  });

  it("deduplicates a pending native font load and presents only the latest exit state", async () => {
    let resolveFont!: (response: Response) => void;
    const fetchFont = stubNativeFont(() => new Promise<Response>((resolve) => { resolveFont = resolve; }));
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    const createBrowserView = vi.fn(() => ({
      m_browserView: { LoadURL: loadURL, SetBounds: vi.fn(), SetVisible: setVisible },
    }));
    mockGetGamepadUIMainWindowInstance.mockReturnValue({ CreateBrowserView: createBrowserView });
    mockGetSteamClient.mockReturnValue({});
    const api = createAutoSyncStatusBrowserView();
    const first = {
      status: "backing_up" as const,
      visible: true,
      source: "lifecycle_exit" as const,
      lifecycle: "lifecycle_exit" as const,
      appID: "100",
    };
    const latest = { ...first, status: "syncthing_uploading" as const };

    api.setContext(first);
    api.sync(first);
    api.sync(first);
    api.setContext(latest);
    api.sync(latest);
    api.sync(latest);
    expect(fetchFont).toHaveBeenCalledOnce();
    expect(loadURL).not.toHaveBeenCalled();

    resolveFont(new Response(new Uint8Array([0, 1, 0, 0])));
    await vi.runAllTimersAsync();

    expect(loadURL).toHaveBeenCalledOnce();
    expect(visiblePostGameMessage(loadURL.mock.calls[0][0])).toBe(autoSyncStatusText[latest.status]);
    expect(setVisible).toHaveBeenLastCalledWith(true);

    api.sync(latest);
    expect(loadURL).toHaveBeenCalledOnce();
    const laterExit = { ...latest, status: "syncthing_complete" as const };
    api.setContext(laterExit);
    api.sync(laterExit);
    await vi.runAllTimersAsync();
    expect(fetchFont).toHaveBeenCalledOnce();
    expect(loadURL).toHaveBeenCalledTimes(2);
    api.destroy();
  });

  it("uses a readable no-font post-game document after a failed font request without looping", async () => {
    const fetchFont = stubNativeFont(() => Promise.reject(new Error("font unavailable")));
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    mockGetGamepadUIMainWindowInstance.mockReturnValue({
      CreateBrowserView: () => ({
        m_browserView: { LoadURL: loadURL, SetBounds: vi.fn(), SetVisible: setVisible },
      }),
    });
    mockGetSteamClient.mockReturnValue({});
    const api = createAutoSyncStatusBrowserView();
    const state = {
      status: "backing_up" as const,
      visible: true,
      source: "lifecycle_exit" as const,
      lifecycle: "lifecycle_exit" as const,
      appID: "100",
    };
    api.setContext(state);
    api.sync(state);
    await vi.runAllTimersAsync();

    expect(fetchFont).toHaveBeenCalledOnce();
    expect(loadURL).toHaveBeenCalledOnce();
    expect(visiblePostGameMessage(loadURL.mock.calls[0][0])).toBe(autoSyncStatusText[state.status]);
    expect(setVisible).toHaveBeenLastCalledWith(true);

    api.sync(state);
    expect(fetchFont).toHaveBeenCalledOnce();
    expect(loadURL).toHaveBeenCalledOnce();
    api.destroy();
  });

  it("cancels a delayed reveal when presentation becomes hidden before the callback", async () => {
    stubNativeFont(() => Promise.resolve(new Response(new Uint8Array([0, 1, 0, 0]))));
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    const createBrowserView = vi.fn(() => ({
      m_browserView: { LoadURL: loadURL, SetBounds: vi.fn(), SetVisible: setVisible },
    }));
    mockGetGamepadUIMainWindowInstance.mockReturnValue({ CreateBrowserView: createBrowserView });
    mockGetSteamClient.mockReturnValue({});
    const api = createAutoSyncStatusBrowserView();
    const state = {
      status: "backing_up" as const,
      visible: true,
      source: "lifecycle_exit" as const,
      lifecycle: "lifecycle_exit" as const,
      appID: "100",
    };

    api.setContext(state);
    api.sync(state);
    await vi.advanceTimersByTimeAsync(0);
    expect(loadURL).toHaveBeenCalledOnce();
    api.setContext({ ...state, visible: false });
    api.sync({ ...state, visible: false });
    await vi.advanceTimersByTimeAsync(100);

    expect(loadURL).toHaveBeenLastCalledWith("about:blank");
    expect(setVisible).not.toHaveBeenLastCalledWith(true);
    api.destroy();
  });

  it("keeps a same-status startup presentation separate from a pending post-game presentation", async () => {
    let resolveFont!: (response: Response) => void;
    stubNativeFont(() => new Promise<Response>((resolve) => { resolveFont = resolve; }));
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    mockGetGamepadUIMainWindowInstance.mockReturnValue({
      CreateBrowserView: () => ({
        m_browserView: { LoadURL: loadURL, SetBounds: vi.fn(), SetVisible: setVisible },
      }),
    });
    mockGetSteamClient.mockReturnValue({});
    const api = createAutoSyncStatusBrowserView();
    const exit = {
      status: "backing_up" as const,
      visible: true,
      source: "lifecycle_exit" as const,
      lifecycle: "lifecycle_exit" as const,
      appID: "100",
    };
    const startup = {
      ...exit,
      source: "lifecycle_start" as const,
      lifecycle: "lifecycle_start" as const,
    };

    api.setContext(exit);
    api.sync(exit);
    expect(loadURL).not.toHaveBeenCalled();
    api.setContext(startup);
    api.sync(startup);
    expect(loadURL).toHaveBeenCalledOnce();
    resolveFont(new Response(new Uint8Array([0, 1, 0, 0])));
    await vi.runAllTimersAsync();

    expect(loadURL).toHaveBeenCalledOnce();
    expect(setVisible).toHaveBeenLastCalledWith(true);
    api.destroy();
  });

  it("does not let a pending post-game font replace a protected startup document", async () => {
    let resolveFont!: (response: Response) => void;
    const fetchFont = vi.fn(() => new Promise<Response>((resolve) => { resolveFont = resolve; }));
    vi.stubGlobal("fetch", fetchFont);
    vi.stubGlobal("FileReader", class {
      result: string | null = null;
      error: Error | null = null;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      readAsDataURL() {
        this.result = "data:application/font-sfnt;base64,AAEAAA==";
        this.onload?.();
      }
    });
    const loadURL = vi.fn();
    const setVisible = vi.fn();
    mockGetGamepadUIMainWindowInstance.mockReturnValue({
      CreateBrowserView: () => ({
        m_browserView: { LoadURL: loadURL, SetBounds: vi.fn(), SetVisible: setVisible },
      }),
    });
    mockGetSteamClient.mockReturnValue({});
    const api = createAutoSyncStatusBrowserView();
    const exit = { status: "backing_up" as const, visible: true, source: "lifecycle_exit" as const, lifecycle: "lifecycle_exit" as const };
    api.setContext(exit);
    api.sync(exit);
    expect(loadURL).not.toHaveBeenCalled();

    const startup = { status: "checking" as const, visible: true, source: "lifecycle_start" as const, lifecycle: "lifecycle_start" as const };
    api.setContext(startup);
    api.sync(startup);
    expect(loadURL).toHaveBeenCalledOnce();
    expect(fetchFont).toHaveBeenCalledOnce();
    resolveFont(new Response(new Uint8Array([0, 1, 0, 0])));
    await vi.runAllTimersAsync();
    expect(loadURL).toHaveBeenCalledOnce();
    expect(setVisible).toHaveBeenLastCalledWith(true);
    api.destroy();
  });
});
