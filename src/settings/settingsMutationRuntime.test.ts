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
    setGameSyncEnabledCall: vi.fn(),
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
    vi.clearAllMocks();
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

  it("keeps the displayed game when auto-sync returns a different persisted preference", async () => {
    const store = createLudusaviStateStore();
    const runtime = createSettingsMutationRuntime();
    const rpc = await import("../api/ludusaviRpc");
    runtime.applySettings(store, {
      auto_sync_enabled: false,
      selected_game: "B",
      sync_disabled_games: [],
    } as any);
    store.setDisplayedGame("A");
    const controller = runtime.createController({
      ludusaviStore: store,
      notifyFailure: vi.fn(),
    });
    vi.mocked(rpc.setAutoSyncEnabled).mockResolvedValueOnce({
      auto_sync_enabled: true,
      selected_game: "B",
      sync_disabled_games: [],
    } as any);

    controller.toggleAutoSync(true);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().selectedGame).toBe("A");
    expect(store.getSnapshot().settings?.selected_game).toBe("B");
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

    // The displayed game updates optimistically, but the persisted preference
    // remains unchanged until the selection RPC resolves.
    expect(store.getSnapshot().settings?.auto_sync_enabled).toBe(true);
    expect(store.getSnapshot().settings?.selected_game).toBe("A");
    expect(store.getSnapshot().settings?.notifications.failures_errors).toBe(true);

    // 4. selectedGame succeeds, but remains queued behind autoSync.
    resolveSelectedGame({ auto_sync_enabled: false, selected_game: "B", update_channel: "stable", notifications: { failures_errors: false } } as any);
    await vi.runAllTimersAsync();

    // The resolved selection is not persisted into the settings mirror until
    // the earlier mutation finishes and the queued selection is applied.
    expect(store.getSnapshot().settings?.selected_game).toBe("A");
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

  function setupGameSync(disabledGames: string[] = []) {
    const store = createLudusaviStateStore();
    const runtime = createSettingsMutationRuntime();
    const notifyFailure = vi.fn();
    runtime.applySettings(store, {
      auto_sync_enabled: true,
      sync_disabled_games: disabledGames,
    } as any);
    const controller = runtime.createController({
      ludusaviStore: store,
      notifyFailure,
    });
    return { store, runtime, controller, notifyFailure };
  }

  it("optimistically updates one game and applies a successful result", async () => {
    const rpc = await import("../api/ludusaviRpc");
    const { store, controller } = setupGameSync();
    vi.mocked(rpc.setGameSyncEnabledCall).mockResolvedValueOnce({
      sync_disabled_games: ["Hades"],
    } as any);

    controller.toggleGameSync("Hades", false);
    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["Hades"]);

    await vi.runAllTimersAsync();
    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["Hades"]);
  });

  it("keeps the displayed game when game sync returns a different persisted preference", async () => {
    const rpc = await import("../api/ludusaviRpc");
    const { store, runtime, controller } = setupGameSync();
    runtime.applySettings(store, {
      ...store.getSnapshot().settings,
      selected_game: "B",
    } as any);
    store.setDisplayedGame("A");
    vi.mocked(rpc.setGameSyncEnabledCall).mockResolvedValueOnce({
      ...store.getSnapshot().settings,
      selected_game: "B",
      sync_disabled_games: ["A"],
    } as any);

    controller.toggleGameSync("A", false);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().selectedGame).toBe("A");
    expect(store.getSnapshot().settings?.selected_game).toBe("B");
  });

  it("rolls back only the failed game against hydrated persisted state", async () => {
    const rpc = await import("../api/ludusaviRpc");
    const { store, controller } = setupGameSync(["Hades"]);
    vi.mocked(rpc.setGameSyncEnabledCall).mockRejectedValueOnce(new Error("RPC failed"));

    controller.toggleGameSync("Celeste", false);
    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["Celeste", "Hades"]);

    await vi.runAllTimersAsync();
    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["Hades"]);
  });

  it("keeps A persisted when A succeeds and B fails", async () => {
    const rpc = await import("../api/ludusaviRpc");
    const { store, controller } = setupGameSync();
    vi.mocked(rpc.setGameSyncEnabledCall)
      .mockResolvedValueOnce({ sync_disabled_games: ["A"] } as any)
      .mockRejectedValueOnce(new Error("B failed"));

    controller.toggleGameSync("A", false);
    controller.toggleGameSync("B", false);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["A"]);
  });

  it("applies a late success after timeout rollback", async () => {
    const rpc = await import("../api/ludusaviRpc");
    const { store, controller, notifyFailure } = setupGameSync();
    const originalSetTimeout = window.setTimeout;
    const originalClearTimeout = window.clearTimeout;
    window.setTimeout = globalThis.setTimeout;
    window.clearTimeout = globalThis.clearTimeout;
    let resolveRpc: (settings: any) => void = () => {};
    vi.mocked(rpc.setGameSyncEnabledCall).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRpc = resolve;
      }),
    );

    controller.toggleGameSync("Hades", false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual([]);
    expect(notifyFailure).toHaveBeenCalledTimes(1);

    resolveRpc({ sync_disabled_games: ["Hades"] });
    await vi.runAllTimersAsync();
    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["Hades"]);
    window.setTimeout = originalSetTimeout;
    window.clearTimeout = originalClearTimeout;
  });

  it("tracks rapid toggles for different games independently", async () => {
    const rpc = await import("../api/ludusaviRpc");
    const { store, controller } = setupGameSync();
    vi.mocked(rpc.setGameSyncEnabledCall)
      .mockResolvedValueOnce({ sync_disabled_games: ["A"] } as any)
      .mockResolvedValueOnce({ sync_disabled_games: ["A", "B"] } as any);

    controller.toggleGameSync("A", false);
    controller.toggleGameSync("B", false);
    await vi.runAllTimersAsync();

    expect(rpc.setGameSyncEnabledCall).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["A", "B"]);
  });

  it("rolls a failed same-game re-enable back to the preceding successful disable", async () => {
    const rpc = await import("../api/ludusaviRpc");
    const { store, controller } = setupGameSync();
    vi.mocked(rpc.setGameSyncEnabledCall)
      .mockResolvedValueOnce({ sync_disabled_games: ["A"] } as any)
      .mockRejectedValueOnce(new Error("re-enable failed"));

    controller.toggleGameSync("A", false);
    controller.toggleGameSync("A", true);
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().settings?.sync_disabled_games).toEqual(["A"]);
  });
});
