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

  it("settings writes do not trigger a disabling busy label (flicker regression)", async () => {
    const store = createLudusaviStateStore();
    store.applySettings({ auto_sync_enabled: false } as any);
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");
    
    const notifyFailure = vi.fn();

    runtime.setActiveStore(store, notifyFailure);
    const controller = runtime.createController({
      ludusaviStore: store,
      notifyFailure
    });

    let resolveRpc: (res: any) => void;
    vi.mocked(rpc.setAutoSyncEnabled).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRpc = resolve;
      })
    );
    let resolveRpcNotification: (res: any) => void;
    vi.mocked(rpc.setNotificationSettings).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRpcNotification = resolve;
      })
    );

    controller.toggleAutoSync(true);
    controller.toggleNotificationSetting("failures_errors", true);



    resolveRpc!({ auto_sync_enabled: true, notifications: { failures_errors: false } } as any);
    resolveRpcNotification!({ auto_sync_enabled: true, notifications: { failures_errors: true } } as any);
    
    // allow microtasks to clear
    await vi.runAllTimersAsync();

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


  it("superseded RPC result does not clobber newer value", async () => {
    const store = createLudusaviStateStore();
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");

    runtime.setActiveStore(store, vi.fn());
    const controller = runtime.createController({
      ludusaviStore: store,
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

  it("late resolution only applies its specific field and does not clobber newer unrelated settings", async () => {
    const store = createLudusaviStateStore();
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");

    runtime.setActiveStore(store, vi.fn());
    const controller = runtime.createController({
      ludusaviStore: store,
      notifyFailure: vi.fn()
    });

    store.applySettings({ auto_sync_enabled: false, selected_game: "A", update_channel: "stable", notifications: { failures_errors: false } } as any);

    let resolveAutoSync: any;
    let resolveSelectedGame: any;
    let resolveNotification: any;

    vi.mocked(rpc.setAutoSyncEnabled).mockReturnValueOnce(new Promise(r => resolveAutoSync = r));
    vi.mocked(rpc.setSelectedGameCall).mockReturnValueOnce(new Promise(r => resolveSelectedGame = r));
    vi.mocked(rpc.setNotificationSettings).mockReturnValueOnce(new Promise(r => resolveNotification = r));

    // 1. autoSync starts (generation 1)
    controller.toggleAutoSync(true);
    // 2. selectedGame starts (generation 2)
    controller.onGameChange("B");
    // 3. notifications start (generation 3)
    controller.toggleNotificationSetting("failures_errors", true);

    // Optimistically all are applied
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(true);
    expect(store.getSnapshot().settings?.selected_game).toBe("B");
    expect(store.getSnapshot().settings?.notifications.failures_errors).toBe(true);

    // 4. selectedGame succeeds! (generation 2 resolves)
    resolveSelectedGame({ auto_sync_enabled: false, selected_game: "B", update_channel: "stable", notifications: { failures_errors: false } } as any);
    await vi.runAllTimersAsync();

    // Since it was generation 2 (not latest, generation 3 is latest), it should ONLY merge selected_game.
    // It should NOT clobber the optimistic notifications or autoSync.
    expect(store.getSnapshot().settings?.selected_game).toBe("B");
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(true);
    expect(store.getSnapshot().settings?.notifications.failures_errors).toBe(true);

    // 5. autoSync succeeds late! (generation 1 resolves)
    resolveAutoSync({ auto_sync_enabled: true, selected_game: "A", update_channel: "stable", notifications: { failures_errors: false } } as any);
    await vi.runAllTimersAsync();

    // It should ONLY merge auto_sync_enabled.
    // It should NOT clobber the successfully persisted selected_game or the optimistic notifications.
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(true);
    expect(store.getSnapshot().settings?.selected_game).toBe("B");
    expect(store.getSnapshot().settings?.notifications.failures_errors).toBe(true);

    // 6. notifications succeeds! (generation 3 resolves)
    // This is the latest generation, so it applies the full snapshot.
    // However, the backend would return a snapshot reflecting all previous successes.
    resolveNotification({ auto_sync_enabled: true, selected_game: "B", update_channel: "stable", notifications: { failures_errors: true } } as any);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(true);
    expect(store.getSnapshot().settings?.selected_game).toBe("B");
    expect(store.getSnapshot().settings?.notifications.failures_errors).toBe(true);
  });
});
