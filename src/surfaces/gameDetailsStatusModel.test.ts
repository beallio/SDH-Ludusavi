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
});
