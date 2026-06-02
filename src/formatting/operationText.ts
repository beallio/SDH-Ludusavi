import type { LifecycleCheckResult, OperationResult } from "../types";

export function getLastOperationText(
  status: string,
  reason: string | null,
  message: string | null = null
): string {
  switch (status) {
    case "backed_up":
      return "Backup complete";
    case "restored":
      return "Restore complete";
    case "failed":
      const err = message || reason;
      return err ? `Failed — ${err}` : "Failed — check logs";
    case "skipped":
      if (reason) {
        switch (reason) {
          case "local_current":
            return "Skipped — local save is already current";
          case "remote_current":
            return "Skipped — cloud save is already current";
          case "not_processed":
            return "Skipped — game is deselected in Ludusavi";
          case "no_backup":
            return "Skipped — no backup found";
          case "ambiguous_recency":
            return "Skipped — recency is ambiguous";
          case "conflict_unresolved":
            return "Skipped — save conflict was not resolved";
          case "no_files_found":
            return "Skipped — no files found";
          case "preview_failed":
            return "Skipped — preview failed";
          case "auto_sync_disabled":
            return "Skipped — feature disabled";
          case "operation_running":
            return "Skipped — another operation is running";
          case "unmatched_game":
            return "Skipped — could not match game name";
          default:
            return `Skipped — ${reason.replace(/_/g, " ")}`;
        }
      }
      return message ? `Skipped — ${message}` : "Skipped";
    default:
      return "No operation yet";
  }
}

export function summarizeOperationResult(
  result: OperationResult | LifecycleCheckResult,
  label: string
) {
  if (result.status === "conflict") {
    return `Auto-sync needs a save conflict decision for ${result.game ?? "this game"}`;
  }
  if (result.status === "skipped") {
    switch (result.reason) {
      case "auto_sync_disabled": return `Auto-sync skipped: feature disabled`;
      case "operation_running": return `Auto-sync skipped: another operation is running`;
      case "unmatched_game": return `Auto-sync skipped: could not match game name`;
      case "not_processed": return `Auto-sync skipped: game is deselected in Ludusavi`;
      case "no_backup": return `Auto-sync skipped: no backup found for ${result.game}`;

      case "local_current": return `Auto-sync skipped: local save is already current`;
      case "ambiguous_recency": return `Auto-sync skipped: recency is ambiguous`;
      case "conflict_unresolved": return `Auto-sync skipped: save conflict was not resolved`;
      default: return `${label} skipped: ${result.reason ?? "unknown reason"}`;
    }
  }
  if (result.status === "failed") {
    return `${label} failed: ${result.message ?? "unknown error"}`;
  }
  const action = result.status === "backed_up" ? "Backup" : "Restore";
  return `${action} completed for ${result.game}`;
}
