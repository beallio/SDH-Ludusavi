import { useEffect, useRef } from "react";
import type { GameStatus } from "../../types";
import {
  findGameForRunningSession,
  getPreferredSteamGameSession,
  logCurrentGameNoMatch,
  logCurrentGameSelection,
  resetQuickAccessScroll
} from "../../utils/steam";
import { logUiEvent } from "../../utils/logging";

export function selectCurrentSteamGameIfAvailable(
  currentGames: readonly GameStatus[],
  currentAliases: Record<string, string>,
  setDisplayedGame: (gameName: string) => void
): boolean {
  const runningSession = getPreferredSteamGameSession();
  if (!runningSession) {
    logCurrentGameNoMatch(null, currentGames, currentAliases);
    return false;
  }

  const runningGame = findGameForRunningSession(currentGames, runningSession, currentAliases);
  if (!runningGame) {
    logCurrentGameNoMatch(runningSession, currentGames, currentAliases);
    return false;
  }

  setDisplayedGame(runningGame.game.name);
  logCurrentGameSelection(
    runningSession,
    runningGame.game,
    runningGame.reason,
    currentGames,
    currentAliases
  );
  return true;
}

export type UseSteamContextOptions = {
  isQuickAccessVisible: boolean;
  games: readonly GameStatus[];
  gameAliases: Record<string, string>;
  selectedGame: string | null;
  settingsLoaded: boolean;
  operationInProgress: boolean;
  qamContentRef: React.RefObject<HTMLDivElement | null>;
  setDisplayedGame: (gameName: string) => void;
  resolveQamOpenSelection: (args: any) => "wait" | "consume" | "select";
  isExplicitSelectionPending: () => boolean;
  onExplicitSelectionConsumed: () => void;
};

export function useSteamContext({
  isQuickAccessVisible,
  games,
  gameAliases,
  selectedGame,
  settingsLoaded,
  operationInProgress,
  qamContentRef,
  setDisplayedGame,
  resolveQamOpenSelection,
  isExplicitSelectionPending,
  onExplicitSelectionConsumed
}: UseSteamContextOptions) {
  const wasQuickAccessVisible = useRef(false);
  const pendingCurrentGameSelection = useRef(false);

  useEffect(() => {
    if (isQuickAccessVisible && !wasQuickAccessVisible.current) {
      logUiEvent(
        "qam_opened",
        {
          game_count: games.length,
          selected_game: selectedGame || null,
          settings_loaded: settingsLoaded,
        },
        "info",
      );
      pendingCurrentGameSelection.current = true;
      const resetDelays = [50, 150, 350];
      resetQuickAccessScroll(qamContentRef.current);
      resetDelays.forEach((delay) => {
        window.setTimeout(
          () => resetQuickAccessScroll(qamContentRef.current, `qam_open_retry_${delay}`),
          delay
        );
      });
    } else if (!isQuickAccessVisible && wasQuickAccessVisible.current) {
      logUiEvent("qam_closed", { selected_game: selectedGame || null }, "info");
    }
    wasQuickAccessVisible.current = isQuickAccessVisible;
  }, [isQuickAccessVisible, games.length, selectedGame, settingsLoaded, qamContentRef]);

  useEffect(() => {
    const explicitSelectionPending = isExplicitSelectionPending();
    const action = resolveQamOpenSelection({
      isQuickAccessVisible,
      pendingSelection: pendingCurrentGameSelection.current,
      gameCount: games.length,
      operationInProgress,
      explicitSelectionPending,
    });
    if (action === "wait") {
      return;
    }
    if (action === "consume") {
      pendingCurrentGameSelection.current = false;
      if (explicitSelectionPending) {
        onExplicitSelectionConsumed();
      }
      return;
    }
    selectCurrentSteamGameIfAvailable(games, gameAliases, setDisplayedGame);
    pendingCurrentGameSelection.current = false;
  }, [gameAliases, games, isQuickAccessVisible, operationInProgress, setDisplayedGame,
    resolveQamOpenSelection, isExplicitSelectionPending, onExplicitSelectionConsumed
  ]);
}
