import {
  createContext,
  useContext,
  useSyncExternalStore,
  type ReactNode
} from "react";

import {
  GameOperationHistory,
  GameStatus,
  NotificationCategory,
  NotificationSettings,
  RefreshResult,
  Settings,
  Versions,
  UpdateChannel,
  TrackingReadiness
} from "../types";
import { LudusaviLaunchCommand } from "../ludusaviLauncher";
import { normalize } from "../utils/steam";

export const defaultNotificationSettings: NotificationSettings = {
  enabled: true,
  auto_sync_progress: true,
  auto_sync_results: true,
  manual_operations: true,
  refresh_status: true,
  failures_errors: true
};

export const defaultSettings = (): Settings => ({
  auto_sync_enabled: false,
  sync_disabled_games: [],
  selected_game: "",
  notifications: { ...defaultNotificationSettings },
  update_channel: "stable",
  automatic_update_checks: true,
  debug_logging: true
});

export function normalizeNotificationSettings(
  settings?: Partial<NotificationSettings>
): NotificationSettings {
  return {
    enabled: typeof settings?.enabled === "boolean" ? settings.enabled : true,
    auto_sync_progress: typeof settings?.auto_sync_progress === "boolean" ? settings.auto_sync_progress : true,
    auto_sync_results: typeof settings?.auto_sync_results === "boolean" ? settings.auto_sync_results : true,
    manual_operations: typeof settings?.manual_operations === "boolean" ? settings.manual_operations : true,
    refresh_status: typeof settings?.refresh_status === "boolean" ? settings.refresh_status : true,
    failures_errors: typeof settings?.failures_errors === "boolean" ? settings.failures_errors : true
  };
}

export function normalizeSettings(settings: Settings): Settings {
  return {
    ...settings,
    sync_disabled_games: Array.isArray(settings.sync_disabled_games)
      ? settings.sync_disabled_games.filter(
          (name): name is string => typeof name === "string" && name.length > 0
        )
      : [],
    notifications: normalizeNotificationSettings(settings.notifications),
    update_channel: settings.update_channel === "development" ? "development" : "stable",
    automatic_update_checks: typeof settings.automatic_update_checks === "boolean" ? settings.automatic_update_checks : true,
    debug_logging: typeof settings.debug_logging === "boolean" ? settings.debug_logging : true
  };
}

export type LudusaviStateSnapshot = {
  settings: Settings | null;
  games: GameStatus[] | null;
  gameAliases: Record<string, string>;
  gameHistory: Record<string, GameOperationHistory>;
  selectedGame: string;
  installedAppIds: string | undefined;
  versions: Versions | null;
  ludusaviCommand: LudusaviLaunchCommand | null;
  trackedAppIDs: Set<string>;
  trackedNames: Set<string>;
  autoSyncNotificationsEnabled: boolean;
  notificationSettings: NotificationSettings;
  trackingReadiness: TrackingReadiness;
};

function createInitialSnapshot(): LudusaviStateSnapshot {
  return {
    settings: null,
    games: null,
    gameAliases: {},
    gameHistory: {},
    selectedGame: "",
    installedAppIds: undefined,
    versions: null,
    ludusaviCommand: null,
    trackedAppIDs: new Set<string>(),
    trackedNames: new Set<string>(),
    autoSyncNotificationsEnabled: false,
    notificationSettings: { ...defaultNotificationSettings },
    trackingReadiness: "cold"
  };
}

function buildTrackedNames(
  games: GameStatus[],
  aliases: Record<string, string>
): Set<string> {
  const names = new Set<string>();
  games.forEach((game) => names.add(normalize(game.name)));
  Object.entries(aliases).forEach(([alias, target]) => {
    names.add(normalize(alias));
    names.add(normalize(target));
  });
  return names;
}

function buildTrackedAppIDs(games: GameStatus[]): Set<string> {
  return new Set(
    games
      .map((game) => game.steam_id)
      .filter((id): id is string | number => id !== null && id !== undefined)
      .map((id) => String(id))
  );
}

export class LudusaviStateStore {
  private snapshot: LudusaviStateSnapshot = createInitialSnapshot();
  private listeners = new Set<() => void>();

  getSnapshot = () => this.snapshot;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  applySettings(settings: Settings) {
    const normalized = normalizeSettings(settings);
    this.commit({
      settings: normalized,
      autoSyncNotificationsEnabled: normalized.auto_sync_enabled,
      notificationSettings: normalized.notifications
    });
    return normalized;
  }

  patchSettings(partial: Partial<Settings>) {
    const next = { ...(this.snapshot.settings ?? defaultSettings()), ...partial };
    this.applySettings(next);
  }

  setDisplayedGame(selectedGame: string) {
    this.commit({ selectedGame });
  }

  hydrateDisplayedGame(selectedGame: string) {
    if (this.snapshot.selectedGame === "") {
      this.commit({ selectedGame });
    }
  }

  setAutoSyncEnabled(enabled: boolean) {
    this.patchSettings({ auto_sync_enabled: enabled });
  }

  setGameSyncEnabled(gameName: string, enabled: boolean) {
    const disabledGames = new Set(
      this.snapshot.settings?.sync_disabled_games ?? []
    );
    if (enabled) {
      disabledGames.delete(gameName);
    } else {
      disabledGames.add(gameName);
    }
    this.patchSettings({
      sync_disabled_games: [...disabledGames].sort()
    });
  }

  setDebugLogging(enabled: boolean) {
    this.patchSettings({ debug_logging: enabled });
  }

  setNotificationSettings(notifications: NotificationSettings) {
    this.patchSettings({ notifications });
  }

  setUpdateChannel(channel: UpdateChannel) {
    this.patchSettings({ update_channel: channel });
  }

  setAutomaticUpdateChecks(enabled: boolean) {
    this.patchSettings({ automatic_update_checks: enabled });
  }

  setGameHistory(history: Record<string, GameOperationHistory>) {
    this.commit({ gameHistory: history });
  }

  applyRefreshResult(result: RefreshResult) {
    const aliases = result.aliases || {};
    this.commit({
      games: result.games,
      gameAliases: aliases,
      gameHistory: result.history ?? {},
      trackedAppIDs: buildTrackedAppIDs(result.games),
      trackedNames: buildTrackedNames(result.games, aliases),
      trackingReadiness: "ready"
    });
  }

  markTrackingFailed() {
    this.commit({ trackingReadiness: "failed" });
  }

  setInstalledAppIds(installedAppIds: string | undefined) {
    this.commit({ installedAppIds });
  }

  setVersions(versions: Versions) {
    this.commit({ versions });
  }

  setLudusaviCommand(ludusaviCommand: LudusaviLaunchCommand | null) {
    this.commit({ ludusaviCommand });
  }

  shouldShowNotification(category: NotificationCategory): boolean {
    return this.snapshot.notificationSettings.enabled && this.snapshot.notificationSettings[category];
  }

  isTracked(
    name: string,
    appID: string,
    onMatch?: (reason: "appId" | "exact" | "substring", detail: string) => void,
    onMiss?: (normalizedInput: string) => void
  ): boolean {
    if (this.snapshot.trackedAppIDs.has(appID)) {
      onMatch?.("appId", appID);
      return true;
    }

    const normalizedInput = normalize(name);
    if (this.snapshot.trackedNames.has(normalizedInput)) {
      onMatch?.("exact", normalizedInput);
      return true;
    }

    const candidates: string[] = [];
    for (const trackedName of this.snapshot.trackedNames) {
      if (
        (normalizedInput.length > 4 && trackedName.includes(normalizedInput)) ||
        (trackedName.length > 4 && normalizedInput.includes(trackedName))
      ) {
        candidates.push(trackedName);
      }
    }

    if (candidates.length === 1) {
      onMatch?.("substring", `${normalizedInput} <-> ${candidates[0]}`);
      return true;
    }

    onMiss?.(normalizedInput);
    return false;
  }

  resolveCanonicalGameName(name: string, appID: string): string | null {
    const games = this.snapshot.games ?? [];

    const appIDMatch = games.find(
      (game) => game.steam_id !== null
        && game.steam_id !== undefined
        && String(game.steam_id) === appID
    );
    if (appIDMatch) {
      return appIDMatch.name;
    }

    const aliasTarget = this.snapshot.gameAliases[name];
    if (aliasTarget !== undefined) {
      const aliasMatch = games.find((game) => game.name === aliasTarget);
      if (aliasMatch) {
        return aliasMatch.name;
      }
    }

    const normalizedInput = normalize(name);
    const exactMatch = games.find(
      (game) => normalize(game.name) === normalizedInput
    );
    if (exactMatch) {
      return exactMatch.name;
    }

    const candidates = games.filter((game) => {
      const normalizedTarget = normalize(game.name);
      const isSubstring = normalizedInput.includes(normalizedTarget)
        || normalizedTarget.includes(normalizedInput);
      return isSubstring
        && fuzzyMatchAllowed(normalizedInput, normalizedTarget, game.configured);
    });

    return candidates.length === 1 ? candidates[0].name : null;
  }

  isGameSyncDisabled(name: string, appID: string): boolean {
    const canonicalName = this.resolveCanonicalGameName(name, appID);
    if (canonicalName === null) {
      return false;
    }
    return (this.snapshot.settings?.sync_disabled_games ?? []).includes(canonicalName);
  }

  shouldPublishAutoSyncStatusBeforeRpc(tracked: boolean): boolean {
    const trackingCacheEmpty =
      this.snapshot.trackedAppIDs.size === 0 && this.snapshot.trackedNames.size === 0;
    return (
      (this.snapshot.settings === null || this.snapshot.autoSyncNotificationsEnabled) &&
      (tracked || trackingCacheEmpty)
    );
  }

  private commit(patch: Partial<LudusaviStateSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }
}

function fuzzyMatchAllowed(
  normalizedInput: string,
  normalizedTarget: string,
  configured: boolean
): boolean {
  if (normalizedInput.length > 4 && normalizedTarget.length > 4) {
    return true;
  }
  if (!configured || normalizedTarget.length !== 4) {
    return false;
  }
  if (!normalizedInput.startsWith(normalizedTarget)) {
    return false;
  }
  if (normalizedInput.length === normalizedTarget.length) {
    return true;
  }
  return [" ", ".", "-"].includes(normalizedInput[normalizedTarget.length]);
}

export function createLudusaviStateStore() {
  return new LudusaviStateStore();
}

const LudusaviStateContext = createContext<LudusaviStateStore | null>(null);

export function LudusaviStateProvider({
  children,
  store
}: {
  children: ReactNode;
  store: LudusaviStateStore;
}) {
  return (
    <LudusaviStateContext.Provider value={store}>
      {children}
    </LudusaviStateContext.Provider>
  );
}

export function useLudusaviStateStore() {
  const store = useContext(LudusaviStateContext);
  if (!store) {
    throw new Error("useLudusaviStateStore must be used within LudusaviStateProvider");
  }
  return store;
}

export function useLudusaviState() {
  const store = useLudusaviStateStore();
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
