import { describe, expect, it, vi } from "vitest";
import { startCssLoaderThemeRefresh } from "./cssLoaderThemeRefresh";

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
    let finishInstall!: (changed: boolean) => void;
    const change = new Promise<boolean>((resolve) => { finishInstall = resolve; });
    const resetThemes = vi.fn(async () => true);
    const refresh = startCssLoaderThemeRefresh({
      consumeChange: () => change,
      resetThemes,
      warn: vi.fn(),
    });

    refresh.dispose();
    finishInstall(true);
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
