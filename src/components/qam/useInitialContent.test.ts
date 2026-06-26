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

describe("useInitialContent", () => {
  it("mounts and initiates data fetch", () => {
    const deps = {
      isMounted: vi.fn().mockReturnValue(true),
      isWarmed: false,
      installedAppIds: "app1",
      cachedGames: [],
      initPromise: null,
      metadataPromise: null,
      setInitPromise: vi.fn(),
      setMetadataPromise: vi.fn(),
      getOperationStatus: vi.fn().mockResolvedValue({}),
      getVersions: vi.fn().mockResolvedValue({}),
      getLudusaviCommandCall: vi.fn().mockResolvedValue({}),
      getSettings: vi.fn().mockResolvedValue({}),
      getGameHistoryCall: vi.fn().mockResolvedValue({}),
      isGameCacheCurrentCall: vi.fn().mockResolvedValue(true),
      refreshGamesCall: vi.fn().mockResolvedValue({}),
      applySettings: vi.fn(),
      setGameHistory: vi.fn(),
      setVersions: vi.fn(),
      setLudusaviCommand: vi.fn(),
      applyRefreshResult: vi.fn(),
      applyCachedRefreshResult: vi.fn(),
      setInstalledAppIds: vi.fn(),
      setOperation: vi.fn(),
      setBackgroundRefreshBusy: vi.fn(),
      setBusyLabel: vi.fn(),
      isRpcStatus: vi.fn().mockReturnValue(false),
      logRpcStatus: vi.fn(),
    };

    useInitialContent(deps as any);

    expect(deps.setBusyLabel).toHaveBeenCalledWith("Loading");
    expect(deps.setInitPromise).toHaveBeenCalled();
    expect(deps.setMetadataPromise).toHaveBeenCalled();
  });

  it("refreshes the game list exactly once per load (no concurrent refresh)", async () => {
    const initPromises: Array<Promise<unknown>> = [];
    const deps = {
      isMounted: vi.fn().mockReturnValue(true),
      isWarmed: false,
      installedAppIds: "app1",
      cachedGames: [],
      initPromise: null,
      metadataPromise: null,
      setInitPromise: vi.fn((p: Promise<unknown> | null) => {
        if (p) initPromises.push(p);
      }),
      setMetadataPromise: vi.fn(),
      getOperationStatus: vi.fn().mockResolvedValue({}),
      getVersions: vi.fn().mockResolvedValue({}),
      getLudusaviCommandCall: vi.fn().mockResolvedValue({}),
      getSettings: vi.fn().mockResolvedValue({}),
      getGameHistoryCall: vi.fn().mockResolvedValue({}),
      isGameCacheCurrentCall: vi.fn().mockResolvedValue(false),
      refreshGamesCall: vi.fn().mockResolvedValue({ games: [], aliases: {} }),
      applySettings: vi.fn(),
      setGameHistory: vi.fn(),
      setVersions: vi.fn(),
      setLudusaviCommand: vi.fn(),
      applyRefreshResult: vi.fn().mockReturnValue(true),
      applyCachedRefreshResult: vi.fn(),
      setInstalledAppIds: vi.fn(),
      setOperation: vi.fn(),
      setBackgroundRefreshBusy: vi.fn(),
      setBusyLabel: vi.fn(),
      isRpcStatus: vi.fn().mockReturnValue(false),
      logRpcStatus: vi.fn(),
    };

    useInitialContent(deps as any);

    await Promise.allSettled(initPromises);

    expect(deps.refreshGamesCall).toHaveBeenCalledTimes(1);
  });
});
