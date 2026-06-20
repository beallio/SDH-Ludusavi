import { vi, describe, it, expect } from "vitest";
import { useSteamContext, selectCurrentSteamGameIfAvailable } from "./useSteamContext";
import * as steamUtils from "../../utils/steam";

vi.mock("react", () => ({
  useCallback: (fn: any) => fn,
  useState: (initial: any) => [initial, vi.fn()],
  useRef: (initial: any) => ({ current: initial }),
  useEffect: (fn: any) => { fn(); },
}));

vi.mock("../../utils/steam", () => ({
  captureSteamUiGameContext: vi.fn(),
  findGameForRunningSession: vi.fn(),
  getPreferredSteamGameSession: vi.fn(),
  logCurrentGameNoMatch: vi.fn(),
  logCurrentGameSelection: vi.fn(),
  resetQuickAccessScroll: vi.fn(),
}));

vi.mock("../../utils/logging", () => ({
  log: vi.fn(),
  logUiEvent: vi.fn()
}));

describe("useSteamContext", () => {
  it("selectCurrentSteamGameIfAvailable does nothing if no session", () => {
    vi.mocked(steamUtils.getPreferredSteamGameSession).mockReturnValue(null);

    const setSelectedGame = vi.fn();
    const result = selectCurrentSteamGameIfAvailable([], {}, setSelectedGame);

    expect(result).toBe(false);
    expect(setSelectedGame).not.toHaveBeenCalled();
  });

  it("selectCurrentSteamGameIfAvailable selects game if found", () => {
    vi.mocked(steamUtils.getPreferredSteamGameSession).mockReturnValue({ appid: "123" } as any);
    vi.mocked(steamUtils.findGameForRunningSession).mockReturnValue({ game: { name: "Test" }, reason: "test" } as any);

    const setSelectedGame = vi.fn();
    const result = selectCurrentSteamGameIfAvailable([], {}, setSelectedGame);

    expect(result).toBe(true);
    expect(setSelectedGame).toHaveBeenCalledWith("Test");
  });

  it("mounts without errors", () => {
    const setSelectedGame = vi.fn();
    const resolveQamOpenSelection = vi.fn().mockReturnValue("wait");

    useSteamContext({
      isQuickAccessVisible: false,
      games: [],
      gameAliases: {},
      selectedGame: "Test",
      settingsLoaded: true,
      operationInProgress: false,
      qamContentRef: { current: null },
      setSelectedGame,
      resolveQamOpenSelection,
    });

    expect(setSelectedGame).not.toHaveBeenCalled();
  });
});

vi.mock("../../utils/logging", () => ({
  log: vi.fn(),
  logUiEvent: vi.fn()
}));
