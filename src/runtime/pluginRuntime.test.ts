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

      expect(runtime.contentLoad.getInitPromise()).toBeNull();
      runtime.contentLoad.setInitPromise(initP);
      expect(runtime.contentLoad.getInitPromise()).toBe(initP);

      expect(runtime.contentLoad.getMetadataPromise()).toBeNull();
      runtime.contentLoad.setMetadataPromise(metaP);
      expect(runtime.contentLoad.getMetadataPromise()).toBe(metaP);
    });

    it("dispose nulls promises", () => {
      const runtime = createPluginRuntime();
      runtime.contentLoad.setInitPromise(Promise.resolve({ is_running: false, name: null, game_name: null, last_result: null, last_error: null }));
      runtime.contentLoad.setMetadataPromise(Promise.resolve());
      runtime.dispose();
      expect(runtime.contentLoad.getInitPromise()).toBeNull();
      expect(runtime.contentLoad.getMetadataPromise()).toBeNull();
    });

    it("two runtimes are independent", () => {
      const r1 = createPluginRuntime();
      const r2 = createPluginRuntime();
      const p = Promise.resolve();
      
      r1.contentLoad.setMetadataPromise(p);
      expect(r1.contentLoad.getMetadataPromise()).toBe(p);
      expect(r2.contentLoad.getMetadataPromise()).toBeNull();
    });
  });

  describe("override injection and dispose delegation", () => {
    it("delegates dispose and allows overrides with correct ordering", () => {
      const order: string[] = [];

      const statusSurfaceDispose = vi.fn(() => { order.push("statusSurface"); });
      const settingsDispose = vi.fn(() => { order.push("settings"); });
      const contentLoadDispose = vi.fn(() => { order.push("contentLoad"); });

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
          getInitPromise: () => null,
          setInitPromise: () => {},
          getMetadataPromise: () => null,
          setMetadataPromise: () => {},
          dispose: contentLoadDispose
        }
      };
      
      const runtime = createPluginRuntime(overrides);
      expect(runtime.contentLoad).toBe(overrides.contentLoad);
      
      runtime.dispose();
      
      expect(order).toEqual(["statusSurface", "settings", "contentLoad"]);
    });
  });
});
