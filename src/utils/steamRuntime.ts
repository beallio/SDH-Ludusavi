import { Router } from "@decky/ui";

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

export function getSteamClient(): unknown {
  try {
    return (globalThis as any).SteamClient ?? (window as any).SteamClient;
  } catch {
    return null;
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

export function getGamepadUIMainWindowInstance(): unknown | null {
  try {
    return (Router as any).WindowStore?.GamepadUIMainWindowInstance ?? null;
  } catch {
    return null;
  }
}

export function getSteamClientApps(): unknown {
  try {
    const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    return client?.Apps ?? null;
  } catch {
    return null;
  }
}

export function getAppStore(): unknown {
  try {
    return (globalThis as any).appStore ?? (window as any).appStore ?? null;
  } catch {
    return null;
  }
}

export function getAppDetailsStore(): unknown {
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

export function registerAppLifetimeNotification(callback: (app: unknown) => void): { unregister: () => void } | null {
  try {
    const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    if (client?.GameSessions?.RegisterForAppLifetimeNotifications) {
      const reg = client.GameSessions.RegisterForAppLifetimeNotifications(callback);
      if (reg) {
        if (typeof reg.unregister === "function") {
          return { unregister: reg.unregister.bind(reg) };
        } else if (typeof reg.Unregister === "function") {
          return { unregister: reg.Unregister.bind(reg) };
        } else if (typeof reg === "function") {
          return { unregister: reg };
        }
      }
    }
  } catch {
    // ignore
  }
  return null;
}

export function createBrowserView(): unknown {
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
