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
