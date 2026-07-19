import { isRpcStatus } from "../utils/rpc";
import { SingleDropdownOption } from "@decky/ui";

import {
  setAutomaticUpdateChecksCall,
  setAutoSyncEnabled,
  setGameSyncEnabledCall,
  setNotificationSettings,
  setSelectedGameCall,
  setUpdateChannelCall,
  setDebugLoggingCall
} from "../api/ludusaviRpc";
import {
  defaultNotificationSettings,
  type LudusaviStateStore
} from "../state/ludusaviState";
import type {
  NotificationSettings,
  Settings,
  UpdateChannel
} from "../types";
import { log, logUiEvent, type LogFields, type LogLevel } from "../utils/logging";

type NotifyFailure = (title: string, body: string) => void;

type SettingsMutationControllerOptions = {
  ludusaviStore: LudusaviStateStore;
  notifyFailure: NotifyFailure;
};

export type SettingsMutationRuntime = ReturnType<typeof createSettingsMutationRuntime>;

export function createSettingsMutationRuntime() {
  const settingsQueue: (() => Promise<void>)[] = [];
  let settingsProcessing = false;
  let mutationGeneration = 0;
  let autoSyncSeq = 0;
  const gameSyncSeq = new Map<string, number>();
  let notificationSeq = 0;
  let selectedGameSeq = 0;
  let updateChannelSeq = 0;
  let automaticUpdateChecksSeq = 0;
  let debugLoggingSeq = 0;
  let lastPersistedAutoSync: boolean | null = null;
  let lastPersistedSyncDisabledGames: string[] | null = null;
  let lastPersistedNotifications: NotificationSettings | null = null;
  let lastPersistedUpdateChannel: UpdateChannel | null = null;
  let lastPersistedAutomaticUpdateChecks: boolean | null = null;
  let lastPersistedDebugLogging: boolean | null = null;
  let lastPersistedSelectedGame: string | null = null;
  let lastQueuedSelectedGame: string | null = null;
  let activeLudusaviStore: LudusaviStateStore | null = null;
  let activeFailureNotifier: NotifyFailure | null = null;

  async function processSettingsQueue() {
    if (settingsProcessing) return;
    settingsProcessing = true;
    try {
      while (settingsQueue.length > 0) {
        const task = settingsQueue.shift();
        if (task) {
          try {
            await task();
          } catch (err) {
            log("error", `Settings update failed in queue: ${err}`);
            if (activeLudusaviStore && activeFailureNotifier) {
              activeFailureNotifier(
                "Settings Update Failed",
                err instanceof Error ? err.message : String(err)
              );
            }
          }
        }
      }
    } finally {
      settingsProcessing = false;
    }
  }

  function enqueueSettingsUpdate(task: () => Promise<void>) {
    settingsQueue.push(task);
    logUiEvent("settings_update_queued", { queue_depth: settingsQueue.length }, "debug", "ui_settings");
    void processSettingsQueue();
  }

  function withTimeout<T>(promise: Promise<T>, timeoutMs: number, errorMessage: string): Promise<T> {
    let timeoutId: number;
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = window.setTimeout(() => {
        reject(new Error(errorMessage));
      }, timeoutMs);
    });
    return Promise.race([promise, timeoutPromise]).finally(() => {
      window.clearTimeout(timeoutId);
    });
  }

  function applySettings(store: LudusaviStateStore, nextSettings: Settings) {
    activeLudusaviStore = store;
    const normalized = store.applySettings(nextSettings);
    if (normalized.auto_sync_enabled !== undefined) {
      lastPersistedAutoSync = normalized.auto_sync_enabled;
    }
    lastPersistedSyncDisabledGames = normalized.sync_disabled_games;
    if (normalized.notifications) {
      lastPersistedNotifications = normalized.notifications;
    }
    if (normalized.selected_game !== undefined) {
      lastPersistedSelectedGame = normalized.selected_game;
    }
    if (normalized.update_channel !== undefined) {
      lastPersistedUpdateChannel = normalized.update_channel;
    }
    if (normalized.automatic_update_checks !== undefined) {
      lastPersistedAutomaticUpdateChecks = normalized.automatic_update_checks;
    }
    if (normalized.debug_logging !== undefined) {
      lastPersistedDebugLogging = normalized.debug_logging;
    }
    return normalized;
  }

  function syncLastQueuedSelectedGame(selectedGame: string) {
    lastQueuedSelectedGame = selectedGame;
  }

  function clearLastQueuedSelectedGame() {
    lastQueuedSelectedGame = null;
  }

  function setActiveStore(store: LudusaviStateStore, notifyFailure: NotifyFailure) {
    activeLudusaviStore = store;
    activeFailureNotifier = notifyFailure;
  }

  function createController({
    ludusaviStore,
    notifyFailure
  }: SettingsMutationControllerOptions) {
    setActiveStore(ludusaviStore, notifyFailure);

    const logSettingsEvent = (
      event: string,
      setting: string,
      fields: LogFields = {},
      level: LogLevel = "info",
      gameName?: string,
    ) => {
      logUiEvent(event, { setting, ...fields }, level, "ui_settings", gameName);
    };

    const reportSettingsFailure = (error: unknown) => {
      notifyFailure(
        "SDH-Ludusavi settings failed",
        error instanceof Error ? error.message : String(error)
      );
    };


    type MutateOptions<T, V extends import("../utils/logging").LogFieldValue> = {
      updateSeq: number;
      readSeq: () => number;
      settingKey: string;
      settingValue?: V;
      settingPreviousValue?: V;
      gameName?: string;
      logExecute: string;
      logLateResolution: string;
      logLateFailure: string;
      logError: string;
      timeoutMessage: string;
      fallbackValue: V;
      logFallbackValue?: V;
      optimisticUpdate: () => void;
      rpcCall: () => Promise<T | import("../types").RpcStatus>;
      applyResult: (res: T, isLatestGeneration: boolean) => void;
      rollbackUpdate: (fallback: V) => void;
      getPersistedValue: (res: T) => V | string[];
    };

    const mutateSetting = <T extends Settings, V extends import("../utils/logging").LogFieldValue>({
      updateSeq,
      readSeq,
      settingKey,
      settingValue,
      settingPreviousValue,
      gameName,
      logExecute,
      logLateResolution,
      logLateFailure,
      logError,
      timeoutMessage,
      fallbackValue,
      logFallbackValue,
      optimisticUpdate,
      rpcCall,
      applyResult,
      rollbackUpdate,
      getPersistedValue
    }: MutateOptions<T, V>) => {
      const logFields: LogFields = { sequence: updateSeq };
      if (settingValue !== undefined) logFields.value = settingValue;
      if (settingPreviousValue !== undefined) logFields.previous_value = settingPreviousValue;

      logSettingsEvent("settings_change_requested", settingKey, logFields, gameName ? "info" : undefined, gameName);
      optimisticUpdate();

      mutationGeneration++;
      const startedGeneration = mutationGeneration;

      enqueueSettingsUpdate(async () => {
        log("info", logExecute);
        let awaitFailed = false;
        const originalPromise = rpcCall().then((res) => {
          if (awaitFailed) {
            log("info", logLateResolution);
            if (updateSeq === readSeq() && !isRpcStatus(res)) {
              applyResult(res as T, startedGeneration >= mutationGeneration);
            }
          }
          return res;
        }).catch((err) => {
          if (awaitFailed) {
            log("error", `${logLateFailure}: ${err}`);
          }
          throw err;
        });

        try {
          const result = await withTimeout(originalPromise, 10000, timeoutMessage);
          if (isRpcStatus(result)) {
            throw new Error(result.message || result.status);
          }
          if (updateSeq === readSeq()) {
            applyResult(result as T, startedGeneration >= mutationGeneration);
            const persistedValue = getPersistedValue(result as T);
            logSettingsEvent("settings_change_persisted", settingKey, {
              sequence: updateSeq,
              value: Array.isArray(persistedValue)
                ? JSON.stringify(persistedValue)
                : persistedValue,
            }, gameName ? "info" : undefined, gameName);
          } else {
            logSettingsEvent("settings_change_superseded", settingKey, {
              sequence: updateSeq,
            }, "debug", gameName);
          }
        } catch (error) {
          awaitFailed = true;
          log("error", `${logError}: ${error}`);
          if (updateSeq === readSeq()) {
            rollbackUpdate(fallbackValue);
            logSettingsEvent("settings_change_rolled_back", settingKey, {
              fallback: logFallbackValue !== undefined ? logFallbackValue : fallbackValue,
              message: error instanceof Error ? error.message : String(error),
              sequence: updateSeq,
            }, "error", gameName);
            reportSettingsFailure(error);
          }
        }
      });
    };

    const toggleAutoSync = (enabled: boolean) => {
      mutateSetting<Settings, boolean>({
        updateSeq: ++autoSyncSeq,
        readSeq: () => autoSyncSeq,
        settingKey: "auto_sync_enabled",
        settingValue: enabled,
        logExecute: `Executing toggle auto-sync to ${enabled}`,
        logLateResolution: `Late resolution of setAutoSyncEnabled to ${enabled} succeeded`,
        logLateFailure: `Late failure of setAutoSyncEnabled to ${enabled}`,
        logError: `Failed to toggle auto-sync`,
        timeoutMessage: "Setting auto-sync timed out",
        fallbackValue: lastPersistedAutoSync ?? false,
        optimisticUpdate: () => ludusaviStore.setAutoSyncEnabled(enabled),
        rpcCall: () => setAutoSyncEnabled(enabled),
        applyResult: (res, isLatest) => {
          if (isLatest) applySettings(ludusaviStore, res);
          else {
            if (res.auto_sync_enabled !== undefined) lastPersistedAutoSync = res.auto_sync_enabled;
            ludusaviStore.patchSettings({ auto_sync_enabled: res.auto_sync_enabled });
          }
        },
        rollbackUpdate: (fallback) => ludusaviStore.setAutoSyncEnabled(fallback),
        getPersistedValue: (res) => res.auto_sync_enabled
      });
    };

    const toggleGameSync = (gameName: string, enabled: boolean) => {
      const updateSeq = (gameSyncSeq.get(gameName) ?? 0) + 1;
      gameSyncSeq.set(gameName, updateSeq);
      mutateSetting<Settings, boolean>({
        updateSeq,
        readSeq: () => gameSyncSeq.get(gameName) ?? 0,
        settingKey: "sync_disabled_games",
        settingValue: enabled,
        gameName,
        logExecute: `Executing game sync toggle for ${gameName} to ${enabled}`,
        logLateResolution: `Late resolution of setGameSyncEnabledCall for ${gameName} to ${enabled} succeeded`,
        logLateFailure: `Late failure of setGameSyncEnabledCall for ${gameName} to ${enabled}`,
        logError: `Failed to toggle game sync for ${gameName}`,
        timeoutMessage: "Setting game sync timed out",
        fallbackValue: !(lastPersistedSyncDisabledGames ?? []).includes(gameName),
        optimisticUpdate: () => ludusaviStore.setGameSyncEnabled(gameName, enabled),
        rpcCall: async () => {
          const res = await setGameSyncEnabledCall(gameName, enabled);
          if (!isRpcStatus(res)) {
            lastPersistedSyncDisabledGames = res.sync_disabled_games;
          }
          return res;
        },
        applyResult: (res, isLatest) => {
          if (isLatest) {
            applySettings(ludusaviStore, res);
          } else {
            ludusaviStore.setGameSyncEnabled(
              gameName,
              !res.sync_disabled_games.includes(gameName),
            );
          }
        },
        rollbackUpdate: () =>
          ludusaviStore.setGameSyncEnabled(
            gameName,
            !(lastPersistedSyncDisabledGames ?? []).includes(gameName),
          ),
        getPersistedValue: (res) => res.sync_disabled_games,
      });
    };

    const toggleDebugLogging = (enabled: boolean) => {
      mutateSetting<Settings, boolean>({
        updateSeq: ++debugLoggingSeq,
        readSeq: () => debugLoggingSeq,
        settingKey: "debug_logging",
        settingValue: enabled,
        logExecute: `Executing toggle debug logging to ${enabled}`,
        logLateResolution: `Late resolution of setDebugLogging to ${enabled} succeeded`,
        logLateFailure: `Late failure of setDebugLogging to ${enabled}`,
        logError: `Failed to toggle debug logging`,
        timeoutMessage: "Setting debug logging timed out",
        fallbackValue: lastPersistedDebugLogging ?? true,
        optimisticUpdate: () => ludusaviStore.setDebugLogging(enabled),
        rpcCall: () => setDebugLoggingCall(enabled),
        applyResult: (res, isLatest) => {
          if (isLatest) applySettings(ludusaviStore, res);
          else {
            if (res.debug_logging !== undefined) lastPersistedDebugLogging = res.debug_logging;
            ludusaviStore.patchSettings({ debug_logging: res.debug_logging });
          }
        },
        rollbackUpdate: (fallback) => ludusaviStore.setDebugLogging(fallback),
        getPersistedValue: (res) => res.debug_logging
      });
    };

    const toggleNotificationSetting = (key: keyof NotificationSettings, enabled: boolean) => {
      const previousNotifications = ludusaviStore.getSnapshot().settings?.notifications ?? defaultNotificationSettings;
      const nextNotifications = { ...previousNotifications, [key]: enabled };
      mutateSetting<Settings, boolean>({
        updateSeq: ++notificationSeq,
        readSeq: () => notificationSeq,
        settingKey: `notifications.${String(key)}`,
        settingValue: enabled,
        logExecute: `Executing toggle notification setting ${String(key)} to ${enabled}`,
        logLateResolution: `Late resolution of setNotificationSettings to ${JSON.stringify(nextNotifications)} succeeded`,
        logLateFailure: `Late failure of setNotificationSettings to ${JSON.stringify(nextNotifications)}`,
        logError: `Failed to update notification settings`,
        timeoutMessage: "Setting notifications timed out",
        fallbackValue: (lastPersistedNotifications ?? defaultNotificationSettings)[key],
        logFallbackValue: (lastPersistedNotifications ?? defaultNotificationSettings)[key],
        optimisticUpdate: () => ludusaviStore.setNotificationSettings(nextNotifications),
        rpcCall: () => setNotificationSettings(nextNotifications),
        applyResult: (res, isLatest) => {
          if (isLatest) applySettings(ludusaviStore, res);
          else {
            if (res.notifications) lastPersistedNotifications = res.notifications;
            ludusaviStore.patchSettings({ notifications: res.notifications });
          }
        },
        rollbackUpdate: (fallback) => {
          const prev = ludusaviStore.getSnapshot().settings?.notifications ?? defaultNotificationSettings;
          ludusaviStore.setNotificationSettings({ ...prev, [key]: fallback });
        },
        getPersistedValue: (res) => res.notifications?.[key] ?? false
      });
    };

    const toggleUpdateChannel = (enabled: boolean) => {
      const channel = enabled ? "development" : "stable";
      mutateSetting<Settings, UpdateChannel>({
        updateSeq: ++updateChannelSeq,
        readSeq: () => updateChannelSeq,
        settingKey: "update_channel",
        settingValue: channel,
        logExecute: `Executing toggle update channel to ${channel}`,
        logLateResolution: `Late resolution of setUpdateChannel to ${channel} succeeded`,
        logLateFailure: `Late failure of setUpdateChannel to ${channel}`,
        logError: `Failed to toggle update channel`,
        timeoutMessage: "Setting update channel timed out",
        fallbackValue: lastPersistedUpdateChannel ?? "stable",
        optimisticUpdate: () => ludusaviStore.setUpdateChannel(channel),
        rpcCall: () => setUpdateChannelCall(channel),
        applyResult: (res, isLatest) => {
          if (isLatest) applySettings(ludusaviStore, res);
          else {
            if (res.update_channel !== undefined) lastPersistedUpdateChannel = res.update_channel;
            ludusaviStore.patchSettings({ update_channel: res.update_channel });
          }
        },
        rollbackUpdate: (fallback) => ludusaviStore.setUpdateChannel(fallback),
        getPersistedValue: (res) => res.update_channel
      });
    };

    const toggleAutomaticUpdateChecks = (enabled: boolean) => {
      mutateSetting<Settings, boolean>({
        updateSeq: ++automaticUpdateChecksSeq,
        readSeq: () => automaticUpdateChecksSeq,
        settingKey: "automatic_update_checks",
        settingValue: enabled,
        logExecute: `Executing toggle automatic update checks to ${enabled}`,
        logLateResolution: `Late resolution of setAutomaticUpdateChecks to ${enabled} succeeded`,
        logLateFailure: `Late failure of setAutomaticUpdateChecks to ${enabled}`,
        logError: `Failed to toggle automatic checks`,
        timeoutMessage: "Setting automatic checks timed out",
        fallbackValue: lastPersistedAutomaticUpdateChecks ?? true,
        optimisticUpdate: () => ludusaviStore.setAutomaticUpdateChecks(enabled),
        rpcCall: () => setAutomaticUpdateChecksCall(enabled),
        applyResult: (res, isLatest) => {
          if (isLatest) applySettings(ludusaviStore, res);
          else {
            if (res.automatic_update_checks !== undefined) lastPersistedAutomaticUpdateChecks = res.automatic_update_checks;
            ludusaviStore.patchSettings({ automatic_update_checks: res.automatic_update_checks });
          }
        },
        rollbackUpdate: (fallback) => ludusaviStore.setAutomaticUpdateChecks(fallback),
        getPersistedValue: (res) => res.automatic_update_checks
      });
    };

    const onGameChange = (data: SingleDropdownOption | string | null | undefined) => {
      const value = (typeof data === "object" && data !== null) ? data.data : data;
      if (typeof value !== "string" || value.trim() === "") {
        logSettingsEvent("settings_change_rejected", "selected_game", {
          reason: "invalid_value",
          value: String(value),
        }, "warning");
        return;
      }
      const lastQueued = lastQueuedSelectedGame ?? ludusaviStore.getSnapshot().selectedGame;
      if (value === lastQueued) {
        logSettingsEvent("settings_change_skipped", "selected_game", {
          reason: "already_selected",
          value,
        }, "debug", value);
        return;
      }
      const previousValue = lastQueued;
      lastQueuedSelectedGame = value;

      mutateSetting<Settings, string>({
        updateSeq: ++selectedGameSeq,
        readSeq: () => selectedGameSeq,
        settingKey: "selected_game",
        settingValue: value,
        settingPreviousValue: previousValue,
        gameName: value,
        logExecute: `Executing selected game change to ${value}`,
        logLateResolution: `Late resolution of setSelectedGameCall to ${value} succeeded`,
        logLateFailure: `Late failure of setSelectedGameCall to ${value}`,
        logError: `Failed to persist selected game`,
        timeoutMessage: "Selecting game timed out",
        fallbackValue: lastPersistedSelectedGame ?? "",
        optimisticUpdate: () => ludusaviStore.setSelectedGame(value),
        rpcCall: () => setSelectedGameCall(value),
        applyResult: (res, isLatest) => {
          if (isLatest) applySettings(ludusaviStore, res);
          else {
            if (res.selected_game !== undefined) lastPersistedSelectedGame = res.selected_game;
            ludusaviStore.patchSettings({ selected_game: res.selected_game });
          }
        },
        rollbackUpdate: (fallback) => {
          ludusaviStore.setSelectedGame(fallback);
          lastQueuedSelectedGame = fallback;
        },
        getPersistedValue: (res) => res.selected_game
      });
    };

    return {
      onGameChange,
      toggleAutoSync,
      toggleGameSync,
      toggleAutomaticUpdateChecks,
      toggleNotificationSetting,
      toggleUpdateChannel,
      toggleDebugLogging
    };
  }

  function dispose() {
    settingsQueue.length = 0;
    settingsProcessing = false;
    mutationGeneration = 0;
    autoSyncSeq = 0;
    gameSyncSeq.clear();
    notificationSeq = 0;
    selectedGameSeq = 0;
    updateChannelSeq = 0;
    automaticUpdateChecksSeq = 0;
    debugLoggingSeq = 0;
    lastPersistedAutoSync = null;
    lastPersistedSyncDisabledGames = null;
    lastPersistedNotifications = null;
    lastPersistedUpdateChannel = null;
    lastPersistedAutomaticUpdateChecks = null;
    lastPersistedDebugLogging = null;
    lastPersistedSelectedGame = null;
    lastQueuedSelectedGame = null;
    activeFailureNotifier = null;
    activeLudusaviStore = null;
  }

  return {
    applySettings,
    syncLastQueuedSelectedGame,
    clearLastQueuedSelectedGame,
    setActiveStore,
    createController,
    dispose
  };
}
