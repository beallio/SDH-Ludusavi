import { describe, it, expect, vi } from "vitest";
import { SyncthingMonitor } from "./syncthingMonitor";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

describe("SyncthingMonitor Smoke Test", () => {
  it("can be instantiated", () => {
    const mockRpc = {
      startWatch: vi.fn(),
      pollWatch: vi.fn(),
      stopWatch: vi.fn(),
    };
    const mockOnStatus = vi.fn();
    const monitor = new SyncthingMonitor(mockRpc, mockOnStatus);
    expect(monitor).toBeDefined();
  });
});
