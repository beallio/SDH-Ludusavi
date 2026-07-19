import { describe, it, expect, vi } from "vitest";

vi.mock("react", () => ({
  createContext: vi.fn(),
  useContext: vi.fn(),
  useSyncExternalStore: vi.fn(),
}));

vi.mock("@decky/ui", () => ({}));
vi.mock("../ludusaviLauncher", () => ({}));
vi.mock("../utils/steam", () => ({
  normalize: (name: string) => name.toLowerCase()
}));
vi.mock("react/jsx-dev-runtime", () => ({
  jsxDEV: vi.fn(),
  Fragment: vi.fn(),
}));

import { createLudusaviStateStore } from "./ludusaviState";

describe("LudusaviStateStore", () => {
  describe("isTracked", () => {
    it("returns true for exact substring match without ambiguity", () => {
      const store = createLudusaviStateStore();
      store.applyRefreshResult({
        games: [
          { name: "Super Metroid", configured: true, has_backup: true },
        ] as any,
        history: {},
        aliases: {},
        dependency_error: null
      });

      const onMatch = vi.fn();
      const onMiss = vi.fn();

      const result = store.isTracked("Metroid", "123", onMatch, onMiss);
      expect(result).toBe(true);
      expect(onMatch).toHaveBeenCalledWith("substring", "metroid <-> super metroid");
      expect(onMiss).not.toHaveBeenCalled();
    });

    it("returns false for ambiguous substring match", () => {
      const store = createLudusaviStateStore();
      store.applyRefreshResult({
        games: [
          { name: "Portal 2", configured: true, has_backup: true },
          { name: "Portal Stories: Mel", configured: true, has_backup: true },
        ] as any,
        history: {},
        aliases: {},
        dependency_error: null
      });

      const onMatch = vi.fn();
      const onMiss = vi.fn();

      const result = store.isTracked("Portal", "123", onMatch, onMiss);
      expect(result).toBe(false);
      expect(onMatch).not.toHaveBeenCalled();
      expect(onMiss).toHaveBeenCalledWith("portal");
    });
  });

  describe("Tracking readiness", () => {
    it("starts cold, sets ready on refresh, and failed on markTrackingFailed without clearing games", () => {
      const store = createLudusaviStateStore();
      expect(store.getSnapshot().trackingReadiness).toBe("cold");

      // empty-but-valid refresh sets readiness to ready
      store.applyRefreshResult({
        games: [],
        history: {},
        aliases: {},
        dependency_error: null
      });
      expect(store.getSnapshot().trackingReadiness).toBe("ready");
      expect(store.getSnapshot().games).toEqual([]);

      // markTrackingFailed sets failed and leaves games untouched
      store.markTrackingFailed();
      expect(store.getSnapshot().trackingReadiness).toBe("failed");
      expect(store.getSnapshot().games).toEqual([]);
    });
  });

  describe("Settings invariants", () => {
    it("maintains consistency across snapshot and settings when fields are mutated", () => {
      const store = createLudusaviStateStore();
      
      // Initial empty state has no settings but snapshot provides defaults for standalone fields
      expect(store.getSnapshot().settings).toBeNull();

      // Applying settings populates everything
      store.applySettings({
        auto_sync_enabled: true,
        sync_disabled_games: [],
        selected_game: "Hades",
        notifications: {
          enabled: true,
          auto_sync_progress: false,
          auto_sync_results: true,
          manual_operations: true,
          refresh_status: false,
          failures_errors: true,
        },
        update_channel: "stable",
        automatic_update_checks: false,
        debug_logging: true,
      });

      let snap = store.getSnapshot();
      expect(snap.selectedGame).toBe("Hades");
      expect(snap.settings?.selected_game).toBe("Hades");
      expect(snap.autoSyncNotificationsEnabled).toBe(true);
      expect(snap.settings?.auto_sync_enabled).toBe(true);
      expect(snap.notificationSettings.auto_sync_progress).toBe(false);
      expect(snap.settings?.notifications.auto_sync_progress).toBe(false);

      // Mutating selected game updates both
      store.setSelectedGame("Portal");
      snap = store.getSnapshot();
      expect(snap.selectedGame).toBe("Portal");
      expect(snap.settings?.selected_game).toBe("Portal");

      // Mutating auto sync updates both
      store.setAutoSyncEnabled(false);
      snap = store.getSnapshot();
      expect(snap.autoSyncNotificationsEnabled).toBe(false);
      expect(snap.settings?.auto_sync_enabled).toBe(false);

      // Mutating notification settings updates both
      store.setNotificationSettings({ ...snap.notificationSettings, refresh_status: true });
      snap = store.getSnapshot();
      expect(snap.notificationSettings.refresh_status).toBe(true);
      expect(snap.settings?.notifications.refresh_status).toBe(true);
    });

    it("normalizes malformed disabled games and patches sorted unique membership", () => {
      const store = createLudusaviStateStore();
      store.applySettings({
        auto_sync_enabled: true,
        sync_disabled_games: ["Hades", 1, "", "Celeste", "Hades"] as any,
        selected_game: "",
        notifications: {
          enabled: true,
          auto_sync_progress: true,
          auto_sync_results: true,
          manual_operations: true,
          refresh_status: true,
          failures_errors: true,
        },
        update_channel: "stable",
        automatic_update_checks: true,
        debug_logging: true,
      });

      expect(store.getSnapshot().settings?.sync_disabled_games).toEqual([
        "Hades",
        "Celeste",
        "Hades",
      ]);

      store.setGameSyncEnabled("Portal", false);
      store.setGameSyncEnabled("Celeste", false);
      expect(store.getSnapshot().settings?.sync_disabled_games).toEqual([
        "Celeste",
        "Hades",
        "Portal",
      ]);

      store.setGameSyncEnabled("Hades", true);
      expect(store.getSnapshot().settings?.sync_disabled_games).toEqual([
        "Celeste",
        "Portal",
      ]);
    });
  });

  describe("canonical game resolution", () => {
    function hydrateGames() {
      const store = createLudusaviStateStore();
      store.applySettings({
        auto_sync_enabled: true,
        sync_disabled_games: ["Hades", "Portal 2", "Doom"],
        selected_game: "",
        notifications: {
          enabled: true,
          auto_sync_progress: true,
          auto_sync_results: true,
          manual_operations: true,
          refresh_status: true,
          failures_errors: true,
        },
        update_channel: "stable",
        automatic_update_checks: true,
        debug_logging: true,
      });
      store.applyRefreshResult({
        games: [
          { name: "Hades", steam_id: 1145360, configured: true, has_backup: true },
          { name: "Hades II", steam_id: "1145350", configured: true, has_backup: true },
          { name: "Portal 2", configured: true, has_backup: true },
          { name: "Portal Stories: Mel", configured: true, has_backup: true },
          { name: "Doom", configured: true, has_backup: true },
        ] as any,
        history: {},
        aliases: { "Supergiant Hades": "Hades" },
        dependency_error: null,
      });
      return store;
    }

    it("resolves numeric app IDs before launch names", () => {
      const store = hydrateGames();

      expect(store.resolveCanonicalGameName("Different Launch Name", "1145360")).toBe("Hades");
      expect(store.isGameSyncDisabled("Different Launch Name", "1145360")).toBe(true);
    });

    it("resolves aliases and exact normalized names", () => {
      const store = hydrateGames();

      expect(store.resolveCanonicalGameName("Supergiant Hades", "")).toBe("Hades");
      expect(store.resolveCanonicalGameName("PORTAL 2", "")).toBe("Portal 2");
    });

    it("uses canonical app ID resolution to avoid Hades and Hades II false positives", () => {
      const store = hydrateGames();

      expect(store.resolveCanonicalGameName("Hades II", "1145350")).toBe("Hades II");
      expect(store.isGameSyncDisabled("Hades II", "1145350")).toBe(false);
    });

    it("rejects ambiguous substrings and unresolved empty registries", () => {
      const store = hydrateGames();

      expect(store.resolveCanonicalGameName("Portal", "")).toBeNull();

      const empty = createLudusaviStateStore();
      empty.applyRefreshResult({
        games: [],
        history: {},
        aliases: {},
        dependency_error: null,
      });
      expect(empty.resolveCanonicalGameName("Hades", "1145360")).toBeNull();
      expect(empty.isGameSyncDisabled("Hades", "1145360")).toBe(false);
    });

    it("applies backend short-name fuzzy eligibility rules", () => {
      const store = hydrateGames();

      expect(store.resolveCanonicalGameName("Doom Eternal", "")).toBe("Doom");
      expect(store.resolveCanonicalGameName("Doomer", "")).toBeNull();
    });
  });
});
