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
  Versions
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
  selected_game: "",
  notifications: { ...defaultNotificationSettings }
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
    notifications: normalizeNotificationSettings(settings.notifications)
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
    notificationSettings: { ...defaultNotificationSettings }
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
      selectedGame: normalized.selected_game,
      autoSyncNotificationsEnabled: normalized.auto_sync_enabled,
      notificationSettings: normalized.notifications
    });
    return normalized;
  }

  setSelectedGame(selectedGame: string) {
    this.commit({ selectedGame });
  }

  syncSelectedGameCache(selectedGame: string) {
    const settings = this.snapshot.settings
      ? { ...this.snapshot.settings, selected_game: selectedGame }
      : { ...defaultSettings(), selected_game: selectedGame };
    this.commit({ settings, selectedGame });
  }

  setAutoSyncEnabled(enabled: boolean) {
    const settings = {
      ...(this.snapshot.settings ?? defaultSettings()),
      auto_sync_enabled: enabled
    };
    this.commit({
      settings,
      autoSyncNotificationsEnabled: enabled
    });
  }

  setNotificationSettings(notifications: NotificationSettings) {
    const normalizedNotifications = normalizeNotificationSettings(notifications);
    const settings = {
      ...(this.snapshot.settings ?? defaultSettings()),
      notifications: normalizedNotifications
    };
    this.commit({
      settings,
      notificationSettings: normalizedNotifications
    });
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
      trackedNames: buildTrackedNames(result.games, aliases)
    });
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

  isTracked(name: string, appID: string): boolean {
    if (this.snapshot.trackedAppIDs.has(appID)) {
      return true;
    }

    const normalizedInput = normalize(name);
    if (this.snapshot.trackedNames.has(normalizedInput)) {
      return true;
    }

    for (const trackedName of Array.from(this.snapshot.trackedNames)) {
      if (
        (normalizedInput.length > 4 && trackedName.includes(normalizedInput)) ||
        (trackedName.length > 4 && normalizedInput.includes(trackedName))
      ) {
        return true;
      }
    }

    return false;
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
