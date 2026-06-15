import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createSettingsMutationRuntime } from "./settingsMutationRuntime";
import { createLudusaviStateStore } from "../state/ludusaviState";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {},
}));

vi.mock("react", () => ({
  createContext: vi.fn(),
  useContext: vi.fn(),
  useSyncExternalStore: vi.fn(),
}));

vi.mock("react/jsx-dev-runtime", () => ({
  jsxDEV: vi.fn(),
  Fragment: Symbol("Fragment"),
}));

vi.mock("../api/ludusaviRpc", () => {
  return {
    setAutoSyncEnabled: vi.fn(),
    setNotificationSettings: vi.fn(),
    setSelectedGameCall: vi.fn(),
    setUpdateChannelCall: vi.fn(),
    setAutomaticUpdateChecksCall: vi.fn()
  };
});

vi.stubGlobal("window", {
  setTimeout,
  clearTimeout
});

describe("SettingsMutationRuntime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("busy-flag lifecycle with fake timers", async () => {
    const store = createLudusaviStateStore();
    store.applySettings({ auto_sync_enabled: false } as any);
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");
    
    let busyStatus = false;
    runtime.subscribeQueue((busy: boolean) => {
      busyStatus = busy;
    });

    const isMounted = { current: true };
    const setBusyLabel = vi.fn();
    const notifyFailure = vi.fn();

    runtime.setActiveStore(store, notifyFailure);
    const controller = runtime.createController({
      ludusaviStore: store,
      isMounted,
      setBusyLabel,
      notifyFailure
    });

    let resolveRpc: (res: any) => void;
    vi.mocked(rpc.setAutoSyncEnabled).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRpc = resolve;
      })
    );

    controller.toggleAutoSync(true);

    expect(busyStatus).toBe(true);
    expect(setBusyLabel).toHaveBeenCalledWith("Updating settings");

    resolveRpc!({ auto_sync_enabled: true } as any);
    
    // allow microtasks to clear
    await vi.runAllTimersAsync();

    expect(busyStatus).toBe(false);
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(true);
  });

  it("rollback to lastPersisted on RPC failure", async () => {
    const store = createLudusaviStateStore();
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");

    const notifyFailure = vi.fn();
    runtime.setActiveStore(store, notifyFailure);
    const controller = runtime.createController({
      ludusaviStore: store,
      isMounted: { current: true },
      setBusyLabel: vi.fn(),
      notifyFailure
    });

    store.setAutoSyncEnabled(false);
    runtime.applySettings(store, { auto_sync_enabled: false } as any);

    vi.mocked(rpc.setAutoSyncEnabled).mockRejectedValueOnce(new Error("RPC failed"));

    controller.toggleAutoSync(true);

    // Initial optimistic update
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(true);

    await vi.runAllTimersAsync();

    // Rollback to previous state
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(false);
    expect(notifyFailure).toHaveBeenCalled();
  });

  it("two runtimes isolated", async () => {
    const r1 = createSettingsMutationRuntime();
    const r2 = createSettingsMutationRuntime();
    
    let r1Busy = false;
    let r2Busy = false;
    
    r1.subscribeQueue((busy: boolean) => { r1Busy = busy; });
    r2.subscribeQueue((busy: boolean) => { r2Busy = busy; });
    
    const store = createLudusaviStateStore();
    const rpc = await import("../api/ludusaviRpc");
    vi.mocked(rpc.setAutoSyncEnabled).mockResolvedValueOnce({ auto_sync_enabled: true } as any);
    
    r1.setActiveStore(store, vi.fn());
    const c1 = r1.createController({
      ludusaviStore: store,
      isMounted: { current: true },
      setBusyLabel: vi.fn(),
      notifyFailure: vi.fn()
    });
    
    c1.toggleAutoSync(true);
    
    expect(r1Busy).toBe(true);
    expect(r2Busy).toBe(false);
    
    await vi.runAllTimersAsync();
  });

  it("dispose clears + notifies false", async () => {
    const r1 = createSettingsMutationRuntime();
    const store = createLudusaviStateStore();
    const rpc = await import("../api/ludusaviRpc");

    let busyStatus = false;
    r1.subscribeQueue((busy: boolean) => { busyStatus = busy; });

    vi.mocked(rpc.setAutoSyncEnabled).mockReturnValueOnce(new Promise(() => {}));
    
    r1.setActiveStore(store, vi.fn());
    const c1 = r1.createController({
      ludusaviStore: store,
      isMounted: { current: true },
      setBusyLabel: vi.fn(),
      notifyFailure: vi.fn()
    });

    c1.toggleAutoSync(true);
    expect(busyStatus).toBe(true);

    r1.dispose();

    expect(busyStatus).toBe(false);
  });
  it("superseded RPC result does not clobber newer value", async () => {
    const store = createLudusaviStateStore();
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");

    runtime.setActiveStore(store, vi.fn());
    const controller = runtime.createController({
      ludusaviStore: store,
      isMounted: { current: true },
      setBusyLabel: vi.fn(),
      notifyFailure: vi.fn()
    });

    let resolveFirst: any;
    let resolveSecond: any;
    vi.mocked(rpc.setAutoSyncEnabled)
      .mockReturnValueOnce(new Promise(r => resolveFirst = r))
      .mockReturnValueOnce(new Promise(r => resolveSecond = r));

    controller.toggleAutoSync(true); // updateSeq 1
    controller.toggleAutoSync(false); // updateSeq 2

    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(false);

    // Resolve first (superseded)
    resolveFirst({ auto_sync_enabled: true } as any);
    await vi.runAllTimersAsync();

    // Still false
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(false);

    // Resolve second
    resolveSecond({ auto_sync_enabled: false } as any);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(false);
  });
  it("superseded RPC result does not clobber newer value for update_channel", async () => {
    const store = createLudusaviStateStore();
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");

    runtime.setActiveStore(store, vi.fn());
    const controller = runtime.createController({
      ludusaviStore: store,
      isMounted: { current: true },
      setBusyLabel: vi.fn(),
      notifyFailure: vi.fn()
    });

    let resolveFirst: any;
    let resolveSecond: any;
    vi.mocked(rpc.setUpdateChannelCall)
      .mockReturnValueOnce(new Promise(r => resolveFirst = r))
      .mockReturnValueOnce(new Promise(r => resolveSecond = r));

    controller.toggleUpdateChannel(true); // update_channel: development
    controller.toggleUpdateChannel(false); // update_channel: stable

    expect(store.getSnapshot().settings?.update_channel).toBe("stable");

    resolveFirst({ update_channel: "development" } as any);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().settings?.update_channel).toBe("stable");

    resolveSecond({ update_channel: "stable" } as any);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().settings?.update_channel).toBe("stable");
  });
});
