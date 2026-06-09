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
  it("returns an opaque watch session", () => {
    const session = monitor.start("post_game", "Hades", "1145300");

    expect(session).toEqual(
      expect.objectContaining({
        cancel: expect.any(Function),
        activatePostGameHandoff: expect.any(Function),
      }),
    );
    expect(session).not.toHaveProperty("generation");
  });

  afterEach(() => {
    monitor.dispose();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("start() synchronously returns a session without confirming readiness", async () => {
    let resolveStart: any;
    const startPromise = new Promise<RpcResult<SyncthingWatchStartResult>>((resolve) => {
      resolveStart = resolve;
    });
    mockRpc.startWatch.mockReturnValue(startPromise);

    const handle = monitor.start("post_game", "Hades", "1145300");
    expect(handle).toBeDefined();
    expect(monitor.getSnapshotForTest().generation).toBe(1);
    expect(handle.phase).toBe("post_game");
    expect(handle.gameName).toBe("Hades");
    expect(handle.appID).toBe("1145300");

    // The backend hasn't resolved watch ID yet, so monitor shouldn't be ready
    void handle.activatePostGameHandoff(750);
    
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
    const handoffPromise = handle.activatePostGameHandoff(750);

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
    const handoffPromise = handle.activatePostGameHandoff(750);

    // Fast-forward timers for polling
    await vi.advanceTimersByTimeAsync(250); // first poll (empty)
    await vi.advanceTimersByTimeAsync(250); // second poll (valid sample)

    const handoffResult = await handoffPromise;
    expect(handoffResult.status).toBe("pending");
  });

  it("confirmation timeout cancels and stops a known watch", async () => {
    let resolveStart: any;
    const startPromise = new Promise<RpcResult<SyncthingWatchStartResult>>((resolve) => {
      resolveStart = resolve;
    });
    mockRpc.startWatch.mockReturnValue(startPromise);

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffPromise = handle.activatePostGameHandoff(750);

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
    const handoffPromise = handle.activatePostGameHandoff(750);

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
    const generation1 = monitor.getSnapshotForTest().generation;
    
    // Start second generation
    monitor.start("post_game", "Hades", "1145300");
    const generation2 = monitor.getSnapshotForTest().generation;
    expect(generation2).not.toBeNull();
    expect(generation2).toBeGreaterThan(generation1 ?? 0);

    // First handoff should resolve stale
    const handoffResult1 = await handle1.activatePostGameHandoff(750);
    expect(handoffResult1.status).toBe("stale");
  });

  it("cancellation is idempotent", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    const handle = monitor.start("post_game", "Hades", "1145300");

    await handle.cancel("manual");
    expect(mockRpc.stopWatch).toHaveBeenCalledTimes(1);

    // Call it again
    await handle.cancel("manual again");
    expect(mockRpc.stopWatch).toHaveBeenCalledTimes(1);
  });

  it("post-game watch uses backend detection grace instead of the legacy eight seconds", async () => {
    mockRpc.startWatch.mockResolvedValue({
      status: "watching",
      watch_id: "w1",
      folder_id: "f1",
      label: "Folder",
      path: "/path",
      detection_grace_ms: 30_000,
    });
    mockRpc.pollWatch.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: {
        status: "idle",
        folder_id: "f1",
        folder_state: "idle",
        active_transfer: false,
        update_in_progress: false,
        settled: true,
        downloading: false,
        uploading: false,
        sequence: 1,
        timestamp_unix: 1234567890,
      }
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const generation = monitor.getSnapshotForTest().generation;
    const handoffResult = await handle.activatePostGameHandoff(750);
    expect(handoffResult.status).toBe("pending");

    // Initially context is present
    expect(monitor.getSnapshotForTest().generation).toBe(generation);

    await vi.advanceTimersByTimeAsync(10_500);
    expect(monitor.getSnapshotForTest().generation).toBe(generation);

    await vi.advanceTimersByTimeAsync(20_000);
    expect(monitor.getSnapshotForTest().generation).toBeNull();
  });

  it("initialization requires a valid folder_state (not unknown)", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    
    // First poll returns unknown folder_state
    // Second poll returns syncing folder_state
    mockRpc.pollWatch
      .mockResolvedValueOnce({
        status: "activity",
        watch_id: "w1",
        sample: {
          status: "idle",
          folder_id: "f1",
          folder_state: "unknown",
          active_transfer: false,
          update_in_progress: false,
          settled: true,
          downloading: false,
          uploading: false,
          sequence: 1,
          timestamp_unix: 1234567890,
        }
      })
      .mockResolvedValueOnce({
        status: "activity",
        watch_id: "w1",
        sample: {
          status: "idle",
          folder_id: "f1",
          folder_state: "syncing",
          active_transfer: false,
          update_in_progress: false,
          settled: true,
          downloading: false,
          uploading: false,
          sequence: 1,
          timestamp_unix: 1234567891,
        }
      });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffPromise = handle.activatePostGameHandoff(750);

    // Watch should NOT be initialized yet (first poll returned unknown synchronously)
    expect(monitor.getSnapshotForTest().initialized).toBe(false);

    // Second poll runs on next 250ms (returns syncing)
    await vi.advanceTimersByTimeAsync(250);

    // Watch should be initialized now
    expect(monitor.getSnapshotForTest().initialized).toBe(true);

    const handoffResult = await handoffPromise;
    expect(handoffResult.status).toBe("pending");
  });
});
