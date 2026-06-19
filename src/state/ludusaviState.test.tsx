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
});
