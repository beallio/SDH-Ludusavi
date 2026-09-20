import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@decky/api", () => ({ callable: () => () => Promise.resolve() }));
vi.mock("@decky/ui", () => ({
  Router: { RunningApps: [{ appid: 100, display_name: "Fixture" }] },
}));
vi.mock("../utils/logging", () => ({ log: vi.fn(), logUiEvent: vi.fn() }));

import { createGameLifecycleController } from "./gameLifecycleController";
import { createLudusaviStateStore } from "../state/ludusaviState";
import { createAutoSyncStatusSurface } from "../surfaces/autoSyncStatusSurface";

describe("details-status lifecycle cleanup", () => {
  let lifetimeCallback: (notification: unknown) => void;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("window", globalThis);
    vi.stubGlobal("SteamClient", {
      GameSessions: {
        RegisterForAppLifetimeNotifications: (callback: (notification: unknown) => void) => {
          lifetimeCallback = callback;
          return { unregister: vi.fn() };
        },
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("settles checking when the exit check rejects and its watch is canceled", async () => {
    const store = createLudusaviStateStore();
    store.applySettings({
      auto_sync_enabled: true, sync_disabled_games: [], selected_game: "",
      notifications: { enabled: true, auto_sync_progress: true, auto_sync_results: true, manual_operations: true, refresh_status: true, failures_errors: true, update_available: true },
      update_channel: "stable", automatic_update_checks: true, debug_logging: true,
    });
    store.applyRefreshResult({
      games: [{ name: "Fixture", steam_id: 100, configured: true, has_backup: true, needs_first_backup: false, error: null, status: "has_backup" }],
      aliases: {}, history: {}, dependency_error: null,
    });
    const surface = createAutoSyncStatusSurface({ setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() } as any, store);
    const rpc = {
      checkGameStart: vi.fn(), restoreGameOnStart: vi.fn(), resolveGameStartConflict: vi.fn(),
      checkGameExit: vi.fn().mockRejectedValue(new Error("check failed")), backupGameOnExit: vi.fn(),
      pauseGameProcess: vi.fn(), resumeGameProcess: vi.fn(), renewGameProcessPause: vi.fn(),
      startSyncthingActivityWatch: vi.fn().mockResolvedValue({ status: "watching", watch_id: "watch" }),
      getSyncthingActivity: vi.fn(), stopSyncthingActivityWatch: vi.fn().mockResolvedValue({ status: "stopped", watch_id: "watch" }),
    };
    const controller = createGameLifecycleController({
      store, rpc: rpc as any, statusSurface: surface, resolveConflict: vi.fn(), notifyFailure: vi.fn(), syncGlobalHistory: vi.fn(),
    });
    controller.start();

    lifetimeCallback({ unAppID: 100, nInstanceID: 1, bRunning: false });
    await vi.runAllTimersAsync();

    expect(store.getSnapshot().autoSyncObservations["100"].activity).toBe("unverified");
    expect(rpc.stopSyncthingActivityWatch).toHaveBeenCalled();
    await controller.dispose();
  });
});
