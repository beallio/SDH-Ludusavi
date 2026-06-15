import { describe, it, expect, vi } from "vitest";
import { createPluginRuntime } from "./pluginRuntime";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {},
}));

vi.mock("react", () => ({
  createContext: vi.fn(),
  useContext: vi.fn(),
  useSyncExternalStore: vi.fn(),
}));

vi.mock("react/jsx-dev-runtime", () => ({
  jsxDEV: vi.fn(),
  Fragment: Symbol("Fragment"),
}));

describe("PluginRuntime", () => {
  describe("ContentLoadCoordinator", () => {
    it("round-trips promises", () => {
      const runtime = createPluginRuntime();
      const initP = Promise.resolve({ is_running: false, name: null, game_name: null, last_result: null, last_error: null });
      const metaP = Promise.resolve();

      expect(runtime.contentLoad.initPromise).toBeNull();
      runtime.contentLoad.initPromise = initP;
      expect(runtime.contentLoad.initPromise).toBe(initP);

      expect(runtime.contentLoad.metadataPromise).toBeNull();
      runtime.contentLoad.metadataPromise = metaP;
      expect(runtime.contentLoad.metadataPromise).toBe(metaP);
    });

    it("dispose nulls promises", () => {
      const runtime = createPluginRuntime();
      runtime.contentLoad.initPromise = Promise.resolve({ is_running: false, name: null, game_name: null, last_result: null, last_error: null });
      runtime.contentLoad.metadataPromise = Promise.resolve();
      runtime.dispose();
      expect(runtime.contentLoad.initPromise).toBeNull();
      expect(runtime.contentLoad.metadataPromise).toBeNull();
    });

    it("two runtimes are independent", () => {
      const r1 = createPluginRuntime();
      const r2 = createPluginRuntime();
      const p = Promise.resolve();
      
      r1.contentLoad.metadataPromise = p;
      expect(r1.contentLoad.metadataPromise).toBe(p);
      expect(r2.contentLoad.metadataPromise).toBeNull();
    });
  });

  describe("override injection and dispose delegation", () => {
    it("delegates dispose and allows overrides with correct ordering", () => {
      const order: string[] = [];

      const statusSurfaceDispose = vi.fn(() => { order.push("statusSurface"); });
      const settingsDispose = vi.fn(() => { order.push("settings"); });

      const overrides = {
        statusSurface: {
          publish: vi.fn(),
          hide: vi.fn(),
          complete: vi.fn(),
          dispose: statusSurfaceDispose
        } as any,
        settings: {
          dispose: settingsDispose
        } as any,
        contentLoad: {
          initPromise: null,
          metadataPromise: null,
        }
      };
      
      const runtime = createPluginRuntime(overrides);
      expect(runtime.contentLoad).toBe(overrides.contentLoad);
      
      runtime.dispose();
      
      expect(order).toEqual(["statusSurface", "settings"]);
    });
  });
});
