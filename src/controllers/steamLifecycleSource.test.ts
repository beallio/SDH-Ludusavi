import { describe, it, expect, vi } from "vitest";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {
    RunningApps: []
  },
}));

import { createSteamLifecycleSource } from "./steamLifecycleSource";

describe("steamLifecycleSource", () => {
  it("can be created and disposed without errors", () => {
    const observer = {
      onAppStart: vi.fn(),
      onAppExit: vi.fn(),
    };
    const source = createSteamLifecycleSource(observer);
    expect(source.start).toBeDefined();
    expect(source.dispose).toBeDefined();
    
    // We mock SteamClient globally in other tests, but here we just ensure basic creation.
    source.dispose();
  });
});
