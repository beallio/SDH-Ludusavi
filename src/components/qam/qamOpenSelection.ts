export function resolveQamOpenSelection({
  isQuickAccessVisible,
  pendingSelection,
  gameCount,
  operationInProgress
}: {
  isQuickAccessVisible: boolean;
  pendingSelection: boolean;
  gameCount: number;
  operationInProgress: boolean;
}): "select" | "wait" | "consume" {
  if (!isQuickAccessVisible) return "wait";
  if (!pendingSelection) return "wait";
  if (gameCount === 0 || operationInProgress) return "consume";
  return "select";
}
