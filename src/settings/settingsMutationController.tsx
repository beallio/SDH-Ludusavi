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
  isMounted: MountedRef;
  setBusyLabel: (label: string | null) => void;
  notifyFailure: NotifyFailure;
};

const settingsQueue: (() => Promise<void>)[] = [];
let settingsProcessing = false;
const queueListeners = new Set<(busy: boolean) => void>();

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

export function getSettingsQueueBusy() {
  return settingsProcessing || settingsQueue.length > 0;
}

export function subscribeQueue(listener: (busy: boolean) => void) {
  queueListeners.add(listener);
  try {
    listener(getSettingsQueueBusy());
  } catch (err) {
    log("error", `Initial queue listener call failed: ${err}`);
  }
  return () => {
    queueListeners.delete(listener);
  };
}

function notifyQueueListeners() {
  const busy = getSettingsQueueBusy();
  queueListeners.forEach((listener) => {
    try {
      listener(busy);
    } catch (err) {
      log("error", `Queue listener notification failed: ${err}`);
    }
  });
}

async function processSettingsQueue() {
  if (settingsProcessing) return;
  settingsProcessing = true;
  notifyQueueListeners();
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
      notifyQueueListeners();
    }
  } finally {
    settingsProcessing = false;
    notifyQueueListeners();
  }
}

function enqueueSettingsUpdate(task: () => Promise<void>) {
  settingsQueue.push(task);
  logUiEvent("settings_update_queued", { queue_depth: settingsQueue.length }, "debug", "ui_settings");
  notifyQueueListeners();
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


export function applySettingsGlobal(store: LudusaviStateStore, nextSettings: Settings) {
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

export function syncLastQueuedSelectedGame(selectedGame: string) {
  lastQueuedSelectedGame = selectedGame;
}

export function clearLastQueuedSelectedGame() {
  lastQueuedSelectedGame = null;
}

export function setActiveSettingsStore(store: LudusaviStateStore, notifyFailure: NotifyFailure) {
  activeLudusaviStore = store;
  activeFailureNotifier = notifyFailure;
}

export function resetSettingsMutationController() {
  settingsQueue.length = 0;
  settingsProcessing = false;
  queueListeners.clear();
  notifyQueueListeners();
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

export function createSettingsMutationController({
  ludusaviStore,
  isMounted,
  setBusyLabel,
  notifyFailure
}: SettingsMutationControllerOptions) {
  setActiveSettingsStore(ludusaviStore, notifyFailure);

  const logSettingsEvent = (
    event: string,
    setting: string,
    fields: LogFields = {},
    level: LogLevel = "info",
    gameName?: string,
  ) => {
    logUiEvent(event, { setting, ...fields }, level, "ui_settings", gameName);
  };

  const markBusy = () => {
    if (isMounted.current) {
      setBusyLabel("Updating settings");
    }
  };

  const reportSettingsFailure = (error: unknown) => {
    notifyFailure(
      "SDH-Ludusavi settings failed",
      error instanceof Error ? error.message : String(error)
    );
  };

  const toggleAutoSync = (enabled: boolean) => {
    const updateSeq = ++autoSyncSeq;
    logSettingsEvent("settings_change_requested", "auto_sync_enabled", {
      sequence: updateSeq,
      value: enabled,
    });
    ludusaviStore.setAutoSyncEnabled(enabled);
    markBusy();

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle auto-sync to ${enabled}`);
      let awaitFailed = false;
      const originalPromise = setAutoSyncEnabled(enabled).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setAutoSyncEnabled to ${enabled} succeeded`);
          if (updateSeq === autoSyncSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setAutoSyncEnabled to ${enabled}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting auto-sync timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === autoSyncSeq) {
          applySettingsGlobal(ludusaviStore, result);
          logSettingsEvent("settings_change_persisted", "auto_sync_enabled", {
            sequence: updateSeq,
            value: result.auto_sync_enabled,
          });
        } else {
          logSettingsEvent("settings_change_superseded", "auto_sync_enabled", {
            sequence: updateSeq,
          }, "debug");
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to toggle auto-sync: ${error}`);
        if (updateSeq === autoSyncSeq) {
          const fallback = lastPersistedAutoSync ?? false;
          ludusaviStore.setAutoSyncEnabled(fallback);
          logSettingsEvent("settings_change_rolled_back", "auto_sync_enabled", {
            fallback,
            message: error instanceof Error ? error.message : String(error),
            sequence: updateSeq,
          }, "error");
          reportSettingsFailure(error);
        }
      }
    });
  };

  const toggleNotificationSetting = (key: keyof NotificationSettings, enabled: boolean) => {
    const updateSeq = ++notificationSeq;
    logSettingsEvent("settings_change_requested", `notifications.${String(key)}`, {
      sequence: updateSeq,
      value: enabled,
    });
    const previousNotifications = ludusaviStore.getSnapshot().settings?.notifications ?? defaultNotificationSettings;
    const nextNotifications = { ...previousNotifications, [key]: enabled };
    ludusaviStore.setNotificationSettings(nextNotifications);
    markBusy();

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle notification setting ${String(key)} to ${enabled}`);
      let awaitFailed = false;
      const originalPromise = setNotificationSettings(nextNotifications).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setNotificationSettings to ${JSON.stringify(nextNotifications)} succeeded`);
          if (updateSeq === notificationSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setNotificationSettings to ${JSON.stringify(nextNotifications)}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting notifications timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === notificationSeq) {
          applySettingsGlobal(ludusaviStore, result);
          logSettingsEvent("settings_change_persisted", `notifications.${String(key)}`, {
            sequence: updateSeq,
            value: result.notifications?.[key],
          });
        } else {
          logSettingsEvent("settings_change_superseded", `notifications.${String(key)}`, {
            sequence: updateSeq,
          }, "debug");
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to update notification settings: ${error}`);
        if (updateSeq === notificationSeq) {
          const fallback = lastPersistedNotifications ?? defaultNotificationSettings;
          ludusaviStore.setNotificationSettings(fallback);
          logSettingsEvent("settings_change_rolled_back", `notifications.${String(key)}`, {
            fallback: fallback[key],
            message: error instanceof Error ? error.message : String(error),
            sequence: updateSeq,
          }, "error");
          reportSettingsFailure(error);
        }
      }
    });
  };

  const toggleUpdateChannel = (enabled: boolean) => {
    const channel = enabled ? "development" : "stable";
    const updateSeq = ++updateChannelSeq;
    logSettingsEvent("settings_change_requested", "update_channel", {
      sequence: updateSeq,
      value: channel,
    });
    ludusaviStore.setUpdateChannel(channel);
    markBusy();

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle update channel to ${channel}`);
      let awaitFailed = false;
      const originalPromise = setUpdateChannelCall(channel).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setUpdateChannel to ${channel} succeeded`);
          if (updateSeq === updateChannelSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setUpdateChannel to ${channel}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting update channel timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === updateChannelSeq) {
          applySettingsGlobal(ludusaviStore, result);
          logSettingsEvent("settings_change_persisted", "update_channel", {
            sequence: updateSeq,
            value: result.update_channel,
          });
        } else {
          logSettingsEvent("settings_change_superseded", "update_channel", {
            sequence: updateSeq,
          }, "debug");
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to toggle update channel: ${error}`);
        if (updateSeq === updateChannelSeq) {
          const fallback = lastPersistedUpdateChannel ?? "stable";
          ludusaviStore.setUpdateChannel(fallback);
          logSettingsEvent("settings_change_rolled_back", "update_channel", {
            fallback,
            message: error instanceof Error ? error.message : String(error),
            sequence: updateSeq,
          }, "error");
          reportSettingsFailure(error);
        }
      }
    });
  };

  const toggleAutomaticUpdateChecks = (enabled: boolean) => {
    const updateSeq = ++automaticUpdateChecksSeq;
    logSettingsEvent("settings_change_requested", "automatic_update_checks", {
      sequence: updateSeq,
      value: enabled,
    });
    ludusaviStore.setAutomaticUpdateChecks(enabled);
    markBusy();

    enqueueSettingsUpdate(async () => {
      log("info", `Executing toggle automatic update checks to ${enabled}`);
      let awaitFailed = false;
      const originalPromise = setAutomaticUpdateChecksCall(enabled).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setAutomaticUpdateChecks to ${enabled} succeeded`);
          if (updateSeq === automaticUpdateChecksSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setAutomaticUpdateChecks to ${enabled}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Setting automatic checks timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === automaticUpdateChecksSeq) {
          applySettingsGlobal(ludusaviStore, result);
          logSettingsEvent("settings_change_persisted", "automatic_update_checks", {
            sequence: updateSeq,
            value: result.automatic_update_checks,
          });
        } else {
          logSettingsEvent("settings_change_superseded", "automatic_update_checks", {
            sequence: updateSeq,
          }, "debug");
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to toggle automatic checks: ${error}`);
        if (updateSeq === automaticUpdateChecksSeq) {
          const fallback = lastPersistedAutomaticUpdateChecks ?? true;
          ludusaviStore.setAutomaticUpdateChecks(fallback);
          logSettingsEvent("settings_change_rolled_back", "automatic_update_checks", {
            fallback,
            message: error instanceof Error ? error.message : String(error),
            sequence: updateSeq,
          }, "error");
          reportSettingsFailure(error);
        }
      }
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
    const updateSeq = ++selectedGameSeq;
    logSettingsEvent("settings_change_requested", "selected_game", {
      previous_value: lastQueued,
      sequence: updateSeq,
      value,
    }, "info", value);
    lastQueuedSelectedGame = value;
    ludusaviStore.setSelectedGame(value);
    markBusy();

    enqueueSettingsUpdate(async () => {
      log("info", `Executing selected game change to ${value}`);
      let awaitFailed = false;
      const originalPromise = setSelectedGameCall(value).then((res) => {
        if (awaitFailed) {
          log("info", `Late resolution of setSelectedGameCall to ${value} succeeded`);
          if (updateSeq === selectedGameSeq && !isRpcStatus(res)) {
            applySettingsGlobal(ludusaviStore, res);
          }
        }
        return res;
      }).catch((err) => {
        if (awaitFailed) {
          log("error", `Late failure of setSelectedGameCall to ${value}: ${err}`);
        }
        throw err;
      });

      try {
        const result = await withTimeout(originalPromise, 10000, "Selecting game timed out");
        if (isRpcStatus(result)) {
          throw new Error(result.message || result.status);
        }
        if (updateSeq === selectedGameSeq) {
          applySettingsGlobal(ludusaviStore, result);
          logSettingsEvent("settings_change_persisted", "selected_game", {
            sequence: updateSeq,
            value: result.selected_game,
          }, "info", value);
        } else {
          logSettingsEvent("settings_change_superseded", "selected_game", {
            sequence: updateSeq,
          }, "debug", value);
        }
      } catch (error) {
        awaitFailed = true;
        log("error", `Failed to persist selected game: ${error}`);
        if (updateSeq === selectedGameSeq) {
          const fallback = lastPersistedSelectedGame ?? "";
          ludusaviStore.setSelectedGame(fallback);
          lastQueuedSelectedGame = fallback;
          logSettingsEvent("settings_change_rolled_back", "selected_game", {
            fallback,
            message: error instanceof Error ? error.message : String(error),
            sequence: updateSeq,
          }, "error", value);
          reportSettingsFailure(error);
        }
      }
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
