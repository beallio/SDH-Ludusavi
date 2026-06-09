import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("@decky/ui", () => {
  return {
    Router: {}
  };
});

import { 
  isSteamRuntimeAvailable, 
  getSteamLanguage, 
  asRecord,
  getRouterMainRunningApp,
  getRouterRunningApps,
  getGamepadMainWindow,
  getSteamClientApps,
  getAppStore,
  getAppDetailsStore,
  getCollectionStoreApps,
  registerAppLifetimeNotification,
  createBrowserView
} from "./steamRuntime";

import { Router } from "@decky/ui";

describe("steamRuntime", () => {
  beforeEach(() => {
    (globalThis as any).SteamClient = undefined;
    (globalThis as any).window = undefined;
    (globalThis as any).appStore = undefined;
    (globalThis as any).appDetailsStore = undefined;
    (globalThis as any).collectionStore = undefined;
    
    // reset Router mock
    for (const key in Router as any) {
      delete (Router as any)[key];
    }
  });

  it("asRecord handles objects", () => {
    expect(asRecord({})).toEqual({});
    expect(asRecord(null)).toBeNull();
    expect(asRecord(123)).toBeNull();
  });

  it("isSteamRuntimeAvailable handles missing SteamClient", () => {
    expect(isSteamRuntimeAvailable()).toBe(false);
  });

  it("getSteamLanguage falls back to english", () => {
    expect(getSteamLanguage()).toBe("english");
    
    (globalThis as any).SteamClient = { Settings: { Language: { GetLanguage: () => "french" } } };
    expect(getSteamLanguage()).toBe("french");
    
    (globalThis as any).SteamClient = { Settings: { Language: { GetLanguage: "not-a-function" } } };
    expect(getSteamLanguage()).toBe("english");
  });

  it("getRouterMainRunningApp handles missing or malformed values", () => {
    expect(getRouterMainRunningApp()).toBeNull();
    (Router as any).MainRunningApp = { appid: 123 };
    expect(getRouterMainRunningApp()).toEqual({ appid: 123 });
  });

  it("getRouterRunningApps validates array type", () => {
    expect(getRouterRunningApps()).toBeNull();
    (Router as any).RunningApps = { not: "array" };
    expect(getRouterRunningApps()).toBeNull();
    (Router as any).RunningApps = [1, 2];
    expect(getRouterRunningApps()).toEqual([1, 2]);
  });

  it("getGamepadMainWindow handles deep nesting and missing globals", () => {
    expect(getGamepadMainWindow()).toBeNull();
    (Router as any).WindowStore = { GamepadUIMainWindowInstance: { BrowserWindow: {} } };
    expect(getGamepadMainWindow()).toEqual({});
  });

  it("getSteamClientApps handles missing SteamClient", () => {
    expect(getSteamClientApps()).toBeNull();
    (globalThis as any).SteamClient = { Apps: {} };
    expect(getSteamClientApps()).toEqual({});
  });

  it("getAppStore handles missing globals", () => {
    expect(getAppStore()).toBeNull();
    (globalThis as any).appStore = { GetAppOverviewByAppID: () => {} };
    expect(getAppStore()).toBeDefined();
  });

  it("getAppDetailsStore handles missing globals", () => {
    expect(getAppDetailsStore()).toBeNull();
    (globalThis as any).appDetailsStore = {};
    expect(getAppDetailsStore()).toBeDefined();
  });

  it("getCollectionStoreApps validates forEach presence", () => {
    expect(getCollectionStoreApps()).toBeNull();
    (globalThis as any).collectionStore = { allGamesCollection: { allApps: [] } };
    expect(getCollectionStoreApps()).toEqual([]);
    
    (globalThis as any).collectionStore = { allGamesCollection: { allApps: {} } }; // no forEach
    expect(getCollectionStoreApps()).toBeNull();
  });

  it("registerAppLifetimeNotification requires valid unregister return", () => {
    expect(registerAppLifetimeNotification(() => {})).toBeNull();
    
    (globalThis as any).SteamClient = { GameSessions: { RegisterForAppLifetimeNotifications: () => ({ unregister: () => {} }) } };
    const reg = registerAppLifetimeNotification(() => {});
    expect(reg).toBeDefined();
    expect(typeof reg?.unregister).toBe("function");
    
    (globalThis as any).SteamClient = { GameSessions: { RegisterForAppLifetimeNotifications: () => ({ Unregister: () => {} }) } };
    const regUpper = registerAppLifetimeNotification(() => {});
    expect(regUpper).toBeDefined();
    expect(typeof regUpper?.unregister).toBe("function");
  });

  it("createBrowserView handles missing methods", () => {
    expect(createBrowserView()).toBeNull();
    (globalThis as any).SteamClient = { BrowserView: { Create: () => "view" } };
    expect(createBrowserView()).toBe("view");
  });
});
