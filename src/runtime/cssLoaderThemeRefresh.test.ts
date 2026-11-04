import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetCssLoaderThemes, startCssLoaderThemeRefresh } from "./cssLoaderThemeRefresh";

const calls: unknown[][] = [];
let pluginCall: (...args: unknown[]) => Promise<unknown> = async () => ({ fails: [] });

// Node has no window; the plugin reads only window.DeckyBackend.callable.
Object.assign(globalThis, {
  window: {
    DeckyBackend: {
      callable: (route: string) => async (...args: unknown[]) => {
        calls.push([route, ...args]);
        return pluginCall(...args);
      },
    },
  },
});

beforeEach(() => {
  calls.length = 0;
  pluginCall = async () => ({ fails: [] });
});

describe("resetCssLoaderThemes", () => {
  it("reloads themes through the modern plugin route that native backends accept", async () => {
    await expect(resetCssLoaderThemes()).resolves.toBe(true);
    expect(calls).toEqual([["loader/call_plugin_method", "CSS Loader", "reset"]]);
  });

  it("surfaces a rejected reload so the caller can warn", async () => {
    pluginCall = async () => {
      throw new Error("CSS Loader is not loaded");
    };

    await expect(resetCssLoaderThemes()).rejects.toThrow("CSS Loader is not loaded");
  });

  it("reports failure when CSS Loader could not load the status theme", async () => {
    pluginCall = async () => ({ fails: [["SDH-Ludusavi Status", "invalid theme.json"]] });

    await expect(resetCssLoaderThemes()).resolves.toBe(false);
  });

  it("ignores load failures of other users' themes", async () => {
    pluginCall = async () => ({ fails: [["Broken Theme", "invalid theme.json"]] });

    await expect(resetCssLoaderThemes()).resolves.toBe(true);
  });

  describe("stock CSS Loader (api_version 0)", () => {
    const api0 = new Error(
      "api_version 1 or newer is required to call methods with index-based arguments",
    );
    let legacyReply: unknown;

    beforeEach(() => {
      legacyReply = { success: true, result: { fails: [] } };
      pluginCall = async (...args: unknown[]) => {
        // The legacy route is the only one that passes a kwargs object.
        if (args.length === 3) return legacyReply;
        throw api0;
      };
    });

    it("retries once on the legacy route after the api_version rejection", async () => {
      await expect(resetCssLoaderThemes()).resolves.toBe(true);
      expect(calls).toEqual([
        ["loader/call_plugin_method", "CSS Loader", "reset"],
        ["loader/call_legacy_plugin_method", "CSS Loader", "reset", {}],
      ]);
    });

    it("reports failure when the legacy call fails", async () => {
      legacyReply = { success: false, result: "boom" };

      await expect(resetCssLoaderThemes()).resolves.toBe(false);
    });

    it("reports failure when the legacy reply lists the status theme", async () => {
      legacyReply = { success: true, result: { fails: [["SDH-Ludusavi Status", "bad"]] } };

      await expect(resetCssLoaderThemes()).resolves.toBe(false);
    });
  });

  it("never retries on the legacy route after any other rejection", async () => {
    for (const message of ["CSS Loader is not loaded", "reset raised inside the plugin"]) {
      calls.length = 0;
      pluginCall = async () => {
        throw new Error(message);
      };

      await expect(resetCssLoaderThemes()).rejects.toThrow(message);
      expect(calls).toEqual([["loader/call_plugin_method", "CSS Loader", "reset"]]);
    }
  });
});

describe("CSS Loader theme refresh", () => {
  it("resets once for changed theme files, not when a later startup changes nothing", async () => {
    const changes = [true, false];
    const resetThemes = vi.fn(async () => true);
    const deps = {
      consumeChange: async () => changes.shift() ?? false,
      resetThemes,
      warn: vi.fn(),
    };

    await startCssLoaderThemeRefresh(deps).ready;
    await startCssLoaderThemeRefresh(deps).ready;

    expect(resetThemes).toHaveBeenCalledTimes(1);
    expect(deps.warn).not.toHaveBeenCalled();
  });

  it("does not reset themes when Decky dismounts the plugin before installation finishes", async () => {
    const { promise, resolve } = Promise.withResolvers<boolean>();
    const resetThemes = vi.fn(async () => true);
    const refresh = startCssLoaderThemeRefresh({
      consumeChange: () => promise,
      resetThemes,
      warn: vi.fn(),
    });

    refresh.dispose();
    resolve(true);
    await refresh.ready;

    expect(resetThemes).not.toHaveBeenCalled();
  });

  it("keeps plugin startup usable when CSS Loader is unavailable", async () => {
    const resetThemes = vi.fn(async () => { throw new Error("CSS Loader unavailable"); });
    const warn = vi.fn();
    const refresh = startCssLoaderThemeRefresh({
      consumeChange: async () => true,
      resetThemes,
      warn,
    });

    await refresh.ready;

    expect(resetThemes).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledTimes(1);
  });
});
