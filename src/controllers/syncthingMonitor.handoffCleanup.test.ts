import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SyncthingMonitor } from "./syncthingMonitor";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

describe("SyncthingMonitor", () => {
  let monitor: SyncthingMonitor;
  let mockRpc: any;

  beforeEach(() => {
    vi.useFakeTimers();
    globalThis.window = globalThis as any;
    
    mockRpc = {
      startWatch: vi.fn(),
      pollWatch: vi.fn(),
      cancelWatch: vi.fn(),
      stopWatch: vi.fn(),
    };
    
    monitor = new SyncthingMonitor(mockRpc, vi.fn());
  });

  afterEach(() => {
    monitor.dispose();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe("handoffCleanup", () => {
    it("cleans up context on confirmation timeout", async () => {
      mockRpc.startWatch.mockResolvedValue({ status: "watching", watch_id: "w1", detection_grace_ms: 1000 });
      mockRpc.pollWatch.mockResolvedValue({ status: "activity", sample: null });

      const handle = monitor.start("post_game", "Game", "1");
      const resultP = handle.activatePostGameHandoff(500);

      await vi.advanceTimersByTimeAsync(600);

      const result = await resultP;

      expect(result).toEqual({ status: "unavailable", reason: "confirmation_timeout" });
      expect(((monitor as any).contexts as Map<number, unknown>).size).toBe(0);
    });
  });
});
