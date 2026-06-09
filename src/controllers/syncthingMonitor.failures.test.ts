import { describe, it, expect, vi, beforeEach } from "vitest";
import { SyncthingMonitor, type SyncthingRpc } from "./syncthingMonitor";

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
  it("initialization failure resolves handoff unavailable", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "failed", reason: "watch_initialization_failed", message: "failed cursor" });
    
    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffResult = await handle.activatePostGameHandoff(750);

    expect(handoffResult.status).toBe("unavailable");
    if (handoffResult.status === "unavailable") {
      expect(handoffResult.reason).toBe("initialization_failed");
    }
  });

  it("activated failure before activity publishes Syncthing unavailable", async () => {
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
    const handoffResult = await handle.activatePostGameHandoff(750);
    expect(handoffResult.status).toBe("pending");

    // Advance timer for the second failing poll
    await vi.advanceTimersByTimeAsync(500);

    expect(mockOnStatus).toHaveBeenCalledWith("syncthing_unavailable", {
      source: "rpc_result",
      gameName: "Hades",
      appID: "1145300",
    });
  });

  it("activated failure after activity publishes unavailable state", async () => {
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
    const handoffResult = await handle.activatePostGameHandoff(750);
    expect(handoffResult.status).toBe("pending");

    // Run first poll (ready but idle) and second poll (activity observed)
    await vi.advanceTimersByTimeAsync(500);
    expect(mockOnStatus).toHaveBeenCalledWith("syncthing_uploading", expect.any(Object));
    mockOnStatus.mockClear();

    // Run third poll (fails)
    await vi.advanceTimersByTimeAsync(500);

    expect(mockOnStatus).toHaveBeenCalledWith("syncthing_unavailable", {
      source: "rpc_result",
      gameName: "Hades",
      appID: "1145300",
    });
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

  it("terminated contexts are removed from the generation map", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    mockRpc.pollWatch.mockResolvedValue({
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
        timestamp_unix: 1234567890,
      }
    });

    const handle = monitor.start("pre_game", "Hades", "1145300");
    expect(monitor.getSnapshotForTest().generation).not.toBeNull();

    // Cancel the pre_game watch
    await handle.cancel("test-cancel");
    
    // The context should be deleted
    expect(monitor.getSnapshotForTest().generation).toBeNull();
  });

  it("post-game watch allocation failure (failed status) does not leak context", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "failed", reason: "watch_initialization_failed", message: "Failed to allocate watch" });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const contextsMap = (monitor as any).contexts;
    const generation = monitor.getSnapshotForTest().generation;
    expect(contextsMap.has(generation)).toBe(true);

    const handoffPromise = handle.activatePostGameHandoff(750);

    // Let background watch allocation run
    await vi.advanceTimersByTimeAsync(0);

    const handoffResult = await handoffPromise;
    expect(handoffResult.status).toBe("unavailable");
    if (handoffResult.status === "unavailable") {
      expect(handoffResult.reason).toBe("initialization_failed");
    }

    expect(contextsMap.has(generation)).toBe(false);
  });

  it("post-game watch allocation failure (rejection) does not leak context", async () => {
    mockRpc.startWatch.mockRejectedValue(new Error("RPC failed"));

    const handle = monitor.start("post_game", "Hades", "1145300");
    const contextsMap = (monitor as any).contexts;
    const generation = monitor.getSnapshotForTest().generation;
    expect(contextsMap.has(generation)).toBe(true);

    const handoffPromise = handle.activatePostGameHandoff(750);

    // Let background watch allocation run
    await vi.advanceTimersByTimeAsync(0);

    const handoffResult = await handoffPromise;
    expect(handoffResult.status).toBe("unavailable");
    if (handoffResult.status === "unavailable") {
      expect(handoffResult.reason).toBe("initialization_failed");
    }

    expect(contextsMap.has(generation)).toBe(false);
  });

  it("polling failure before handoff activation does not leak context", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    mockRpc.pollWatch.mockResolvedValue({ status: "error", reason: "error", message: "polling failed" });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const contextsMap = (monitor as any).contexts;
    const generation = monitor.getSnapshotForTest().generation;
    expect(contextsMap.has(generation)).toBe(true);

    // Run timers so watch allocation runs and performs the first poll
    await vi.advanceTimersByTimeAsync(250);

    expect((monitor as any).contexts.get(generation).cancelled).toBe(true);

    const handoffResult = await handle.activatePostGameHandoff(750);
    expect(handoffResult.status).toBe("unavailable");

    expect(contextsMap.has(generation)).toBe(false);
  });
});
