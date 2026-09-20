import { describe, expect, it } from "vitest";

import {
  getSteamCloudEligibility,
  selectGameDetailsStatus,
} from "./gameDetailsStatusModel";

const settings = {
  auto_sync_enabled: true,
  sync_disabled_games: [],
  selected_game: "",
  notifications: {
    enabled: true,
    auto_sync_progress: true,
    auto_sync_results: true,
    manual_operations: true,
    refresh_status: true,
    failures_errors: true,
    update_available: true,
  },
  update_channel: "stable" as const,
  automatic_update_checks: true,
  debug_logging: true,
};

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    settings,
    games: [{
      name: "Fixture",
      steam_id: "100",
      configured: true,
      has_backup: true,
      needs_first_backup: false,
      error: null,
      status: "has_backup" as const,
    }],
    gameAliases: {},
    gameHistory: {},
    selectedGame: "",
    installedAppIds: undefined,
    versions: null,
    ludusaviCommand: null,
    trackedAppIDs: new Set(["100"]),
    trackedNames: new Set(["fixture"]),
    trackingReadiness: "ready" as const,
    autoSyncObservations: {},
    ...overrides,
  };
}

describe("Steam Cloud eligibility", () => {
  it("requires matching loaded details and both boolean Cloud flags", () => {
    expect(getSteamCloudEligibility("100", null)).toBe("unknown");
    expect(getSteamCloudEligibility("100", {})).toBe("unknown");
    expect(getSteamCloudEligibility("100", {
      unAppID: 101,
      bCloudEnabledForApp: false,
      bCloudEnabledForAccount: false,
    })).toBe("unknown");
    expect(getSteamCloudEligibility("100", {
      unAppID: 100,
      bCloudEnabledForApp: false,
    })).toBe("unknown");
  });

  it("blocks only a selected entry with both Cloud switches enabled", () => {
    expect(getSteamCloudEligibility("100", {
      unAppID: 100,
      bCloudEnabledForApp: true,
      bCloudEnabledForAccount: true,
    })).toBe("blocked");
    expect(getSteamCloudEligibility("100", {
      unAppID: 100,
      bCloudEnabledForApp: false,
      bCloudEnabledForAccount: true,
    })).toBe("eligible");
    expect(getSteamCloudEligibility("100", {
      unAppID: 100,
      bCloudEnabledForApp: true,
      bCloudEnabledForAccount: false,
    })).toBe("eligible");
  });
});

describe("game details status selection", () => {
  it("retains an accepted Syncthing limitation for its app without losing its local result", () => {
    const state = snapshot({
      autoSyncObservations: {
        "100": {
          appID: "100",
          gameName: "Fixture",
          canonicalGameName: "Fixture",
          lifecycle: "lifecycle_exit",
          generation: 7,
          status: "syncthing_folder_not_found",
          activity: "settled",
          observedAt: 200,
          localOperation: {
            status: "has_backup",
            resultStatus: "backed_up",
            observedAt: 100,
            generation: 7,
          },
          syncObservation: {
            status: "syncthing_folder_not_found",
            observedAt: 200,
            generation: 7,
          },
        },
      },
    });

    const selected = selectGameDetailsStatus({
      snapshot: state,
      appID: "100",
      gameName: "Fixture",
      canonicalGameName: "Fixture",
      eligibility: "eligible",
    });
    expect(selected.kind).toBe("last_observed");
    expect(selected.localStatus).toBe("has_backup");
    expect(selected.syncStatus).toBe("syncthing_folder_not_found");
    expect(selected.canOwnStatusArea).toBe(true);
    expect(selected.label).toBe("Ludusavi: Unable to sync");

    const otherGame = selectGameDetailsStatus({
      snapshot: state,
      appID: "101",
      gameName: "Other",
      canonicalGameName: null,
      eligibility: "eligible",
    });
    expect(otherGame.kind).toBe("not_tracked");
    expect(otherGame.syncStatus).toBeNull();
  });

  it("uses a reload's last durable local operation without inventing remote delivery", () => {
    const state = snapshot({
      gameHistory: {
        Fixture: {
          last_backup: {
            operation: "backup",
            trigger: "auto_exit",
            status: "backed_up",
            reason: null,
            message: null,
            timestamp: "2026-09-13 12:00:00",
          },
          last_restore: null,
          last_skip: null,
          last_failure: {
            operation: "backup",
            trigger: "auto_exit",
            status: "failed",
            reason: null,
            message: "old failure",
            timestamp: "2026-09-13 11:00:00",
          },
          last_operation: {
            operation: "backup",
            trigger: "auto_exit",
            status: "backed_up",
            reason: null,
            message: null,
            timestamp: "2026-09-13 12:00:00",
          },
        },
      },
    });

    const selected = selectGameDetailsStatus({
      snapshot: state,
      appID: "100",
      gameName: "Fixture",
      canonicalGameName: "Fixture",
      eligibility: "eligible",
    });
    expect(selected.kind).toBe("local_result");
    expect(selected.status).toBe("has_backup");
    expect(selected.syncStatus).toBeNull();
    expect(selected.syncVerification).toBe("unverified");
  });

  it("keeps a skipped local-current result up to date after reload", () => {
    const operation = {
      operation: "backup",
      trigger: "manual_backup",
      status: "skipped",
      reason: "local_current",
      message: null,
      timestamp: "2026-09-13 12:00:00",
    } as const;
    const selected = selectGameDetailsStatus({
      snapshot: snapshot({ gameHistory: { Fixture: {
        last_backup: null,
        last_restore: null,
        last_skip: operation,
        last_failure: null,
        last_operation: operation,
      } } }),
      appID: "100",
      gameName: "Fixture",
      canonicalGameName: "Fixture",
      eligibility: "eligible",
    });

    expect(selected.status).toBe("has_backup");
    expect(selected.label).toBe("Ludusavi: Up to date");
    expect(selected.description).toContain("Local save already current");
    expect(selected.description).toContain("Remote sync was not checked after reload");
  });

  it("uses the normal native row treatment for an unknown durable result", () => {
    const operation = {
      operation: "restore",
      trigger: "manual_restore",
      status: "skipped",
      reason: "no_backup",
      message: null,
      timestamp: "2026-09-13 12:00:00",
    } as const;
    const selected = selectGameDetailsStatus({
      snapshot: snapshot({ gameHistory: { Fixture: {
        last_backup: null,
        last_restore: null,
        last_skip: operation,
        last_failure: null,
        last_operation: operation,
      } } }),
      appID: "100",
      gameName: "Fixture",
      canonicalGameName: "Fixture",
      eligibility: "eligible",
    });

    expect(selected.status).toBe("unknown");
    expect(selected.label).toBe("Ludusavi: Unknown");
    expect(selected.tone).toBe("info");
  });

  it("does not use retained history as proof for an untracked or missing entry", () => {
    const state = snapshot({
      games: [],
      trackedAppIDs: new Set(),
      trackedNames: new Set(),
      gameHistory: {
        Fixture: {
          last_backup: null,
          last_restore: null,
          last_skip: null,
          last_failure: null,
          last_operation: {
            operation: "backup",
            trigger: "manual_backup",
            status: "backed_up",
            reason: null,
            message: null,
            timestamp: "2026-09-13 12:00:00",
          },
        },
      },
    });

    const selected = selectGameDetailsStatus({
      snapshot: state,
      appID: "100",
      gameName: "Fixture",
      canonicalGameName: null,
      eligibility: "eligible",
    });
    expect(selected.kind).toBe("not_tracked");
    expect(selected.status).toBeNull();
  });

  it("uses failed readiness, local terminal facts, and current inventory before older history", () => {
    const failed = selectGameDetailsStatus({
      snapshot: snapshot({ games: null, trackingReadiness: "failed" }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(failed.kind).toBe("unavailable");

    const localFailure = selectGameDetailsStatus({
      snapshot: snapshot({ autoSyncObservations: {
        "100": {
          appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", lifecycle: "lifecycle_start", generation: 3,
          status: "error", activity: "settled", observedAt: 30, resultStatus: "failed",
          localOperation: { status: "error", resultStatus: "failed", observedAt: 30, generation: 3 },
          syncObservation: { status: "syncthing_complete", observedAt: 20, generation: 3 },
        },
      } }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(localFailure.kind).toBe("local_result");
    expect(localFailure.status).toBe("error");

    const backupNeeded = selectGameDetailsStatus({
      snapshot: snapshot({
        games: [{ name: "Fixture", steam_id: "100", configured: true, has_backup: false, needs_first_backup: true, error: null, status: "needs_first_backup" }],
        gameHistory: { Fixture: { last_backup: null, last_restore: null, last_skip: null, last_failure: null, last_operation: { operation: "backup", trigger: "manual_backup", status: "backed_up", reason: null, message: null, timestamp: "2026-09-13 12:00:00" } } },
      }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(backupNeeded.kind).toBe("needs_backup");
  });

  it("does not present canceled transfers as active and applies disabled settings after activity settles", () => {
    const settled = snapshot({
      settings: { ...settings, auto_sync_enabled: false },
      autoSyncObservations: { "100": {
        appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", lifecycle: "lifecycle_exit", generation: 4,
        status: "syncthing_pending_upload", activity: "unverified", observedAt: 40,
        localOperation: { status: "has_backup", observedAt: 20, generation: 4 },
        syncObservation: { status: "syncthing_pending_upload", observedAt: 40, generation: 4 },
      } },
    });
    const disabled = selectGameDetailsStatus({ snapshot: settled, appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible" });
    expect(disabled.kind).toBe("auto_sync_disabled");
    expect(disabled.active).toBe(false);

    const settledObservation = (settled.autoSyncObservations as Record<string, any>)["100"];
    const active = selectGameDetailsStatus({
      snapshot: { ...settled, settings: { ...settings, auto_sync_enabled: false }, autoSyncObservations: { "100": { ...settledObservation, activity: "active" } } },
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(active.kind).toBe("active");
  });

  it("keeps local and remote wording tied to their own result and lifecycle", () => {
    const start = selectGameDetailsStatus({
      snapshot: snapshot({ autoSyncObservations: { "100": {
        appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", lifecycle: "lifecycle_start", generation: 5,
        status: "syncthing_complete", activity: "settled", observedAt: 20,
        localOperation: { status: "has_backup", resultStatus: "skipped", observedAt: 10, generation: 5 },
        syncObservation: { status: "syncthing_complete", observedAt: 20, generation: 5 },
      } } }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(start.description).toContain("Local result: Local save already current.");
    expect(start.description).toContain("Last remote observation: Incoming folder activity settled.");

    const exit = selectGameDetailsStatus({
      snapshot: snapshot({ autoSyncObservations: { "100": {
        appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", lifecycle: "lifecycle_exit", generation: 6,
        status: "syncthing_complete", activity: "settled", observedAt: 20,
        localOperation: { status: "has_backup", resultStatus: "backed_up", observedAt: 10, generation: 6 },
        syncObservation: { status: "syncthing_complete", observedAt: 20, generation: 6 },
      } } }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(exit.description).toContain("Remote upload observed with a connected peer.");
    expect(exit.description).not.toContain("Incoming folder activity settled.");
  });

  it("uses Steam-style visible statuses while retaining detailed local meaning", () => {
    const restored = selectGameDetailsStatus({
      snapshot: snapshot({ gameHistory: { Fixture: {
        last_backup: null, last_restore: null, last_skip: null, last_failure: null,
        last_operation: {
          operation: "restore", trigger: "manual_restore", status: "restored", reason: null, message: null,
          timestamp: "2026-09-13 12:00:00",
        },
      } } }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(restored.label).toBe("Ludusavi: Up to date");
    expect(restored.description).toContain("Local restore complete");

    const active = selectGameDetailsStatus({
      snapshot: snapshot({ autoSyncObservations: { "100": {
        appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", lifecycle: "lifecycle_exit", generation: 8,
        status: "backing_up", activity: "active", observedAt: 30,
        localOperation: { status: "backing_up", observedAt: 30, generation: 8 },
        syncObservation: null,
      } } }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(active.label).toBe("Ludusavi: Backing up...");
    expect(active.description).toContain("Current activity: Backing up local save.");

    const disabled = selectGameDetailsStatus({
      snapshot: snapshot({ settings: { ...settings, auto_sync_enabled: false } }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(disabled.label).toBe("Ludusavi: Disabled");
  });

  it("honors fresh missing-backup inventory unless a local result is newer", () => {
    const inventory = { games: [{ name: "Fixture", steam_id: "100", configured: true, has_backup: false, needs_first_backup: true, error: null, status: "needs_first_backup" as const }], trackingRevision: 2 };
    const live = (trackingRevision: number) => ({ "100": { appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", lifecycle: "lifecycle_exit" as const, generation: 4, status: "has_backup" as const, activity: "settled" as const, observedAt: 10, localOperation: { status: "has_backup" as const, resultStatus: "backed_up" as const, observedAt: 10, generation: 4, trackingRevision }, syncObservation: null } });
    const stale = selectGameDetailsStatus({
      snapshot: snapshot({ ...inventory, autoSyncObservations: live(1) }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(stale.kind).toBe("needs_backup");
    const current = selectGameDetailsStatus({
      snapshot: snapshot({ ...inventory, autoSyncObservations: live(2) }),
      appID: "100", gameName: "Fixture", canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(current.kind).toBe("local_result");
  });

});
