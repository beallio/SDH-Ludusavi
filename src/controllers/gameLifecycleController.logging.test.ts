import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createGameLifecycleController } from "./gameLifecycleController";
import type { AppLifetimeNotification } from "../types";

const { logMock } = vi.hoisted(() => ({
  logMock: vi.fn(),
}));

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {
    RunningApps: [{ appid: 1145300, display_name: "Hades" }],
  },
}));

vi.mock("../utils/logging", () => ({
  log: logMock,
  logUiEvent: vi.fn(),
}));

describe("GameLifecycleController diagnostic logging", () => {
  let mockStore: any;
  let mockRpc: any;
  let mockStatusSurface: any;
  let lifecycleCallback: (notification: AppLifetimeNotification) => void;

  beforeEach(() => {
    vi.useFakeTimers();
    globalThis.window = globalThis as any;
    logMock.mockClear();

    mockStore = {
      isTracked: vi.fn().mockReturnValue(true),
      isGameSyncDisabled: vi.fn().mockReturnValue(false),
      shouldPublishAutoSyncStatusBeforeRpc: vi.fn().mockReturnValue(true),
      getSnapshot: vi.fn().mockReturnValue({
        settings: { auto_sync_enabled: true },
        autoSyncNotificationsEnabled: true,
        trackedNames: new Set(["hades"]),
        trackedAppIDs: new Set(["1145300"]),
      }),
    };

    mockRpc = {
      checkGameStart: vi.fn().mockResolvedValue({ status: "skipped", reason: "local_current" }),
      restoreGameOnStart: vi.fn().mockResolvedValue({ status: "restored" }),
      resolveGameStartConflict: vi.fn(),
      checkGameExit: vi.fn().mockResolvedValue({ status: "skipped", reason: "local_current" }),
      backupGameOnExit: vi.fn().mockResolvedValue({ status: "backed_up" }),
      pauseGameProcess: vi.fn().mockResolvedValue({ status: "paused" }),
      resumeGameProcess: vi.fn().mockResolvedValue({ status: "resumed" }),
      startSyncthingActivityWatch: vi
        .fn()
        .mockResolvedValue({ status: "watching", watch_id: "w1" }),
      getSyncthingActivity: vi
        .fn()
        .mockResolvedValue({ status: "activity", watch_id: "w1", sample: null }),
      stopSyncthingActivityWatch: vi.fn().mockResolvedValue({ status: "stopped", watch_id: "w1" }),
    };

    mockStatusSurface = {
      publish: vi.fn(),
      hide: vi.fn(),
      complete: vi.fn(),
    };

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

  const createController = () =>
    createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: vi.fn(),
      notifyFailure: vi.fn(),
      syncGlobalHistory: vi.fn(),
    });

  const triggerStart = (appID: number) => {
    lifecycleCallback({ unAppID: appID, nInstanceID: 1, bRunning: true });
  };

  const triggerExit = (appID: number) => {
    lifecycleCallback({ unAppID: appID, nInstanceID: 1, bRunning: false });
  };

  const loggedMessages = () => logMock.mock.calls.map((call: any[]) => `${call[0]}:${call[1]}`);

  it("explains why the pre-check status bar is not shown on app start", async () => {
    mockStore.shouldPublishAutoSyncStatusBeforeRpc.mockReturnValue(false);
    mockStore.isTracked.mockReturnValue(false);
    mockStore.getSnapshot.mockReturnValue({
      settings: { auto_sync_enabled: true },
      autoSyncNotificationsEnabled: false,
      trackedNames: new Set(["hades"]),
      trackedAppIDs: new Set(["1145300"]),
    });

    const controller = createController();
    controller.start();

    triggerStart(1145300);
    await vi.runAllTimersAsync();

    const messages = loggedMessages();
    expect(
      messages.some(
        (message) =>
          message.includes("status bar not shown") &&
          message.includes("tracked=false") &&
          message.includes("autoSyncNotificationsEnabled=false"),
      ),
    ).toBe(true);
    expect(mockStatusSurface.publish).not.toHaveBeenCalledWith("checking", expect.any(Object));
  });

  it("logs when a stale lifecycle epoch drops a status update", async () => {
    let resolveCheck: (value: unknown) => void = () => {};
    mockRpc.checkGameStart.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveCheck = resolve;
        }),
    );

    const controller = createController();
    controller.start();

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(0);

    // A newer lifecycle event supersedes the in-flight start handler.
    triggerExit(1145300);
    await vi.advanceTimersByTimeAsync(0);

    resolveCheck({ status: "failed", game: "Hades" });
    await vi.runAllTimersAsync();

    const messages = loggedMessages();
    expect(
      messages.some((message) => message.startsWith("debug:") && message.includes("stale")),
    ).toBe(true);
  });
});
