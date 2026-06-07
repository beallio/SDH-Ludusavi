import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createGameLifecycleController } from "./gameLifecycleController";
import type { AppLifetimeNotification } from "../types";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {
    RunningApps: [{ appid: 2405230651, display_name: "Wobbly Life" }],
  },
}));

describe("GameLifecycleController – tracked promotion", () => {
  let mockStore: any;
  let mockRpc: any;
  let mockStatusSurface: any;
  let mockResolveConflict: any;
  let mockNotifyFailure: any;
  let mockSyncGlobalHistory: any;
  let lifecycleCallback: (notification: AppLifetimeNotification) => void;

  beforeEach(() => {
    vi.useFakeTimers();
    globalThis.window = globalThis as any;

    // Simulate the timing race: isTracked returns false (state not yet hydrated)
    mockStore = {
      isTracked: vi.fn().mockReturnValue(false),
      shouldPublishAutoSyncStatusBeforeRpc: vi.fn().mockReturnValue(true),
      getSnapshot: vi.fn().mockReturnValue({
        settings: {
          auto_sync_enabled: true,
        },
      }),
    };

    mockRpc = {
      checkGameStart: vi.fn().mockResolvedValue({ status: "skipped", reason: "local_current" }),
      restoreGameOnStart: vi.fn().mockResolvedValue({ status: "restored" }),
      resolveGameStartConflict: vi.fn(),
      // Backend confirms backup needed (authoritative match)
      checkGameExit: vi.fn().mockResolvedValue({
        status: "needed",
        operation: "backup",
        game: "Wobbly Life",
      }),
      backupGameOnExit: vi.fn().mockResolvedValue({ status: "backed_up" }),
      pauseGameProcess: vi.fn().mockResolvedValue({ status: "paused" }),
      resumeGameProcess: vi.fn().mockResolvedValue({ status: "resumed" }),
      startSyncthingActivityWatch: vi
        .fn()
        .mockResolvedValue({ status: "watching", watch_id: "w1" }),
      getSyncthingActivity: vi.fn().mockResolvedValue({
        status: "activity",
        watch_id: "w1",
        sample: { status: "idle", timestamp_unix: 1000 },
      }),
      stopSyncthingActivityWatch: vi
        .fn()
        .mockResolvedValue({ status: "stopped", watch_id: "w1" }),
    };

    mockStatusSurface = {
      publish: vi.fn(),
      hide: vi.fn(),
      complete: vi.fn(),
    };

    mockResolveConflict = vi.fn();
    mockNotifyFailure = vi.fn();
    mockSyncGlobalHistory = vi.fn();

    const mockRegister = vi.fn((cb) => {
      lifecycleCallback = cb;
      return { unregister: vi.fn() };
    });

    (globalThis as any).SteamClient = {
      GameSessions: {
        RegisterForAppLifetimeNotifications: mockRegister,
      },
    } as any;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    delete (globalThis as any).SteamClient;
  });

  const triggerStart = (appID: number) => {
    lifecycleCallback({ unAppID: appID, nInstanceID: 1, bRunning: true });
  };

  const triggerExit = (appID: number) => {
    lifecycleCallback({ unAppID: appID, nInstanceID: 1, bRunning: false });
  };

  it(
    "starts Syncthing watch when backend confirms backup needed even if isTracked was false",
    async () => {
      const controller = createGameLifecycleController({
        store: mockStore,
        rpc: mockRpc,
        statusSurface: mockStatusSurface,
        resolveConflict: mockResolveConflict,
        notifyFailure: mockNotifyFailure,
        syncGlobalHistory: mockSyncGlobalHistory,
      });
      controller.start();

      triggerStart(2405230651);
      await vi.advanceTimersByTimeAsync(100);

      triggerExit(2405230651);
      await vi.runAllTimersAsync();

      // Backend confirmed match → Syncthing watch must be started
      expect(mockRpc.startSyncthingActivityWatch).toHaveBeenCalledWith(
        "post_game",
        "Wobbly Life",
        "2405230651",
      );
    },
  );

  it(
    "does not start Syncthing watch when check_game_exit returns local_current (unmatched game)",
    async () => {
      mockRpc.checkGameExit.mockResolvedValue({
        status: "skipped",
        reason: "unmatched_game",
      });

      const controller = createGameLifecycleController({
        store: mockStore,
        rpc: mockRpc,
        statusSurface: mockStatusSurface,
        resolveConflict: mockResolveConflict,
        notifyFailure: mockNotifyFailure,
        syncGlobalHistory: mockSyncGlobalHistory,
      });
      controller.start();

      triggerStart(2405230651);
      await vi.advanceTimersByTimeAsync(100);

      triggerExit(2405230651);
      await vi.runAllTimersAsync();

      // Truly unmatched → no watch
      expect(mockRpc.startSyncthingActivityWatch).not.toHaveBeenCalledWith(
        "post_game",
        expect.any(String),
        expect.any(String),
      );
    },
  );

  it(
    "does not start Syncthing watch when check_game_exit returns local_current (no backup needed)",
    async () => {
      mockRpc.checkGameExit.mockResolvedValue({
        status: "skipped",
        reason: "local_current",
      });

      const controller = createGameLifecycleController({
        store: mockStore,
        rpc: mockRpc,
        statusSurface: mockStatusSurface,
        resolveConflict: mockResolveConflict,
        notifyFailure: mockNotifyFailure,
        syncGlobalHistory: mockSyncGlobalHistory,
      });
      controller.start();

      triggerStart(2405230651);
      await vi.advanceTimersByTimeAsync(100);

      triggerExit(2405230651);
      await vi.runAllTimersAsync();

      expect(mockRpc.startSyncthingActivityWatch).not.toHaveBeenCalledWith(
        "post_game",
        expect.any(String),
        expect.any(String),
      );
    },
  );
});
