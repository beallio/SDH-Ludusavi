from pathlib import Path

# Create src/utils/steamRuntime.ts
runtime_ts_path = Path("src/utils/steamRuntime.ts")
runtime_ts_content = """import { Router } from "@decky/ui";

export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
}

export function isSteamRuntimeAvailable(): boolean {
  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    return typeof steamClient !== "undefined" && steamClient !== null;
  } catch {
    return false;
  }
}

export function getSteamLanguage(): string {
  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    if (steamClient?.Settings?.Language?.GetLanguage) {
      const lang = steamClient.Settings.Language.GetLanguage();
      if (typeof lang === "string" && lang) {
        return lang;
      }
    }
  } catch {
    // ignore
  }
  return "english";
}

export function getRouterMainRunningApp(): unknown | null {
  try {
    return (Router as any).MainRunningApp ?? null;
  } catch {
    return null;
  }
}

export function getRouterRunningApps(): unknown[] | null {
  try {
    const apps = (Router as any).RunningApps;
    return Array.isArray(apps) ? apps : null;
  } catch {
    return null;
  }
}

export function getGamepadMainWindow(): Window | null {
  try {
    return (Router as any).WindowStore?.GamepadUIMainWindowInstance?.BrowserWindow ?? null;
  } catch {
    return null;
  }
}

export function getSteamClientApps(): any {
  try {
    const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    return client?.Apps ?? null;
  } catch {
    return null;
  }
}

export function getAppStore(): any {
  try {
    return (globalThis as any).appStore ?? (window as any).appStore ?? null;
  } catch {
    return null;
  }
}

export function getAppDetailsStore(): any {
  try {
    return (globalThis as any).appDetailsStore ?? (window as any).appDetailsStore ?? null;
  } catch {
    return null;
  }
}

export function getCollectionStoreApps(): unknown[] | null {
  try {
    const store = (globalThis as any).collectionStore ?? (window as any).collectionStore;
    const apps = store?.allGamesCollection?.allApps;
    if (apps && typeof apps.forEach === "function") {
      // It might be a Map or Set or Array, convert to Array to be safe, or just return as is if it has forEach
      return apps;
    }
    return null;
  } catch {
    return null;
  }
}

export function registerAppLifetimeNotification(callback: (app: any) => void): { unregister: () => void } | null {
  try {
    const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    if (client?.GameSessions?.RegisterForAppLifetimeNotifications) {
      const reg = client.GameSessions.RegisterForAppLifetimeNotifications(callback);
      if (reg && typeof reg.unregister === "function") {
        return { unregister: reg.unregister.bind(reg) };
      }
    }
  } catch {
    // ignore
  }
  return null;
}

export function createBrowserView(): any {
  try {
    const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    if (client?.BrowserView?.Create) {
      return client.BrowserView.Create();
    }
  } catch {
    // ignore
  }
  return null;
}
"""
runtime_ts_path.write_text(runtime_ts_content)

# Create src/utils/steamRuntime.test.ts
test_ts_path = Path("src/utils/steamRuntime.test.ts")
test_ts_content = """import { describe, it, expect, beforeEach } from "vitest";
import { isSteamRuntimeAvailable, getSteamLanguage, asRecord } from "./steamRuntime";

describe("steamRuntime", () => {
  beforeEach(() => {
    (globalThis as any).SteamClient = undefined;
    (globalThis as any).window = undefined;
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
  });
});
"""
test_ts_path.write_text(test_ts_content)

print("Created steamRuntime.ts and steamRuntime.test.ts")
