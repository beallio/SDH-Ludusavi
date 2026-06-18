import { describe, it, expect, vi } from "vitest";
import { logCurrentGameNoMatch } from "./steam";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {}
}));

vi.mock("./logging", () => ({
  log: vi.fn(),
}));

import { log } from "./logging";
import { RunningSession } from "../types";

describe("logCurrentGameNoMatch", () => {
  it("logs at debug severity when session is present", () => {
    const session: RunningSession = { appID: "123", name: "Test Game", source: "focused" };
    logCurrentGameNoMatch(session, [], {});
    expect(log).toHaveBeenCalledWith(
      "debug",
      expect.stringContaining("QAM current game not selected: context="),
      "qam_context",
      "Test Game"
    );
  });

  it("logs at debug severity when session is null", () => {
    logCurrentGameNoMatch(null, [], {});
    expect(log).toHaveBeenCalledWith(
      "debug",
      expect.stringContaining("QAM current game not selected: context=none"),
      "qam_context",
      undefined
    );
  });
});
