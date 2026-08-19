import { afterEach, describe, it, expect, vi } from "vitest";
import {
  logCurrentGameNoMatch,
  startBoundedSteamUiGameContextCapture,
} from "./steam";

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

describe("startBoundedSteamUiGameContextCapture", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops scraping after ten samples during a minute hidden", () => {
    vi.useFakeTimers();
    const capture = vi.fn();

    const cancel = startBoundedSteamUiGameContextCapture(capture);

    expect(capture).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(4_500);
    expect(capture).toHaveBeenCalledTimes(10);

    vi.advanceTimersByTime(60_000);
    expect(capture).toHaveBeenCalledTimes(10);
    cancel();
  });

  it("cancels the remaining hidden-QAM capture burst", () => {
    vi.useFakeTimers();
    const capture = vi.fn();

    const cancel = startBoundedSteamUiGameContextCapture(capture);
    vi.advanceTimersByTime(500);
    expect(capture).toHaveBeenCalledTimes(2);

    cancel();
    vi.advanceTimersByTime(60_000);
    expect(capture).toHaveBeenCalledTimes(2);
  });
});
