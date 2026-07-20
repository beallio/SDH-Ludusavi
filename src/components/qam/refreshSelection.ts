export interface RefreshSelectionInput {
  games: readonly { name: string }[];
  preferredGame?: string;
  currentSelectedGame: string;
}
export interface RefreshSelectionOutcome {
  game: string;
  source: "preferred" | "first" | "none";
}
export interface AppliedSelectionInput
  extends Omit<RefreshSelectionInput, "currentSelectedGame"> {
  liveSelection: string;
}
export function resolveRefreshedSelection(
  input: RefreshSelectionInput,
): RefreshSelectionOutcome {
  const target = input.preferredGame || input.currentSelectedGame;
  if (target && input.games.some((game) => game.name === target)) {
    return { game: target, source: "preferred" };
  }
  const first = input.games[0]?.name ?? "";
  return { game: first, source: first ? "first" : "none" };
}
export function resolveAppliedSelection(input: AppliedSelectionInput): RefreshSelectionOutcome {
  const liveSelectionValid =
    input.liveSelection !== "" &&
    input.games.some((game) => game.name === input.liveSelection);

  return resolveRefreshedSelection({
    games: input.games,
    preferredGame: liveSelectionValid ? undefined : input.preferredGame,
    currentSelectedGame: input.liveSelection,
  });
}
