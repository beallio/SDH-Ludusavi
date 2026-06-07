import { describe, it, expect, vi } from "vitest";
import { createGameLifecycleController } from "./gameLifecycleController";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {},
}));

describe("GameLifecycleController Smoke Test", () => {
  it("can be created", () => {
    const mockStore = {} as any;
    const mockRpc = {} as any;
    const mockStatusSurface = {} as any;
    const mockResolveConflict = vi.fn();
    const mockNotifyFailure = vi.fn();
    const mockSyncGlobalHistory = vi.fn();

    const controller = createGameLifecycleController({
      store: mockStore,
      rpc: mockRpc,
      statusSurface: mockStatusSurface,
      resolveConflict: mockResolveConflict,
      notifyFailure: mockNotifyFailure,
      syncGlobalHistory: mockSyncGlobalHistory,
    });
    expect(controller).toBeDefined();
  });
});
