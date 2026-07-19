import { vi, describe, it, expect } from "vitest";

vi.mock("@decky/ui", () => ({}));

vi.mock("react", () => ({
  useCallback: (fn: any) => fn,
  useState: (initial: any) => [initial, vi.fn()],
  useRef: (initial: any) => ({ current: initial }),
  useEffect: (fn: any) => { fn(); },
}));

vi.mock("../../utils/logging", () => ({
  log: vi.fn(),
  logUiEvent: vi.fn()
}));

vi.mock("../../utils/steam", () => ({
  getInstalledAppIdsString: vi.fn().mockResolvedValue("app1")
}));

import { useInitialContent } from "./useInitialContent";

const SETTINGS = {
  auto_sync_enabled: true,
  sync_disabled_games: [],
  selected_game: "B",
  notifications: {
    enabled: true,
    auto_sync_progress: true,
    auto_sync_results: true,
    manual_operations: true,
    refresh_status: true,
    failures_errors: true,
  },
  update_channel: "stable",
  automatic_update_checks: true,
  debug_logging: true,
};
const HISTORY = { B: { last_operation: null } };
const REFRESH = { games: [{ name: "A" }, { name: "B" }], aliases: {} };

function makeHarness(initialDisplayedGame = "", overrides: Record<string, unknown> = {}) {
  let displayedGame = initialDisplayedGame;
  let initPromise: Promise<unknown> | null = null;
  const deps = {
    isMounted: vi.fn().mockReturnValue(true),
    isWarmed: false,
    installedAppIds: "app1",
    cachedGames: [],
    initPromise: null,
    metadataPromise: null,
    setInitPromise: vi.fn((promise: Promise<unknown> | null) => {
      if (promise) initPromise = promise;
    }),
    setMetadataPromise: vi.fn(),
    getOperationStatus: vi.fn().mockResolvedValue({ is_running: false }),
    getVersions: vi.fn().mockResolvedValue({}),
    getLudusaviCommandCall: vi.fn().mockResolvedValue({}),
    getSettings: vi.fn().mockResolvedValue(SETTINGS),
    getGameHistoryCall: vi.fn().mockResolvedValue(HISTORY),
    isGameCacheCurrentCall: vi.fn().mockResolvedValue(false),
    refreshGamesCall: vi.fn().mockResolvedValue(REFRESH),
    applySettings: vi.fn(),
    hydrateDisplayedGame: vi.fn((gameName: string) => {
      if (displayedGame === "") displayedGame = gameName;
    }),
    setGameHistory: vi.fn(),
    setVersions: vi.fn(),
    setLudusaviCommand: vi.fn(),
    applyRefreshResult: vi.fn((result: typeof REFRESH, preferredGame?: string) => {
      const liveSelectionValid = result.games.some((game) => game.name === displayedGame);
      const target = liveSelectionValid ? displayedGame : preferredGame;
      displayedGame = result.games.some((game) => game.name === target)
        ? target ?? ""
        : result.games[0]?.name ?? "";
      return true;
    }),
    applyCachedRefreshResult: vi.fn(),
    setInstalledAppIds: vi.fn(),
    setOperation: vi.fn(),
    setBackgroundRefreshBusy: vi.fn(),
    setBusyLabel: vi.fn(),
    isRpcStatus: vi.fn((result: any) => typeof result?.status === "string"),
    logRpcStatus: vi.fn(),
    logError: vi.fn(),
    ...overrides,
  };

  useInitialContent(deps as any);
  return {
    deps,
    getDisplayedGame: () => displayedGame,
    waitForInit: async () => {
      expect(initPromise).not.toBeNull();
      await initPromise;
    },
  };
}

describe("useInitialContent", () => {
  it("hydrates settings and history before applying the game list", async () => {
    const harness = makeHarness();

    await harness.waitForInit();

    expect(harness.deps.applySettings).toHaveBeenCalledWith(SETTINGS);
    expect(harness.deps.hydrateDisplayedGame).toHaveBeenCalledWith("B");
    expect(harness.deps.setGameHistory).toHaveBeenCalledWith(HISTORY);
    expect(harness.deps.refreshGamesCall).toHaveBeenCalledTimes(1);
    expect(harness.getDisplayedGame()).toBe("B");
  });

  it("does not overwrite an existing displayed game during hydration", async () => {
    const harness = makeHarness("A");

    await harness.waitForInit();

    expect(harness.deps.hydrateDisplayedGame).toHaveBeenCalledWith("B");
    expect(harness.getDisplayedGame()).toBe("A");
  });

  it("still applies the game list when the settings request throws", async () => {
    const harness = makeHarness("", {
      getSettings: vi.fn().mockRejectedValue(new Error("settings failed")),
    });

    await harness.waitForInit();

    expect(harness.deps.applySettings).not.toHaveBeenCalled();
    expect(harness.deps.setGameHistory).toHaveBeenCalledWith(HISTORY);
    expect(harness.deps.applyRefreshResult).toHaveBeenCalledWith(REFRESH, undefined, true);
    expect(harness.getDisplayedGame()).toBe("A");
    expect(harness.deps.logError).toHaveBeenCalled();
    expect(harness.deps.logRpcStatus).toHaveBeenCalledWith(
      expect.objectContaining({ status: "failed" }),
      "settings",
    );
  });

  it("still applies settings and the game list when history throws", async () => {
    const harness = makeHarness("", {
      getGameHistoryCall: vi.fn().mockRejectedValue(new Error("history failed")),
    });

    await harness.waitForInit();

    expect(harness.deps.applySettings).toHaveBeenCalledWith(SETTINGS);
    expect(harness.deps.setGameHistory).not.toHaveBeenCalled();
    expect(harness.deps.refreshGamesCall).toHaveBeenCalledTimes(1);
    expect(harness.getDisplayedGame()).toBe("B");
    expect(harness.deps.logError).toHaveBeenCalled();
    expect(harness.deps.logRpcStatus).toHaveBeenCalledWith(
      expect.objectContaining({ status: "failed" }),
      "history",
    );
  });
});
