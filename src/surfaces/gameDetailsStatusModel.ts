import { autoSyncStatusText, isLudusaviRunningStatus, isSyncthingActiveStatus } from "./autoSyncStatusRenderer";
import type { LudusaviStateSnapshot } from "../state/ludusaviState";
import type { AutoSyncStatusKind, SteamCloudEligibility } from "../types";

export type GameDetailsStatusKind =
  | "hidden" | "loading" | "unavailable" | "not_tracked"
  | "auto_sync_disabled" | "game_sync_disabled" | "needs_backup"
  | "local_backup_available" | "error" | "active" | "local_result" | "last_observed";

export type GameDetailsStatusViewModel = {
  eligibility: SteamCloudEligibility;
  kind: GameDetailsStatusKind;
  status: AutoSyncStatusKind | null;
  localStatus: AutoSyncStatusKind | null;
  syncStatus: AutoSyncStatusKind | null;
  syncVerification: "not_checked" | "unverified" | "observed";
  label: string;
  description: string;
  tone: "neutral" | "info" | "success" | "warning" | "error";
  active: boolean;
  showRow: boolean;
  canOwnStatusArea: boolean;
};

export type GameDetailsStatusSelectorInput = {
  snapshot: Pick<LudusaviStateSnapshot, "settings" | "games" | "gameHistory" | "trackingReadiness" | "autoSyncObservations">;
  appID: string;
  gameName: string;
  canonicalGameName: string | null;
  eligibility: SteamCloudEligibility;
};

export function getSteamCloudEligibility(appID: string, details: unknown): SteamCloudEligibility {
  if (!details || typeof details !== "object") return "unknown";
  const record = details as Record<string, unknown>;
  if (String(record.unAppID) !== String(appID)) return "unknown";
  if (typeof record.bCloudEnabledForApp !== "boolean" || typeof record.bCloudEnabledForAccount !== "boolean") return "unknown";
  return record.bCloudEnabledForApp && record.bCloudEnabledForAccount ? "blocked" : "eligible";
}

export function selectGameDetailsStatus(input: GameDetailsStatusSelectorInput): GameDetailsStatusViewModel {
  const { snapshot, appID, canonicalGameName, eligibility } = input;
  if (eligibility !== "eligible") return hidden(eligibility);
  if (snapshot.trackingReadiness === "cold" || snapshot.settings === null || snapshot.games === null) {
    return model(eligibility, "loading", null, "Loading save status", "Ludusavi is loading save status.");
  }
  if (snapshot.trackingReadiness === "failed") {
    return model(eligibility, "unavailable", null, "Save status unavailable", "Ludusavi could not load tracking data.");
  }
  if (!canonicalGameName) return model(eligibility, "not_tracked", null, "Not tracked", "Ludusavi does not track this game.");
  const game = snapshot.games.find((candidate) => candidate.name === canonicalGameName);
  if (!game) return model(eligibility, "not_tracked", null, "Not tracked", "Ludusavi does not track this game.");
  if (game.error) return model(eligibility, "error", "error", "Save status error", game.error);

  const observation = snapshot.autoSyncObservations[appID]?.canonicalGameName === canonicalGameName
    ? snapshot.autoSyncObservations[appID] : null;
  const durableOperation = snapshot.gameHistory[canonicalGameName]?.last_operation ?? null;
  const replacedByHistory = Boolean(
    observation?.localOperation?.historyTimestamp && durableOperation?.timestamp
    && durableOperation.timestamp > observation.localOperation.historyTimestamp,
  );
  if (observation && !replacedByHistory && observation.activity === "active") {
    return statusModel(eligibility, "active", observation.status, observation.localOperation?.status ?? null, observation.syncObservation?.status ?? null, true, "observed");
  }
  if (observation && !replacedByHistory && observation.syncObservation) {
    return statusModel(eligibility, "last_observed", observation.syncObservation.status, observation.localOperation?.status ?? null, observation.syncObservation.status, false, "observed");
  }
  if (snapshot.settings.auto_sync_enabled === false) {
    return model(eligibility, "auto_sync_disabled", "game_sync_disabled", "Automatic sync is off", "Ludusavi automatic save sync is disabled.");
  }
  if (snapshot.settings.sync_disabled_games.includes(canonicalGameName)) {
    return model(eligibility, "game_sync_disabled", "game_sync_disabled", "Sync disabled for this game", "Ludusavi automatic save sync is disabled for this game.");
  }
  if (durableOperation) {
    const status = durableStatus(durableOperation.status);
    return statusModel(eligibility, "local_result", status, status, null, false, "unverified", true);
  }
  if (game.needs_first_backup || game.status === "needs_first_backup") {
    return model(eligibility, "needs_backup", "unknown", "Backup needed", "Ludusavi has not made the first backup for this game.");
  }
  if (game.has_backup || game.status === "has_backup") {
    return model(eligibility, "local_backup_available", "has_backup", "Local backup available", "Ludusavi reports a local backup for this game.");
  }
  return model(eligibility, "unavailable", "unknown", "Save status unavailable", "Ludusavi could not verify this save status.");
}

function durableStatus(status: "backed_up" | "restored" | "skipped" | "failed"): AutoSyncStatusKind {
  if (status === "backed_up" || status === "restored") return "has_backup";
  return status === "failed" ? "error" : "unknown";
}

function hidden(eligibility: SteamCloudEligibility): GameDetailsStatusViewModel {
  return { eligibility, kind: "hidden", status: null, localStatus: null, syncStatus: null, syncVerification: "not_checked", label: "", description: "", tone: "neutral", active: false, showRow: false, canOwnStatusArea: false };
}

function model(eligibility: SteamCloudEligibility, kind: GameDetailsStatusKind, status: AutoSyncStatusKind | null, label: string, description: string): GameDetailsStatusViewModel {
  return { eligibility, kind, status, localStatus: null, syncStatus: null, syncVerification: "not_checked", label: `Ludusavi: ${label}`, description, tone: toneForStatus(status), active: false, showRow: true, canOwnStatusArea: true };
}

function statusModel(eligibility: SteamCloudEligibility, kind: GameDetailsStatusKind, status: AutoSyncStatusKind, localStatus: AutoSyncStatusKind | null, syncStatus: AutoSyncStatusKind | null, active: boolean, syncVerification: "unverified" | "observed", historic = false): GameDetailsStatusViewModel {
  const prefix = historic ? "Last local result" : kind === "last_observed" ? "Last observed" : "Ludusavi";
  const localDetail = localStatus && syncStatus ? ` Local result: ${autoSyncStatusText[localStatus]}.` : "";
  return { eligibility, kind, status, localStatus, syncStatus, syncVerification, label: `${prefix}: ${autoSyncStatusText[status]}`, description: `${prefix}: ${autoSyncStatusText[status]}.${localDetail}`, tone: toneForStatus(status), active: active || isLudusaviRunningStatus(status) || isSyncthingActiveStatus(status), showRow: true, canOwnStatusArea: true };
}

function toneForStatus(status: AutoSyncStatusKind | null): GameDetailsStatusViewModel["tone"] {
  if (status === "error") return "error";
  if (["unknown", "conflict", "conflict_unresolved", "game_sync_disabled", "syncthing_upload_incomplete", "syncthing_unavailable", "syncthing_folder_not_found", "syncthing_no_peers"].includes(status ?? "")) return "warning";
  if (status === "has_backup" || status === "syncthing_complete") return "success";
  return "info";
}
