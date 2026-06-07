import { describe, it, expect, vi } from "vitest";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {},
}));

describe("AutoSyncStatusSurface Smoke Test", () => {
  it("dummy test to exist", () => {
    expect(true).toBe(true);
  });
});
