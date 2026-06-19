import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createGameLifecycleController } from "./gameLifecycleController";
import type { AppLifetimeNotification } from "../types";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {
    RunningApps: [
      { appid: 1145300, display_name: "Hades" }
    ]
  },
}));

describe("GameLifecycleController", () => {
  let mockStore: any;
  let mockRpc: any;
  let mockStatusSurface: any;
  let mockResolveConflict: any;
  let mockNotifyFailure: any;
  let mockSyncGlobalHistory: any;
  let mockEnsureStateReady: any;
  let lifecycleCallback: (notification: AppLifetimeNotification) => void;

  beforeEach(() => {
    vi.useFakeTimers();
    globalThis.window = globalThis as any;
    
    mockStore = {
      isTracked: vi.fn().mockReturnValue(true),
      shouldPublishAutoSyncStatusBeforeRpc: vi.fn().mockReturnValue(true),
      getSnapshot: vi.fn().mockReturnValue({
        settings: {
          auto_sync_enabled: true,
        },
      }),
    };

    mockRpc = {
      checkGameStart: vi.fn().mockResolvedValue({ status: "needed", operation: "restore" }),
      restoreGameOnStart: vi.fn().mockResolvedValue({ status: "restored" }),
      resolveGameStartConflict: vi.fn(),
      checkGameExit: vi.fn().mockResolvedValue({ status: "needed", operation: "backup" }),
      backupGameOnExit: vi.fn().mockResolvedValue({ status: "backed_up" }),
      pauseGameProcess: vi.fn().mockResolvedValue({ status: "paused" }),
      resumeGameProcess: vi.fn().mockResolvedValue({ status: "resumed" }),
      startSyncthingActivityWatch: vi.fn().mockResolvedValue({ status: "watching", watch_id: "w1" }),
      getSyncthingActivity: vi.fn().mockResolvedValue({ status: "activity", watch_id: "w1", sample: null }),
      stopSyncthingActivityWatch: vi.fn().mockResolvedValue({ status: "stopped", watch_id: "w1" }),
    };

    mockStatusSurface = {
      publish: vi.fn(),
      hide: vi.fn(),
      complete: vi.fn(),
    };

    mockResolveConflict = vi.fn();
    mockNotifyFailure = vi.fn();
    mockSyncGlobalHistory = vi.fn();
    mockEnsureStateReady = vi.fn().mockResolvedValue(undefined);

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

  it("hydrates persisted settings before deciding whether to start the post-game watch", async () => {
    let snapshot: any = { settings: null };
    mockStore.getSnapshot.mockImplementation(() => snapshot);
    mockEnsureStateReady.mockImplementation(async () => {
      snapshot = {
        settings: {
          auto_sync_enabled: true,
        },
      };
    });
    mockRpc.getSyncthingActivity.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: { status: "idle", folder_state: "idle", timestamp_unix: 1000 },
    });

    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
      ensureStateReady: mockEnsureStateReady,
    });
    controller.start();

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockEnsureStateReady).toHaveBeenCalledOnce();
    expect(mockRpc.startSyncthingActivityWatch).toHaveBeenCalledWith(
      "post_game",
      "Hades",
      "1145300",
    );
    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "syncthing_pending_upload",
      expect.any(Object),
    );
  });

  it("successful backup plus initialized idle watch publishes pending", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    // Mock watcher to initialize with idle sample
    mockRpc.getSyncthingActivity.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: { status: "idle", timestamp_unix: 1000 },
    });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    triggerExit(1145300);
    
    // Let checks, backup, and handoff run
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith("syncthing_pending_upload", expect.any(Object));
    const kinds = mockStatusSurface.publish.mock.calls.map((c: any) => c[0]);
    expect(kinds.indexOf("has_backup")).toBeGreaterThanOrEqual(0);
    expect(kinds.indexOf("has_backup")).toBeLessThan(kinds.indexOf("syncthing_pending_upload"));
  });

  it("starts the buffered post-game watch when the frontend tracking cache is stale", async () => {
    mockStore.isTracked.mockReturnValue(false);
    mockRpc.getSyncthingActivity.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: { status: "idle", timestamp_unix: 1000 },
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

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockRpc.startSyncthingActivityWatch).toHaveBeenCalledWith(
      "post_game",
      "Hades",
      "1145300",
    );
    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "syncthing_pending_upload",
      expect.objectContaining({ tracked: false }),
    );
  });

  it("successful backup plus buffered activity publishes uploading directly", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.getSyncthingActivity.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: { status: "syncing", uploading: true, timestamp_unix: 1000 },
    });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    mockStatusSurface.complete.mockClear();

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith("syncthing_uploading", expect.any(Object));
  });

  it("successful backup plus buffered completion publishes complete directly", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    // Return uploading sample first, then 3 settled samples
    let pollCount = 0;
    mockRpc.startSyncthingActivityWatch.mockImplementation(() => {
      pollCount = 0;
      return Promise.resolve({ status: "watching", watch_id: "w1" });
    });

    mockRpc.getSyncthingActivity.mockImplementation(() => {
      pollCount++;
      if (pollCount === 1) {
        return Promise.resolve({
          status: "activity",
          watch_id: "w1",
          sample: { status: "syncing", uploading: true, timestamp_unix: 1000 }
        });
      } else {
        return Promise.resolve({
          status: "activity",
          watch_id: "w1",
          sample: { status: "idle", settled: true, timestamp_unix: 1000 + pollCount }
        });
      }
    });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith("syncthing_complete", expect.any(Object));
  });

  it("configured but unavailable Syncthing preserves backup and publishes warning", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.startSyncthingActivityWatch.mockResolvedValue({ status: "failed", reason: "api_unavailable", message: "api offline" });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    mockStatusSurface.complete.mockClear();

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "syncthing_unavailable",
      expect.objectContaining({ source: "rpc_result" }),
    );
    expect(mockStatusSurface.complete).not.toHaveBeenCalledWith(
      expect.objectContaining({ status: "failed" }),
      expect.any(Object),
    );
  });

  it("missing Syncthing configuration silently completes local backup", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({
      status: "skipped",
      reason: "not_configured",
      message: "not configured",
    });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      expect.objectContaining({ status: "backed_up" }),
      expect.any(Object),
    );
    expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
      "syncthing_unavailable",
      expect.any(Object),
    );
  });

  it("unshared Ludusavi backup path publishes a distinct warning", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({
      status: "skipped",
      reason: "folder_not_found",
      message: "path not shared",
    });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "syncthing_folder_not_found",
      expect.objectContaining({ source: "rpc_result" }),
    );
  });

  it("successful backup without connected peers publishes the no-peers warning", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({
      status: "skipped",
      reason: "no_connected_peers",
      message: "no peers connected",
    });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    mockNotifyFailure.mockClear();

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "syncthing_no_peers",
      expect.objectContaining({ source: "rpc_result" }),
    );
    expect(mockNotifyFailure).not.toHaveBeenCalled();
  });

  it("unshared folder reason maps to the path-not-shared warning", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({
      status: "skipped",
      reason: "folder_not_shared",
      message: "folder has no remote devices",
    });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "syncthing_folder_not_found",
      expect.objectContaining({ source: "rpc_result" }),
    );
  });

  it("pre-game no-peer detection produces no Syncthing warning", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();
    mockRpc.checkGameStart.mockResolvedValue({ status: "skipped", reason: "local_current" });
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({
      status: "skipped",
      reason: "no_connected_peers",
      message: "no peers connected",
    });

    triggerStart(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
      "syncthing_no_peers",
      expect.any(Object),
    );
    expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
      "syncthing_unavailable",
      expect.any(Object),
    );
    expect(mockNotifyFailure).not.toHaveBeenCalled();
  });

  it("never pauses or resumes a process during exit handling", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    mockRpc.pauseGameProcess.mockClear();
    mockRpc.resumeGameProcess.mockClear();

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockRpc.pauseGameProcess).not.toHaveBeenCalled();
    expect(mockRpc.resumeGameProcess).not.toHaveBeenCalled();
  });

  it("backup failure cancels the generation and publishes error", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.backupGameOnExit.mockResolvedValue({ status: "failed", reason: "disk_full" });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      expect.objectContaining({ status: "failed" }),
      expect.any(Object)
    );
    expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();
  });

  it("local_current cancels the generation before normal completion", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.checkGameExit.mockResolvedValue({ status: "skipped", reason: "local_current" });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      expect.objectContaining({ status: "skipped", reason: "local_current" }),
      expect.any(Object)
    );
    expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();
  });

  it("silent skip cancels the generation and hides", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.checkGameExit.mockResolvedValue({ status: "skipped", reason: "auto_sync_disabled" });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.hide).toHaveBeenCalled();
    expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();
  });

  it("newer app start suppresses older exit handler completion", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    // Delay backup call for the exit handler
    let resolveBackup: any;
    mockRpc.backupGameOnExit.mockReturnValue(new Promise((resolve) => {
      resolveBackup = resolve;
    }));

    // Start first
    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    // Trigger App Exit (Epoch 1)
    triggerExit(1145300);
    await vi.advanceTimersByTimeAsync(100);

    // Trigger App Start (Epoch 2)
    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    // Now resolve the older exit handler's backup
    resolveBackup({ status: "backed_up" });
    await vi.runAllTimersAsync();

    // Since a newer lifecycle epoch (start) has begun, the older exit handler's complete must be suppressed!
    const backedUpCalls = mockStatusSurface.complete.mock.calls.filter((call: any) => call[0]?.status === "backed_up");
    expect(backedUpCalls.length).toBe(0);
  });

  it("newer exit suppresses older exit handler for same game", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    let resolveBackup: any;
    mockRpc.backupGameOnExit.mockReturnValue(new Promise((resolve) => {
      resolveBackup = resolve;
    }));

    // Start first
    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    triggerExit(1145300); // Epoch 1
    await vi.advanceTimersByTimeAsync(100);

    // Start again before second exit
    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);

    triggerExit(1145300); // Epoch 2
    await vi.advanceTimersByTimeAsync(100);

    resolveBackup({ status: "backed_up" });
    await vi.runAllTimersAsync();

    // The older exit handler (Epoch 1) completion must be suppressed
    const backedUpCalls = mockStatusSurface.complete.mock.calls.filter((call: any) => call[0]?.status === "backed_up");
    expect(backedUpCalls.length).toBe(1);
  });

  it("early start silent skip cancels the pre-game watch", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.checkGameStart.mockResolvedValue({ status: "skipped", reason: "auto_sync_disabled" });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(200);

    expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();
  });

  it("conflict start cancels the pre-game watch while resolving conflict", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });

    let resolveFlow: any;
    mockResolveConflict.mockReturnValue(new Promise((resolve) => {
      resolveFlow = resolve;
    }));

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(200);

    expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();

    resolveFlow("keep_local");
    await vi.runAllTimersAsync();
  });

  it("conflict resolved with keep_local publishes the backing-up animation", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
    mockResolveConflict.mockResolvedValue("keep_local");
    mockRpc.resolveGameStartConflict.mockResolvedValue({ status: "backed_up" });

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.runAllTimersAsync();

    expect(mockRpc.resolveGameStartConflict).toHaveBeenCalledWith(
      "Hades",
      "1145300",
      "keep_local",
    );
    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "backing_up",
      expect.objectContaining({ source: "lifecycle_start" }),
    );
    expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
      "restoring",
      expect.anything(),
    );
  });

  it("conflict resolved with restore_backup publishes the restoring animation", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
    mockResolveConflict.mockResolvedValue("restore_backup");
    mockRpc.resolveGameStartConflict.mockResolvedValue({ status: "restored" });

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.publish).toHaveBeenCalledWith(
      "restoring",
      expect.objectContaining({ source: "lifecycle_start" }),
    );
    expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
      "backing_up",
      expect.anything(),
    );
  });

  it("skipped backup result on exit does not notify failure", async () => {
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    mockRpc.backupGameOnExit.mockResolvedValue({ status: "skipped", reason: "unmatched_game" });

    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100);
    mockNotifyFailure.mockClear();

    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      expect.objectContaining({ status: "skipped", reason: "unmatched_game" }),
      expect.any(Object)
    );
    expect(mockNotifyFailure).not.toHaveBeenCalled();
  });
});
