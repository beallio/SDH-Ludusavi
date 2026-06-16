import { isRpcStatus } from "../utils/rpc";
import { SingleDropdownOption } from "@decky/ui";

import {
  setAutomaticUpdateChecksCall,
  setAutoSyncEnabled,
  setNotificationSettings,
  setSelectedGameCall,
  setUpdateChannelCall
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

type MountedRef = { current: boolean };
type NotifyFailure = (title: string, body: string) => void;

type SettingsMutationControllerOptions = {
  ludusaviStore: LudusaviStateStore;
  isMounted?: MountedRef;
  setBusyLabel?: (label: string | null) => void;
  notifyFailure: NotifyFailure;
};

export type SettingsMutationRuntime = ReturnType<typeof createSettingsMutationRuntime>;

export function createSettingsMutationRuntime() {
  const settingsQueue: (() => Promise<void>)[] = [];
  let settingsProcessing = false;
  let autoSyncSeq = 0;
  let notificationSeq = 0;
  let selectedGameSeq = 0;
  let updateChannelSeq = 0;
  let automaticUpdateChecksSeq = 0;
  let lastPersistedAutoSync: boolean | null = null;
  let lastPersistedNotifications: NotificationSettings | null = null;
  let lastPersistedUpdateChannel: UpdateChannel | null = null;
  let lastPersistedAutomaticUpdateChecks: boolean | null = null;
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


    type MutateOptions<T, V> = {
      updateSeq: number;
      readSeq: () => number;
      settingKey: string;
      settingValue?: any;
      settingPreviousValue?: any;
      gameName?: string;
      logExecute: string;
      logLateResolution: string;
      logLateFailure: string;
      logError: string;
      timeoutMessage: string;
      fallbackValue: V;
      logFallbackValue?: any;
      optimisticUpdate: () => void;
      rpcCall: () => Promise<T | import("../types").RpcStatus>;
      applyResult: (res: T) => void;
      rollbackUpdate: (fallback: V) => void;
      getPersistedValue: (res: T) => any;
    };

    const mutateSetting = <T extends Settings, V>({
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

      enqueueSettingsUpdate(async () => {
        log("info", logExecute);
        let awaitFailed = false;
        const originalPromise = rpcCall().then((res) => {
          if (awaitFailed) {
            log("info", logLateResolution);
            if (updateSeq === readSeq() && !isRpcStatus(res)) {
              applyResult(res as T);
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
            applyResult(result as T);
            logSettingsEvent("settings_change_persisted", settingKey, {
              sequence: updateSeq,
              value: getPersistedValue(result as T),
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
        applyResult: (res) => applySettings(ludusaviStore, res),
        rollbackUpdate: (fallback) => ludusaviStore.setAutoSyncEnabled(fallback),
        getPersistedValue: (res) => res.auto_sync_enabled
      });
    };

    const toggleNotificationSetting = (key: keyof NotificationSettings, enabled: boolean) => {
      const previousNotifications = ludusaviStore.getSnapshot().settings?.notifications ?? defaultNotificationSettings;
      const nextNotifications = { ...previousNotifications, [key]: enabled };
      mutateSetting<Settings, NotificationSettings>({
        updateSeq: ++notificationSeq,
        readSeq: () => notificationSeq,
        settingKey: `notifications.${String(key)}`,
        settingValue: enabled,
        logExecute: `Executing toggle notification setting ${String(key)} to ${enabled}`,
        logLateResolution: `Late resolution of setNotificationSettings to ${JSON.stringify(nextNotifications)} succeeded`,
        logLateFailure: `Late failure of setNotificationSettings to ${JSON.stringify(nextNotifications)}`,
        logError: `Failed to update notification settings`,
        timeoutMessage: "Setting notifications timed out",
        fallbackValue: lastPersistedNotifications ?? defaultNotificationSettings,
        logFallbackValue: (lastPersistedNotifications ?? defaultNotificationSettings)[key],
        optimisticUpdate: () => ludusaviStore.setNotificationSettings(nextNotifications),
        rpcCall: () => setNotificationSettings(nextNotifications),
        applyResult: (res) => applySettings(ludusaviStore, res),
        rollbackUpdate: (fallback) => ludusaviStore.setNotificationSettings(fallback),
        getPersistedValue: (res) => res.notifications?.[key]
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
        applyResult: (res) => applySettings(ludusaviStore, res),
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
        applyResult: (res) => applySettings(ludusaviStore, res),
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
        applyResult: (res) => applySettings(ludusaviStore, res),
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
      toggleAutomaticUpdateChecks,
      toggleNotificationSetting,
      toggleUpdateChannel
    };
  }

  function dispose() {
    settingsQueue.length = 0;
    settingsProcessing = false;
    autoSyncSeq = 0;
    notificationSeq = 0;
    selectedGameSeq = 0;
    updateChannelSeq = 0;
    automaticUpdateChecksSeq = 0;
    lastPersistedAutoSync = null;
    lastPersistedNotifications = null;
    lastPersistedUpdateChannel = null;
    lastPersistedAutomaticUpdateChecks = null;
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
