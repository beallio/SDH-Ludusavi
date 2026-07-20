import { vi, describe, it, expect } from "vitest";
import { useSteamContext, selectCurrentSteamGameIfAvailable } from "./useSteamContext";
import { resolveQamOpenSelection } from "./qamOpenSelection";
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

    const setDisplayedGame = vi.fn();
    const result = selectCurrentSteamGameIfAvailable([], {}, setDisplayedGame);

    expect(result).toBe(false);
    expect(setDisplayedGame).not.toHaveBeenCalled();
  });

  it("selectCurrentSteamGameIfAvailable selects game if found", () => {
    vi.mocked(steamUtils.getPreferredSteamGameSession).mockReturnValue({ appid: "123" } as any);
    vi.mocked(steamUtils.findGameForRunningSession).mockReturnValue({ game: { name: "Test" }, reason: "test" } as any);

    const setDisplayedGame = vi.fn();
    const result = selectCurrentSteamGameIfAvailable([], {}, setDisplayedGame);

    expect(result).toBe(true);
    expect(setDisplayedGame).toHaveBeenCalledWith("Test");
  });

  it("mounts without errors", () => {
    const setDisplayedGame = vi.fn();
    const resolveQamOpenSelection = vi.fn().mockReturnValue("wait");

    useSteamContext({
      isQuickAccessVisible: false,
      games: [],
      gameAliases: {},
      selectedGame: "Test",
      settingsLoaded: true,
      operationInProgress: false,
      qamContentRef: { current: null },
      setDisplayedGame,
      resolveQamOpenSelection,
      explicitSelectionPending: false,
      onExplicitSelectionConsumed: vi.fn(),
    });

    expect(setDisplayedGame).not.toHaveBeenCalled();
  });

  it("consumes an explicit selection once without selecting the running game", () => {
    vi.stubGlobal("window", { setTimeout: vi.fn() });
    const setDisplayedGame = vi.fn();
    const onExplicitSelectionConsumed = vi.fn();

    try {
      useSteamContext({
        isQuickAccessVisible: true,
        games: [{ name: "Test" } as any],
        gameAliases: {},
        selectedGame: "Test",
        settingsLoaded: true,
        operationInProgress: false,
        qamContentRef: { current: null },
        setDisplayedGame,
        resolveQamOpenSelection,
        explicitSelectionPending: true,
        onExplicitSelectionConsumed,
      });

      expect(setDisplayedGame).not.toHaveBeenCalled();
      expect(onExplicitSelectionConsumed).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

vi.mock("../../utils/logging", () => ({
  log: vi.fn(),
  logUiEvent: vi.fn()
}));
