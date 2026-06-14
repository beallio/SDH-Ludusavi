import type { LifecycleCheckResult, OperationResult } from "../types";

export function getLastOperationText(
  status: string,
  reason: string | null,
  message: string | null = null,
  operation: string | null = null
): string {
  switch (status) {
    case "backed_up":
      return "Backup complete";
    case "restored":
      return "Restore complete";
    case "failed": {
      const err = message || reason;
      return err ? `Failed — ${err}` : "Failed — check logs";
    }
    case "skipped": {
      const isRestore = operation === "restore" || operation === "start";
      const isBackup = operation === "backup" || operation === "exit";
      const label = isRestore ? "Restore skipped" : isBackup ? "Backup skipped" : "Skipped";

      let detail: string | null = null;
      if (reason) {
        switch (reason) {
          case "local_current":
            detail = isRestore ? "local save already matches backup" : "local save is already current";
            break;
          case "remote_current":
            detail = "cloud save is already current";
            break;
          case "not_processed":
            detail = "game is deselected in Ludusavi";
            break;
          case "no_backup":
            detail = "no backup found";
            break;
          case "ambiguous_recency":
            detail = "recency is ambiguous";
            break;
          case "conflict_unresolved":
            detail = "save conflict was not resolved";
            break;
          case "no_files_found":
            detail = "no files found";
            break;
          case "preview_failed":
            detail = "preview failed";
            break;
          case "auto_sync_disabled":
            detail = "feature disabled";
            break;
          case "operation_running":
            detail = "another operation is running";
            break;
          case "unmatched_game":
            detail = "could not match game name";
            break;
          default:
            detail = reason.replace(/_/g, " ");
        }
      } else if (message) {
        detail = message;
      }

      return detail ? `${label} — ${detail}` : label;
    }
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
