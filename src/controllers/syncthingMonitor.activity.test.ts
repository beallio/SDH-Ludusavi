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

    const handoffResult = await handle.activatePostGameHandoff(750);
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

    const handoffResult = await handle.activatePostGameHandoff(750);
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
    const handoffResult = await handle.activatePostGameHandoff(750);
    expect(handoffResult.status).toBe("pending");

    // Advance timer for the second poll (with uploading activity)
    await vi.advanceTimersByTimeAsync(500);
    
    expect(mockOnStatus).toHaveBeenCalledWith("syncthing_uploading", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
    });
  });

  it("post-game download activity is ignored and does not confirm activity", async () => {
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
        downloading: true,
        uploading: false,
        sequence: 1,
        timestamp_unix: 1234567890,
      }
    });

    monitor.start("post_game", "Hades", "1145300");
    
    // Poll the watch once
    await vi.advanceTimersByTimeAsync(250);

    const snapshot = monitor.getSnapshotForTest();
    expect(snapshot.activityObserved).toBe(false);
  });

  it("post-game download does not set latestStatus to downloading", async () => {
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
        downloading: true,
        uploading: false,
        sequence: 1,
        timestamp_unix: 1234567890,
      }
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    await handle.activatePostGameHandoff(750);
    
    // Poll the watch once
    await vi.advanceTimersByTimeAsync(250);

    // Should not trigger syncthing_downloading status publication
    expect(mockOnStatus).not.toHaveBeenCalled();

    const snapshot = monitor.getSnapshotForTest();
    expect(snapshot.latestStatus).toBe("idle");
  });

  it("post-game download with update_in_progress: true, downloading: true does not set status to uploading", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    mockRpc.pollWatch.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: {
        status: "idle",
        folder_id: "f1",
        folder_state: "syncing",
        active_transfer: true,
        update_in_progress: true,
        settled: false,
        downloading: true,
        uploading: false,
        sequence: 1,
        timestamp_unix: 1234567890,
      }
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    await handle.activatePostGameHandoff(750);
    
    // Poll the watch once
    await vi.advanceTimersByTimeAsync(250);

    // Should not trigger status publication
    expect(mockOnStatus).not.toHaveBeenCalled();

    const snapshot = monitor.getSnapshotForTest();
    expect(snapshot.latestStatus).toBe("idle");
  });

  it("post-game local indexing remains pending without upload evidence", async () => {
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
        status: "INDEXING_OR_SEQUENCE_UPDATE",
        folder_id: "f1",
        folder_state: "scanning",
        active_transfer: false,
        update_in_progress: true,
        settled: false,
        downloading: false,
        uploading: false,
        sequence: 2,
        timestamp_unix: 1234567890,
      },
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffResult = await handle.activatePostGameHandoff(750);

    expect(handoffResult.status).toBe("pending");
    expect(monitor.getSnapshotForTest().activityObserved).toBe(false);
    expect(monitor.getSnapshotForTest().latestStatus).toBe("idle");
    expect(mockOnStatus).not.toHaveBeenCalledWith("syncthing_uploading", expect.anything());
  });

  it("keeps a passive post-game watch alive until the backup handoff", async () => {
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
        uploading: false,
        settled: true,
        timestamp_unix: 1000,
      },
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    await vi.advanceTimersByTimeAsync(121_000);

    const handoff = await handle.activatePostGameHandoff(750);

    expect(handoff.status).toBe("pending");
    expect(mockRpc.stopWatch).not.toHaveBeenCalled();
  });

  it.each(["not_configured", "api_unavailable", "folder_not_found"])(
    "preserves actionable watch allocation reason %s",
    async (reason) => {
      mockRpc.startWatch.mockResolvedValue({
        status: "skipped",
        reason,
        message: reason,
      });

      const handle = monitor.start("post_game", "Hades", "1145300");
      const handoffResult = await handle.activatePostGameHandoff(750);

      expect(handoffResult).toEqual({
        status: "unavailable",
        reason,
      });
    },
  );

  it("post-game upload with concurrent download confirms activity and publishes uploading", async () => {
    mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", folder_id: "f1", label: "Folder", path: "/path" });
    mockRpc.pollWatch.mockResolvedValue({
      status: "activity",
      watch_id: "w1",
      sample: {
        status: "idle",
        folder_id: "f1",
        folder_state: "syncing",
        active_transfer: true,
        update_in_progress: true,
        settled: false,
        downloading: true,
        uploading: true,
        sequence: 1,
        timestamp_unix: 1234567890,
      }
    });

    const handle = monitor.start("post_game", "Hades", "1145300");
    const handoffPromise = handle.activatePostGameHandoff(750);
    
    // Poll the watch once
    await vi.advanceTimersByTimeAsync(250);

    const snapshot = monitor.getSnapshotForTest();
    expect(snapshot.activityObserved).toBe(true);
    expect(snapshot.latestStatus).toBe("uploading");

    const handoffResult = await handoffPromise;
    expect(handoffResult.status).toBe("uploading");
  });
});
