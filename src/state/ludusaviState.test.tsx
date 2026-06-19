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

  describe("Settings invariants", () => {
    it("maintains consistency across snapshot and settings when fields are mutated", () => {
      const store = createLudusaviStateStore();
      
      // Initial empty state has no settings but snapshot provides defaults for standalone fields
      expect(store.getSnapshot().settings).toBeNull();

      // Applying settings populates everything
      store.applySettings({
        auto_sync_enabled: true,
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
  });
});
