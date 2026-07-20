export type QamOpenSelectionAction = "wait" | "consume" | "select";

export interface QamOpenSelectionInput {
  isQuickAccessVisible: boolean;
  pendingSelection: boolean;
  gameCount: number;
  operationInProgress: boolean;
  explicitSelectionPending: boolean;
}

export function resolveQamOpenSelection(
  input: QamOpenSelectionInput,
): QamOpenSelectionAction {
  if (!input.isQuickAccessVisible || !input.pendingSelection || input.gameCount === 0) {
    return "wait";
  }
  if (input.explicitSelectionPending) {
    return "consume";
  }
  if (input.operationInProgress) {
    return "consume";
  }
  return "select";
}
