import { beforeEach, describe, expect, it, vi } from "vitest";

const { backendLog } = vi.hoisted(() => ({
  backendLog: vi.fn(),
}));

vi.mock("@decky/api", () => ({
  callable: () => backendLog,
}));

import { log, logUiEvent } from "./logging";

describe("frontend logging", () => {
  beforeEach(() => {
    backendLog.mockReset();
    backendLog.mockResolvedValue(undefined);
    vi.spyOn(console, "debug").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("formats structured UI events deterministically and omits undefined fields", () => {
    logUiEvent(
      "qam_opened",
      { selected_game: "Hades", game_count: 12, warmed: true, ignored: undefined },
      "info",
      "ui",
    );

    expect(console.info).toHaveBeenCalledWith(
      "SDH-Ludusavi:ui: qam_opened: game_count=12 selected_game=\"Hades\" warmed=true",
    );
    expect(backendLog).toHaveBeenCalledWith(
      "info",
      "qam_opened: game_count=12 selected_game=\"Hades\" warmed=true",
      "ui",
      undefined,
    );
  });

  it("routes warning logs to the matching console method", () => {
    log("warning", "settings rollback", "ui_settings", "Hades");

    expect(console.warn).toHaveBeenCalledWith(
      "SDH-Ludusavi:ui_settings [Hades]: settings rollback",
    );
  });

  it("contains backend logging rejections in the browser console", async () => {
    backendLog.mockRejectedValueOnce(new Error("backend unavailable"));

    logUiEvent("plugin_mounted");
    await Promise.resolve();
    await Promise.resolve();

    expect(console.error).toHaveBeenCalledWith(
      "SDH-Ludusavi: logging RPC failed",
      expect.any(Error),
    );
  });
});
