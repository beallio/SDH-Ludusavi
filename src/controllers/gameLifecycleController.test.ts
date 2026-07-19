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
      isGameSyncDisabled: vi.fn().mockReturnValue(false),
      shouldPublishAutoSyncStatusBeforeRpc: vi.fn().mockReturnValue(true),
      getSnapshot: vi.fn().mockReturnValue({
        settings: {
          auto_sync_enabled: true,
        },
        trackingReadiness: "ready",
      }),
    };

    mockRpc = {
      checkGameStart: vi.fn().mockResolvedValue({ status: "needed", operation: "restore" }),
      restoreGameOnStart: vi.fn().mockResolvedValue({ status: "restored" }),
      resolveGameStartConflict: vi.fn(),
      checkGameExit: vi.fn().mockResolvedValue({ status: "needed", operation: "backup" }),
      backupGameOnExit: vi.fn().mockResolvedValue({ status: "backed_up" }),
      pauseGameProcess: vi.fn().mockResolvedValue({
        status: "paused",
        pid: 2,
        lease_id: "mock_lease",
        lease_ttl_seconds: 30,
      }),
      resumeGameProcess: vi.fn().mockResolvedValue({ status: "resumed" }),
      renewGameProcessPause: vi.fn().mockResolvedValue({ status: "renewed" }),
      startSyncthingActivityWatch: vi.fn().mockResolvedValue({ status: "watching", watch_id: "w1" }),
      getSyncthingActivity: vi.fn().mockResolvedValue({
        status: "activity",
        watch_id: "w1",
        sample: {
          status: "IDLE",
          folder_state: "idle",
          update_in_progress: false,
          settled: true,
          downloading: false,
          uploading: false,
          timestamp_unix: 1,
        },
      }),
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
    let snapshot: any = { settings: null, trackingReadiness: "cold" };
    mockStore.getSnapshot.mockImplementation(() => snapshot);
    mockEnsureStateReady.mockImplementation(async () => {
      snapshot = {
        settings: {
          auto_sync_enabled: true,
        },
        trackingReadiness: "ready",
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
    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      { status: "backed_up" },
      expect.objectContaining({ lifecycle: "lifecycle_exit" }),
    );
    expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
      "has_backup",
      expect.objectContaining({ source: "lifecycle_exit" }),
    );
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

  it("holds the launch pause through pre-game settlement and acts only on a fresh check", async () => {
    mockRpc.checkGameStart
      .mockResolvedValueOnce({ status: "skipped", reason: "local_current" })
      .mockResolvedValueOnce({ status: "needed", operation: "restore" });
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({ status: "watching", watch_id: "w1" });
    mockRpc.getSyncthingActivity
      .mockResolvedValueOnce({ status: "activity", watch_id: "w1", sample: { status: "ACTIVE_TRANSFER", folder_state: "syncing", uploading: false, downloading: true, update_in_progress: false, settled: false, timestamp_unix: 1 } })
      .mockResolvedValueOnce({ status: "activity", watch_id: "w1", sample: { status: "IDLE", folder_state: "idle", uploading: false, downloading: false, update_in_progress: false, settled: true, timestamp_unix: 2 } })
      .mockResolvedValueOnce({ status: "activity", watch_id: "w1", sample: { status: "IDLE", folder_state: "idle", uploading: false, downloading: false, update_in_progress: false, settled: true, timestamp_unix: 3 } })
      .mockResolvedValueOnce({ status: "activity", watch_id: "w1", sample: { status: "IDLE", folder_state: "idle", uploading: false, downloading: false, update_in_progress: false, settled: true, timestamp_unix: 4 } });
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(mockRpc.resumeGameProcess).not.toHaveBeenCalled();
    expect(mockRpc.restoreGameOnStart).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(500);

    expect(mockRpc.checkGameStart).toHaveBeenCalledTimes(2);
    expect(mockRpc.restoreGameOnStart).toHaveBeenCalledOnce();
    expect(mockRpc.resumeGameProcess).toHaveBeenCalledOnce();
    expect(mockStatusSurface.publish.mock.calls.filter((call: any[]) => call[0] === "checking")).toHaveLength(2);
    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      expect.objectContaining({ status: "restored" }),
      expect.objectContaining({ lifecycle: "lifecycle_start" }),
    );
  });

  it("uses the original check without delay when the pre-game watch initializes idle", async () => {
    mockRpc.checkGameStart.mockResolvedValue({ status: "needed", operation: "restore" });
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({ status: "watching", watch_id: "w1" });
    mockRpc.getSyncthingActivity.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: { status: "IDLE", folder_state: "idle", uploading: false, downloading: false, update_in_progress: false, settled: true, timestamp_unix: 1 },
    });
    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(1);

    expect(mockRpc.checkGameStart).toHaveBeenCalledOnce();
    expect(mockRpc.restoreGameOnStart).toHaveBeenCalledOnce();
    expect(mockRpc.resumeGameProcess).toHaveBeenCalledOnce();
  });

  it("fails safely after active pre-game polling is interrupted and still resumes", async () => {
    mockRpc.checkGameStart.mockResolvedValue({ status: "skipped", reason: "local_current" });
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({ status: "watching", watch_id: "w1" });
    mockRpc.getSyncthingActivity
      .mockResolvedValueOnce({ status: "activity", watch_id: "w1", sample: { status: "ACTIVE_TRANSFER", folder_state: "syncing", uploading: false, downloading: true, update_in_progress: false, settled: false, timestamp_unix: 1 } })
      .mockResolvedValueOnce({ status: "failed", reason: "connection_lost", message: "lost" });
    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(500);

    expect(mockStatusSurface.publish).toHaveBeenCalledWith("error", expect.any(Object));
    expect(mockNotifyFailure).toHaveBeenCalledOnce();
    expect(mockRpc.restoreGameOnStart).not.toHaveBeenCalled();
    expect(mockRpc.resolveGameStartConflict).not.toHaveBeenCalled();
    expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalledWith("w1");
    expect(mockRpc.resumeGameProcess).toHaveBeenCalledOnce();
  });

  it("preserves the original restore decision when the watch is unavailable before activity", async () => {
    mockRpc.checkGameStart.mockResolvedValue({ status: "needed", operation: "restore" });
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({ status: "skipped", reason: "no_connected_peers", message: "no peers" });
    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(1);

    expect(mockRpc.checkGameStart).toHaveBeenCalledOnce();
    expect(mockRpc.restoreGameOnStart).toHaveBeenCalledOnce();
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
    mockRpc.getSyncthingActivity.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: null,
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

  it("disabled game never pauses or starts any pre-game or post-game watch", async () => {
    mockStore.isGameSyncDisabled.mockReturnValue(true);
    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
    mockResolveConflict.mockResolvedValue("keep_local");
    mockRpc.resolveGameStartConflict.mockResolvedValue({ status: "backed_up" });
    mockRpc.checkGameExit.mockResolvedValue({
      status: "skipped",
      reason: "game_sync_disabled",
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

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.runAllTimersAsync();
    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockRpc.pauseGameProcess).not.toHaveBeenCalled();
    expect(mockRpc.startSyncthingActivityWatch).not.toHaveBeenCalled();
    expect(mockStore.isGameSyncDisabled).toHaveBeenCalledWith("Hades", "1145300");
  });

  it("enabled game still pauses and starts initial, restarted, and post-game watches", async () => {
    mockStore.isGameSyncDisabled.mockReturnValue(false);
    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
    mockResolveConflict.mockResolvedValue("keep_local");
    mockRpc.resolveGameStartConflict.mockResolvedValue({ status: "backed_up" });
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.runAllTimersAsync();
    triggerExit(1145300);
    await vi.runAllTimersAsync();

    expect(mockRpc.pauseGameProcess).toHaveBeenCalledWith(2);
    expect(mockRpc.startSyncthingActivityWatch.mock.calls).toEqual(
      expect.arrayContaining([
        ["pre_game", "Hades", "1145300"],
        ["post_game", "Hades", "1145300"],
      ]),
    );
    expect(
      mockRpc.startSyncthingActivityWatch.mock.calls.filter(
        ([phase]: [string]) => phase === "pre_game",
      ),
    ).toHaveLength(2);
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
      2,
      "mock_lease",
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

  it("conflict dismissal completes with the explicit unresolved status and no failure toast", async () => {
    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
    mockResolveConflict.mockResolvedValue(null);
    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(1);

    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      { status: "skipped", game: "Hades", reason: "conflict_unresolved" },
      expect.objectContaining({ lifecycle: "lifecycle_start" }),
    );
    expect(mockNotifyFailure).not.toHaveBeenCalled();
    expect(mockRpc.resumeGameProcess).toHaveBeenCalledOnce();
  });

  it("drops a stale first check when a newer lifecycle supersedes the quiescence wait", async () => {
    mockRpc.checkGameStart.mockResolvedValue({ status: "skipped", reason: "local_current" });
    mockRpc.checkGameExit.mockResolvedValue({ status: "skipped", reason: "auto_sync_disabled" });
    mockRpc.startSyncthingActivityWatch.mockResolvedValue({ status: "watching", watch_id: "w1" });
    mockRpc.getSyncthingActivity.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: { status: "ACTIVE_TRANSFER", folder_state: "syncing", uploading: false, downloading: true, update_in_progress: false, settled: false, timestamp_unix: 1 },
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

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(1);
    triggerExit(1145300);
    await vi.advanceTimersByTimeAsync(1);

    expect(mockRpc.checkGameStart).toHaveBeenCalledOnce();
    expect(mockRpc.restoreGameOnStart).not.toHaveBeenCalled();
    expect(mockStatusSurface.complete).not.toHaveBeenCalledWith(
      expect.objectContaining({ reason: "local_current" }),
      expect.any(Object),
    );
    expect(mockRpc.resumeGameProcess).toHaveBeenCalledOnce();
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

  it("cold cache + known backend conflict pauses and allows the modal/action path", async () => {
    mockStore.getSnapshot.mockReturnValue({
      settings: { auto_sync_enabled: true },
      trackingReadiness: "cold",
    });
    mockStore.isTracked.mockReturnValue(false); // Frontend doesn't know it yet
    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });

    let resolveFlow: any;
    mockResolveConflict.mockReturnValue(new Promise((resolve) => { resolveFlow = resolve; }));

    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory, ensureStateReady: mockEnsureStateReady,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(100);

    // It should pause conservatively
    expect(mockRpc.pauseGameProcess).toHaveBeenCalled();
    expect(mockRpc.checkGameStart).toHaveBeenCalled();

    // After backend confirms conflict, it should show the conflict UI (waiting for resolve)
    resolveFlow("keep_local");
    mockRpc.resolveGameStartConflict.mockResolvedValue({ status: "backed_up" });
    await vi.runAllTimersAsync();

    expect(mockRpc.resolveGameStartConflict).toHaveBeenCalled();
  });

  it("cold cache + unmatched backend result pauses briefly, then resumes and cancels the watch", async () => {
    mockStore.getSnapshot.mockReturnValue({
      settings: { auto_sync_enabled: true },
      trackingReadiness: "cold",
    });
    mockStore.isTracked.mockReturnValue(false);
    mockRpc.checkGameStart.mockResolvedValue({ status: "unmatched_game", reason: "not_in_db" });

    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory, ensureStateReady: mockEnsureStateReady,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(100);

    expect(mockRpc.pauseGameProcess).toHaveBeenCalled();
    expect(mockRpc.checkGameStart).toHaveBeenCalled();

    // It should resume and cancel watch
    await vi.runAllTimersAsync();
    expect(mockRpc.resumeGameProcess).toHaveBeenCalled();
  });

  it("ready cache + untracked game does not pause", async () => {
    mockStore.getSnapshot.mockReturnValue({
      settings: { auto_sync_enabled: true },
      trackingReadiness: "ready",
    });
    mockStore.isTracked.mockReturnValue(false);

    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory, ensureStateReady: mockEnsureStateReady,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.runAllTimersAsync();

    expect(mockRpc.pauseGameProcess).not.toHaveBeenCalled();
    expect(mockRpc.checkGameStart).toHaveBeenCalled();
  });

  it("failed tracking hydration follows the cold conservative path and emits one diagnostic", async () => {
    mockStore.getSnapshot.mockReturnValue({
      settings: { auto_sync_enabled: true },
      trackingReadiness: "failed",
    });
    mockStore.isTracked.mockReturnValue(false);
    mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });

    let resolveFlow: any;
    mockResolveConflict.mockReturnValue(new Promise((resolve) => { resolveFlow = resolve; }));

    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory, ensureStateReady: mockEnsureStateReady,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
    await vi.advanceTimersByTimeAsync(200);

    expect(mockRpc.pauseGameProcess).toHaveBeenCalled();
    expect(mockRpc.checkGameStart).toHaveBeenCalled();

    resolveFlow("keep_local");
    await vi.runAllTimersAsync();

    // For exit check, it should call checkGameExit and not just skip
    mockRpc.checkGameExit.mockResolvedValue({ status: "needed", operation: "backup" });
    lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: false });
    await vi.runAllTimersAsync();

    expect(mockRpc.checkGameExit).toHaveBeenCalled();
  });

  it("invalid PID cannot be falsely reported as guarded", async () => {
    mockStore.getSnapshot.mockReturnValue({
      settings: { auto_sync_enabled: true },
      trackingReadiness: "cold",
    });
    mockStore.isTracked.mockReturnValue(false);
    mockRpc.checkGameStart.mockResolvedValue({ status: "needed", operation: "restore" });

    const controller = createGameLifecycleController({
      store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory, ensureStateReady: mockEnsureStateReady,
    });
    controller.start();

    lifecycleCallback({ unAppID: 1145300, nInstanceID: undefined as any, bRunning: true });
    await vi.runAllTimersAsync();

    expect(mockRpc.pauseGameProcess).not.toHaveBeenCalled();
    // But since it needed restore and wasn't paused, it skips and notifies failure
    expect(mockStatusSurface.complete).toHaveBeenCalledWith(
      expect.objectContaining({ status: "failed" }),
      expect.any(Object)
    );
  });

  it("awaits syncthingMonitor.stop() before allocating the next watch", async () => {
    mockStore.isTracked.mockReturnValue(true);
    let stopResolved = false;

    // Make checkGameStart slow so handleAppStart stays pending and pre_game watch stays active
    mockRpc.checkGameStart.mockImplementation(async () => {
      return new Promise((resolve) => setTimeout(() => resolve({ status: "needed", operation: "restore" }), 500));
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

    // Start creates a pre-game watch. Since checkGameStart is slow, it won't finish and cancel it.
    triggerStart(1145300);
    await vi.advanceTimersByTimeAsync(100); // Allow startSyncthingActivityWatch to resolve so wID is set

    // NOW make stopSyncthingActivityWatch resolve slowly so we can check that start is delayed
    mockRpc.stopSyncthingActivityWatch.mockImplementation(async () => {
      return new Promise((resolve) => {
        setTimeout(() => {
          stopResolved = true;
          resolve({ status: "stopped", watch_id: "w1" });
        }, 1000);
      });
    });

    // Exit causes handleAppExit to run, which starts by awaiting syncthingMonitor.stop()
    triggerExit(1145300);

    // Advance slightly, enough to trigger stop() but not to resolve it
    await vi.advanceTimersByTimeAsync(100);
    expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();
    // The start (post_game) should NOT have been called yet because stop() is pending
    expect(mockRpc.startSyncthingActivityWatch).not.toHaveBeenCalledWith("post_game", "Hades", "1145300");

    // Advance time past the 1000ms delay of stop
    await vi.advanceTimersByTimeAsync(1500);

    expect(stopResolved).toBe(true);
    // NOW it should be called
    expect(mockRpc.startSyncthingActivityWatch).toHaveBeenCalledWith("post_game", "Hades", "1145300");
  });

  describe("lease safety and atomic protection", () => {
    let controller: any;
    let resolveConflictFlow: any;

    beforeEach(() => {
      mockStore.getSnapshot.mockReturnValue({
        settings: { auto_sync_enabled: true },
        trackingReadiness: "ready",
      });
      mockStore.isTracked.mockReturnValue(true);

      mockResolveConflict.mockReturnValue(new Promise(resolve => {
        resolveConflictFlow = resolve;
      }));

      controller = createGameLifecycleController({
        store: mockStore, rpc: mockRpc, statusSurface: mockStatusSurface,
        resolveConflict: mockResolveConflict, notifyFailure: mockNotifyFailure,
        syncGlobalHistory: mockSyncGlobalHistory, ensureStateReady: mockEnsureStateReady,
      });
      controller.start();
    });

    it("60-second unresolved conflict renews lease but waits", async () => {
      mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });

      lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
      await vi.advanceTimersByTimeAsync(100);

      // Advance 60 seconds at the five-second renewal cadence.
      for (let i = 0; i < 12; i++) {
        await vi.advanceTimersByTimeAsync(5000);
      }

      expect(mockRpc.renewGameProcessPause).toHaveBeenCalledTimes(12);
      expect(mockRpc.resolveGameStartConflict).not.toHaveBeenCalled();

      resolveConflictFlow("keep_local");
      await vi.runAllTimersAsync();

      expect(mockRpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    });

    it("loss before restore prevents mutation", async () => {
      let resolveCheck: any;
      mockRpc.checkGameStart.mockReturnValue(new Promise(resolve => { resolveCheck = resolve; }));

      lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
      await vi.advanceTimersByTimeAsync(100);

      // Simulate loss
      mockRpc.renewGameProcessPause.mockResolvedValue({ status: "failed" });
      await vi.advanceTimersByTimeAsync(5000);

      // Resolve check now, which says restore needed
      resolveCheck({ status: "needed", operation: "restore" });
      await vi.runAllTimersAsync();

      expect(mockRpc.restoreGameOnStart).not.toHaveBeenCalled();
      expect(mockRpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    });

    it("loss before conflict mutation prevents mutation", async () => {
      mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
      lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
      await vi.advanceTimersByTimeAsync(100);

      // Simulate loss
      mockRpc.renewGameProcessPause.mockResolvedValue({ status: "failed" });
      await vi.advanceTimersByTimeAsync(5000);

      resolveConflictFlow("keep_local");
      await vi.runAllTimersAsync();

      expect(mockRpc.resolveGameStartConflict).not.toHaveBeenCalled();
      expect(mockRpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    });

    it("loss during check aborts cleanly", async () => {
      let resolveCheck: any;
      mockRpc.checkGameStart.mockReturnValue(new Promise(resolve => { resolveCheck = resolve; }));
      lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
      await vi.advanceTimersByTimeAsync(100);

      mockRpc.renewGameProcessPause.mockResolvedValue({ status: "failed" });
      await vi.advanceTimersByTimeAsync(5000);

      resolveCheck({ status: "skipped" });
      await vi.runAllTimersAsync();

      expect(mockRpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    });

    it("dispose during check/conflict cancels watch and status updates", async () => {
      mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
      lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
      await vi.advanceTimersByTimeAsync(100);

      // Controller disposed while waiting for user conflict resolution
      await controller.dispose();
      await vi.runAllTimersAsync();

      // Resolve the promise now - but controller is disposed
      resolveConflictFlow("keep_local");
      await vi.runAllTimersAsync();

      expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();
      expect(mockRpc.resolveGameStartConflict).not.toHaveBeenCalled();
      const backUpCalls = mockStatusSurface.publish.mock.calls.filter((c: any) => c[0] === "backing_up");
      expect(backUpCalls.length).toBe(0);
      expect(mockRpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    });

    it("dispose during the backend check prevents every later mutation and status write", async () => {
      let resolveCheck: ((result: { status: "needed"; operation: "restore" }) => void) | undefined;
      mockRpc.checkGameStart.mockReturnValue(
        new Promise((resolve) => {
          resolveCheck = resolve;
        }),
      );
      lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
      await vi.advanceTimersByTimeAsync(100);
      const publishCountAtDispose = mockStatusSurface.publish.mock.calls.length;
      const completeCountAtDispose = mockStatusSurface.complete.mock.calls.length;

      await controller.dispose();
      resolveCheck?.({ status: "needed", operation: "restore" });
      await vi.runAllTimersAsync();

      expect(mockRpc.restoreGameOnStart).not.toHaveBeenCalled();
      expect(mockRpc.resolveGameStartConflict).not.toHaveBeenCalled();
      expect(mockStatusSurface.publish).toHaveBeenCalledTimes(publishCountAtDispose);
      expect(mockStatusSurface.complete).toHaveBeenCalledTimes(completeCountAtDispose);
      expect(mockRpc.stopSyncthingActivityWatch).toHaveBeenCalled();
      expect(mockRpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    });
  });
});
