import { autoSyncStatusText } from "./autoSyncStatusRenderer";
import type { LudusaviStateSnapshot } from "../state/ludusaviState";
import type { AutoSyncStatusFact, AutoSyncStatusKind, SteamCloudEligibility } from "../types";

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
  lifecycle?: "lifecycle_start" | "lifecycle_exit";
  label: string;
  description: string;
  tone: "neutral" | "info" | "success" | "warning" | "error";
  active: boolean;
  showRow: boolean;
  canOwnStatusArea: boolean;
};

export type GameDetailsStatusSelectorInput = {
  snapshot: Pick<LudusaviStateSnapshot, "settings" | "games" | "gameHistory" | "trackingReadiness" | "autoSyncObservations"> & { trackingRevision?: number };
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
  if (snapshot.trackingReadiness === "failed") {
    return model(eligibility, "unavailable", null, "Save status unavailable", "Ludusavi could not load tracking data.");
  }
  if (snapshot.trackingReadiness === "cold" || snapshot.settings === null || snapshot.games === null) {
    return model(eligibility, "loading", null, "Loading save status", "Ludusavi is loading save status.");
  }
  if (!canonicalGameName) return model(eligibility, "not_tracked", null, "Not tracked", "Ludusavi does not track this game.");
  const game = snapshot.games.find((candidate) => candidate.name === canonicalGameName);
  if (!game) return model(eligibility, "not_tracked", null, "Not tracked", "Ludusavi does not track this game.");
  if (game.error) return model(eligibility, "error", "error", "Save status error", game.error);

  const observation = snapshot.autoSyncObservations[appID]?.canonicalGameName === canonicalGameName
    ? snapshot.autoSyncObservations[appID] : null;
  const local = observation?.localOperation ?? null;
  const sync = observation?.syncObservation ?? null;
  const syncVerification = observation?.activity === "unverified"
    ? "unverified"
    : sync ? "observed" : "not_checked";

  // Accepted active work always remains visible, even when a setting changes.
  if (observation?.activity === "active") {
    return statusModel(
      eligibility, "active", observation.status, local?.status ?? null, sync?.status ?? null,
      true, syncVerification, observation.lifecycle, observation.resultStatus,
    );
  }
  // Once work is idle, current settings describe what can happen next. Retained
  // observations remain available as secondary context rather than overriding it.
  if (snapshot.settings.auto_sync_enabled === false) {
    return model(eligibility, "auto_sync_disabled", "game_sync_disabled", "Automatic sync is off", "Ludusavi automatic save sync is disabled.", local?.status ?? null, sync?.status ?? null, syncVerification, observation?.lifecycle);
  }
  if (snapshot.settings.sync_disabled_games.includes(canonicalGameName)) {
    return model(eligibility, "game_sync_disabled", "game_sync_disabled", "Sync disabled for this game", "Ludusavi automatic save sync is disabled for this game.", local?.status ?? null, sync?.status ?? null, syncVerification, observation?.lifecycle);
  }
  if ((game.needs_first_backup || game.status === "needs_first_backup")
    && !isCurrentInventoryFact(local, snapshot.trackingRevision ?? 0)) {
    return model(eligibility, "needs_backup", "unknown", "Backup needed", "Ludusavi has not made the first backup for this game.", local?.status ?? null, sync?.status ?? null, syncVerification, observation?.lifecycle);
  }

  const observedSync = observation?.activity === "settled" ? sync : null;
  const primary = newerFact(local, observedSync);
  if (primary) {
    return statusModel(
      eligibility,
      primary === local ? "local_result" : "last_observed",
      primary.status,
      local?.status ?? null,
      sync?.status ?? null,
      false,
      syncVerification,
      observation?.lifecycle,
      primary.resultStatus,
      local?.resultStatus,
      primary === observedSync,
      local?.lifecycle ?? observation?.lifecycle,
      sync?.lifecycle ?? observation?.lifecycle,
    );
  }
  if (local) {
    return statusModel(
      eligibility, "local_result", local.status, local.status, sync?.status ?? null,
      false, syncVerification, observation?.lifecycle, local.resultStatus, local.resultStatus,
      false,
      local.lifecycle ?? observation?.lifecycle,
      sync?.lifecycle ?? observation?.lifecycle,
    );
  }

  // Inventory is authoritative for current backup presence. Durable history is
  // useful after reload, but is not proof that the backup still exists.
  if (game.needs_first_backup || game.status === "needs_first_backup") {
    return model(eligibility, "needs_backup", "unknown", "Backup needed", "Ludusavi has not made the first backup for this game.", observation?.localOperation?.status ?? null, observation?.syncObservation?.status ?? null, syncVerification, observation?.lifecycle);
  }
  const durableOperation = snapshot.gameHistory[canonicalGameName]?.last_operation ?? null;
  if (durableOperation) {
    const status = durableStatus(durableOperation.status);
    return statusModel(eligibility, "local_result", status, status, sync?.status ?? null, false, observation ? syncVerification : "unverified", observation?.lifecycle, durableOperation.status, durableOperation.status, false, undefined, sync?.lifecycle ?? observation?.lifecycle);
  }
  if (game.has_backup || game.status === "has_backup") {
    return model(eligibility, "local_backup_available", "has_backup", "Local backup available", "Ludusavi reports a local backup for this game.", observation?.localOperation?.status ?? null, observation?.syncObservation?.status ?? null, syncVerification, observation?.lifecycle);
  }
  return model(eligibility, "unavailable", "unknown", "Save status unavailable", "Ludusavi could not verify this save status.");
}

function newerFact(local: AutoSyncStatusFact | null, sync: AutoSyncStatusFact | null): AutoSyncStatusFact | null {
  if (!local) return sync;
  if (!sync) return local;
  if (local.observedAt !== sync.observedAt) return local.observedAt > sync.observedAt ? local : sync;
  return (local.publicationOrder ?? 0) >= (sync.publicationOrder ?? 0) ? local : sync;
}

function isCurrentInventoryFact(fact: AutoSyncStatusFact | null, trackingRevision: number): boolean {
  return fact?.trackingRevision !== undefined && fact.trackingRevision >= trackingRevision;
}

function durableStatus(status: "backed_up" | "restored" | "skipped" | "failed"): AutoSyncStatusKind {
  if (status === "backed_up" || status === "restored") return "has_backup";
  return status === "failed" ? "error" : "unknown";
}

function hidden(eligibility: SteamCloudEligibility): GameDetailsStatusViewModel {
  return { eligibility, kind: "hidden", status: null, localStatus: null, syncStatus: null, syncVerification: "not_checked", label: "", description: "", tone: "neutral", active: false, showRow: false, canOwnStatusArea: false };
}

function model(
  eligibility: SteamCloudEligibility,
  kind: GameDetailsStatusKind,
  status: AutoSyncStatusKind | null,
  label: string,
  description: string,
  localStatus: AutoSyncStatusKind | null = null,
  syncStatus: AutoSyncStatusKind | null = null,
  syncVerification: GameDetailsStatusViewModel["syncVerification"] = "not_checked",
  lifecycle?: "lifecycle_start" | "lifecycle_exit",
): GameDetailsStatusViewModel {
  return { eligibility, kind, status, localStatus, syncStatus, syncVerification, lifecycle, label: `Ludusavi: ${label}`, description: `${description}${syncDetail(syncStatus, syncVerification, lifecycle)}`, tone: toneForStatus(status), active: false, showRow: true, canOwnStatusArea: true };
}

function statusModel(
  eligibility: SteamCloudEligibility,
  kind: GameDetailsStatusKind,
  status: AutoSyncStatusKind,
  localStatus: AutoSyncStatusKind | null,
  syncStatus: AutoSyncStatusKind | null,
  active: boolean,
  syncVerification: "not_checked" | "unverified" | "observed",
  lifecycle?: "lifecycle_start" | "lifecycle_exit",
  resultStatus?: AutoSyncStatusFact["resultStatus"],
  localResultStatus?: AutoSyncStatusFact["resultStatus"],
  primaryIsSync = false,
  localLifecycle = lifecycle,
  syncLifecycle = lifecycle,
): GameDetailsStatusViewModel {
  const prefix = kind === "last_observed" ? "Last remote observation" : active ? "Current activity" : "Local result";
  const primaryLifecycle = primaryIsSync ? syncLifecycle : localLifecycle;
  const primary = statusPhrase(status, resultStatus, primaryLifecycle);
  const localDetail = localStatus && localStatus !== status ? ` Local result: ${statusPhrase(localStatus, localResultStatus, localLifecycle)}.` : "";
  const detail = `${prefix}: ${primary}.${localDetail}${primaryIsSync ? "" : syncDetail(syncStatus, syncVerification, syncLifecycle)}`;
  return {
    eligibility, kind, status, localStatus, syncStatus, syncVerification, lifecycle,
    label: `Ludusavi: ${prefix}: ${primary}`,
    description: detail,
    tone: toneForStatus(status),
    active,
    showRow: true,
    canOwnStatusArea: true,
  };
}

function statusPhrase(
  status: AutoSyncStatusKind,
  resultStatus?: AutoSyncStatusFact["resultStatus"],
  lifecycle?: "lifecycle_start" | "lifecycle_exit",
): string {
  if (status === "has_backup" && resultStatus === "skipped") return "Local save already current";
  if (status === "has_backup" && resultStatus === "restored") return "Local restore complete";
  if (status === "unknown" && resultStatus === "skipped") return "Local operation skipped";
  if (status === "syncthing_complete") return lifecycle === "lifecycle_exit"
    ? "Remote upload observed with a connected peer"
    : "Incoming folder activity settled";
  const labels: Partial<Record<AutoSyncStatusKind, string>> = {
    checking: "Checking local save",
    backing_up: "Backing up local save",
    restoring: "Restoring local save",
    conflict: "Save conflict needs attention",
    conflict_unresolved: "Save conflict was not resolved",
    game_sync_disabled: "Automatic sync is disabled",
    has_backup: "Local backup complete",
    unknown: "Save result is unknown",
    error: "Local save operation failed",
    syncthing_pending_upload: "Preparing remote sync",
    syncthing_downloading: "Receiving remote save data",
    syncthing_uploading: "Uploading save data",
    syncthing_upload_incomplete: "Remote upload is incomplete",
    syncthing_unavailable: "Remote sync is unavailable",
    syncthing_folder_not_found: "Remote folder was not found",
    syncthing_no_peers: "No relevant remote peer is connected",
  };
  return labels[status] ?? autoSyncStatusText[status];
}

function syncDetail(
  syncStatus: AutoSyncStatusKind | null,
  verification: GameDetailsStatusViewModel["syncVerification"],
  lifecycle?: "lifecycle_start" | "lifecycle_exit",
): string {
  if (syncStatus && verification === "observed") return ` Remote observation: ${statusPhrase(syncStatus, undefined, lifecycle)}.`;
  if (syncStatus && verification === "unverified") return " Remote sync is unverified after interrupted activity.";
  if (verification === "unverified") return " Remote sync was not checked after reload.";
  return "";
}

function toneForStatus(status: AutoSyncStatusKind | null): GameDetailsStatusViewModel["tone"] {
  if (status === "error") return "error";
  if (["unknown", "conflict", "conflict_unresolved", "game_sync_disabled", "syncthing_upload_incomplete", "syncthing_unavailable", "syncthing_folder_not_found", "syncthing_no_peers"].includes(status ?? "")) return "warning";
  if (status === "has_backup" || status === "syncthing_complete") return "success";
  return "info";
}
