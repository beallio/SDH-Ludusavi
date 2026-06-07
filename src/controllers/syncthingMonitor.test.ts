import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SyncthingMonitor, type SyncthingRpc } from "./syncthingMonitor";
import type { RpcResult, SyncthingWatchStartResult } from "../types";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

describe("SyncthingMonitor", () => {
  let mockRpc: {
    startWatch: any;
    pollWatch: any;
    stopWatch: any;
  };
  let mockOnStatus: any;
  let monitor: SyncthingMonitor;

  beforeEach(() => {
    vi.useFakeTimers();
    // Stub globalThis.window to delegate to globalThis timers in Node environment
    globalThis.window = globalThis as any;
    mockRpc = {
      startWatch: vi.fn(),
      pollWatch: vi.fn().mockResolvedValue({ status: "activity", watch_id: "w1", sample: null }),
      stopWatch: vi.fn().mockResolvedValue({ status: "stopped", watch_id: "w1" }),
    };
    mockOnStatus = vi.fn();
    monitor = new SyncthingMonitor(mockRpc as unknown as SyncthingRpc, mockOnStatus);
  });

  afterEach(() => {
    monitor.dispose();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("start() synchronously returns a generation handle without confirming readiness", async () => {
    let resolveStart: any;
    const startPromise = new Promise<RpcResult<SyncthingWatchStartResult>>((resolve) => {
      resolveStart = resolve;
    });
    mockRpc.startWatch.mockReturnValue(startPromise);

    const handle = monitor.start("post_game", "Hades", "1145300");
    expect(handle).toBeDefined();
    expect(handle.generation).toBe(1);
    expect(handle.phase).toBe("post_game");
    expect(handle.gameName).toBe("Hades");
    expect(handle.appID).toBe("1145300");

    // The backend hasn't resolved watch ID yet, so monitor shouldn't be ready
    void monitor.activatePostGameHandoff(handle.generation, 750, 8000);
    
    // Resolve start watch RPC
    resolveStart({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    await vi.runAllTimersAsync();
  });

  it("empty samples do not confirm initialization", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    // Returns status: activity, but sample is empty or missing
    mockRpc.pollWatch.mockResolvedValue({ status: "activity", watch_id: "w1", sample: null });

    const handle = monitor.start("post_game", "Hades", "1145300");
    
    // Start confirmation with 750ms timeout
    const handoffPromise = monitor.activatePostGameHandoff(handle.generation, 750, 8000);

    // Run timers to allow polling
    await vi.advanceTimersByTimeAsync(250);
    
    // Handoff should still be pending (not resolved yet)
    let resolved = false;
    handoffPromise.then(() => { resolved = true; });
    await Promise.resolve(); // flush microtasks
    expect(resolved).toBe(false);
  });

  it("first post-cursor valid finite-timestamp sample confirms readiness", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    
    // First return empty, then a valid sample
    mockRpc.pollWatch
      .mockResolvedValueOnce({ status: "activity", watch_id: "w1", sample: null })
      .mockResolvedValueOnce({
        status: "activity",
        watch_id: "w1",
        sample: {
          status: "idle",
          folder_id: "f1",
          label: "Folder",
          folder_state: "idle",
          active_transfer: false,
          update_in_progress: false,
          settled: true,
          downloading: false,
          uploading: false,
          receive_needed: false,
          need_bytes: 0,
          need_items: 0,
          need_deletes: 0,
          sequence: 1,
          pending_remote_ack: false,
          lagging_remote_devices: 0,
          timestamp_unix: 1234567890,
        }
      });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffPromise = monitor.activatePostGameHandoff(handle.generation, 750, 8000);

    // Fast-forward timers for polling
    await vi.advanceTimersByTimeAsync(250); // first poll (empty)
    await vi.advanceTimersByTimeAsync(250); // second poll (valid sample)

    const handoffResult = await handoffPromise;
    expect(handoffResult.status).toBe("pending");
    expect(handoffResult.generation).toBe(handle.generation);
  });

  it("initialization failure resolves handoff unavailable", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "failed", reason: "watch_initialization_failed", message: "failed cursor" });
    
    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffResult = await monitor.activatePostGameHandoff(handle.generation, 750, 8000);

    expect(handoffResult.status).toBe("unavailable");
    if (handoffResult.status === "unavailable") {
      expect(handoffResult.reason).toBe("initialization_failed");
    }
  });

  it("post-game upload before activation is buffered and not published", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    mockRpc.pollWatch.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: {
        status: "idle",
        folder_id: "f1",
        folder_state: "syncing",
        active_transfer: true,
        update_in_progress: false,
        settled: false,
        downloading: false,
        uploading: true,
        sequence: 1,
        timestamp_unix: 1234567890,
      }
    });

    monitor.start("post_game", "Hades", "1145300");
    
    // Run timer to poll and process uploading sample
    await vi.advanceTimersByTimeAsync(100);

    // Status callback should NOT be called because handoff is not activated yet
    expect(mockOnStatus).not.toHaveBeenCalled();
  });

  it("activation after buffered upload returns uploading, never pending", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    mockRpc.pollWatch.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: {
        status: "idle",
        folder_id: "f1",
        folder_state: "syncing",
        active_transfer: true,
        update_in_progress: false,
        settled: false,
        downloading: false,
        uploading: true,
        sequence: 1,
        timestamp_unix: 1234567890,
      }
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    await vi.advanceTimersByTimeAsync(100);

    const handoffResult = await monitor.activatePostGameHandoff(handle.generation, 750, 8000);
    expect(handoffResult.status).toBe("uploading");
    
    // Status callback should still not be called by the activation process itself (the controller will do the initial print synchronously)
    expect(mockOnStatus).not.toHaveBeenCalled();
  });

  it("buffered completion returns complete", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    
    // Return uploading sample first, then 3 distinct settled samples
    let pollCount = 0;
    mockRpc.pollWatch.mockImplementation(() => {
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
          sample: { status: "idle", uploading: false, settled: true, timestamp_unix: 1000 + pollCount }
        });
      }
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    // Run enough polls to complete the watch (1 upload + 3 settled)
    await vi.advanceTimersByTimeAsync(2000);

    const handoffResult = await monitor.activatePostGameHandoff(handle.generation, 750, 8000);
    expect(handoffResult.status).toBe("complete");
    expect(mockOnStatus).not.toHaveBeenCalled();
  });

  it("activated upload publishes subsequent status callbacks", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    
    let pollCount = 0;
    mockRpc.pollWatch.mockImplementation(() => {
      pollCount++;
      if (pollCount === 1) {
        return Promise.resolve({
          status: "activity",
          watch_id: "w1",
          sample: { status: "idle", timestamp_unix: 1000 }
        });
      } else {
        return Promise.resolve({
          status: "activity",
          watch_id: "w1",
          sample: { status: "syncing", uploading: true, timestamp_unix: 1000 + pollCount }
        });
      }
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffResult = await monitor.activatePostGameHandoff(handle.generation, 750, 8000);
    expect(handoffResult.status).toBe("pending");

    // Advance timer for the second poll (with uploading activity)
    await vi.advanceTimersByTimeAsync(500);
    
    expect(mockOnStatus).toHaveBeenCalledWith("syncthing_uploading", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
    });
  });

  it("confirmation timeout cancels and stops a known watch", async () => {
    let resolveStart: any;
    const startPromise = new Promise<RpcResult<SyncthingWatchStartResult>>((resolve) => {
      resolveStart = resolve;
    });
    mockRpc.startWatch.mockReturnValue(startPromise);

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffPromise = monitor.activatePostGameHandoff(handle.generation, 750, 8000);

    // Resolve watch start RPC so it's a known watch
    resolveStart({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    await Promise.resolve(); // flush microtasks

    // Advance past the 750ms confirmation timeout
    await vi.advanceTimersByTimeAsync(800);

    const result = await handoffPromise;
    expect(result.status).toBe("unavailable");
    if (result.status === "unavailable") {
      expect(result.reason).toBe("confirmation_timeout");
    }

    // Should stop the known watch immediately
    expect(mockRpc.stopWatch).toHaveBeenCalledWith("w1");
  });

  it("late allocation after timeout is stopped and cannot publish", async () => {
    let resolveStart: any;
    const startPromise = new Promise<RpcResult<SyncthingWatchStartResult>>((resolve) => {
      resolveStart = resolve;
    });
    mockRpc.startWatch.mockReturnValue(startPromise);

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffPromise = monitor.activatePostGameHandoff(handle.generation, 750, 8000);

    // Advance past 750ms confirmation timeout before start resolves
    await vi.advanceTimersByTimeAsync(800);
    const result = await handoffPromise;
    expect(result.status).toBe("unavailable");

    // Resolve the start watch RPC late
    resolveStart({ status: "watching", watch_id: "late-watch", folder_id: "f1", label: "Folder", path: "/path" });
    await vi.runAllTimersAsync();

    // Late allocation must be stopped
    expect(mockRpc.stopWatch).toHaveBeenCalledWith("late-watch");
  });

  it("superseding generation invalidates the earlier generation", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });

    const handle1 = monitor.start("post_game", "Hades", "1145300");
    
    // Start second generation
    const handle2 = monitor.start("post_game", "Hades", "1145300");
    expect(handle2.generation).toBeGreaterThan(handle1.generation);

    // First handoff should resolve stale
    const handoffResult1 = await monitor.activatePostGameHandoff(handle1.generation, 750, 8000);
    expect(handoffResult1.status).toBe("stale");
  });

  it("cancellation is idempotent", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    const handle = monitor.start("post_game", "Hades", "1145300");

    await monitor.cancelGeneration(handle.generation, "manual");
    expect(mockRpc.stopWatch).toHaveBeenCalledTimes(1);

    // Call it again
    await monitor.cancelGeneration(handle.generation, "manual again");
    expect(mockRpc.stopWatch).toHaveBeenCalledTimes(1);
  });

  it("activated failure before activity publishes one has_backup", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    // First sample is valid (ready), second sample fails
    mockRpc.pollWatch
      .mockResolvedValueOnce({
        status: "activity",
        watch_id: "w1",
        sample: { status: "idle", timestamp_unix: 1000 }
      })
      .mockResolvedValueOnce({
        status: "failed",
        reason: "connection_lost",
        message: "lost"
      });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffResult = await monitor.activatePostGameHandoff(handle.generation, 750, 8000);
    expect(handoffResult.status).toBe("pending");

    // Advance timer for the second failing poll
    await vi.advanceTimersByTimeAsync(500);

    // Should publish has_backup on poll failure
    expect(mockOnStatus).toHaveBeenCalledWith("has_backup", {
      source: "rpc_result",
      gameName: "Hades",
      appID: "1145300",
    });
  });

  it("activated failure after activity publishes no replacement state or completion", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    // Valid ready, uploading activity, then failed poll
    mockRpc.pollWatch
      .mockResolvedValueOnce({
        status: "activity",
        watch_id: "w1",
        sample: { status: "idle", timestamp_unix: 1000 }
      })
      .mockResolvedValueOnce({
        status: "activity",
        watch_id: "w1",
        sample: { status: "syncing", uploading: true, timestamp_unix: 1001 }
      })
      .mockResolvedValueOnce({
        status: "failed",
        reason: "connection_lost",
        message: "lost"
      });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffResult = await monitor.activatePostGameHandoff(handle.generation, 750, 8000);
    expect(handoffResult.status).toBe("pending");

    // Run first poll (ready but idle) and second poll (activity observed)
    await vi.advanceTimersByTimeAsync(500);
    expect(mockOnStatus).toHaveBeenCalledWith("syncthing_uploading", expect.any(Object));
    mockOnStatus.mockClear();

    // Run third poll (fails)
    await vi.advanceTimersByTimeAsync(500);

    // Should NOT publish has_backup, syncthing_complete, or anything else
    expect(mockOnStatus).not.toHaveBeenCalled();
  });

  it("pre-game watch failure before activity does not publish has_backup", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    mockRpc.pollWatch
      .mockResolvedValueOnce({
        status: "activity",
        watch_id: "w1",
        sample: { status: "idle", timestamp_unix: 1000 }
      })
      .mockResolvedValueOnce({
        status: "failed",
        reason: "connection_lost",
        message: "lost"
      });

    monitor.start("pre_game", "Hades", "1145300");

    // Advance timer to trigger polling
    await vi.advanceTimersByTimeAsync(500); // first poll (ready)
    await vi.advanceTimersByTimeAsync(500); // second poll (failing)

    // Should NOT publish has_backup
    expect(mockOnStatus).not.toHaveBeenCalled();
  });
});

