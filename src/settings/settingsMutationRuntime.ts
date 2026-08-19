import { SingleDropdownOption } from "@decky/ui";

import { updateSettingsCall } from "../api/ludusaviRpc";
import {
  defaultNotificationSettings,
  defaultSettings,
  type LudusaviStateStore,
} from "../state/ludusaviState";
import type {
  NotificationSettings,
  Settings,
  SettingsPatch,
} from "../types";
import { log, logUiEvent, type LogFieldValue } from "../utils/logging";
import { isRpcStatus } from "../utils/rpc";

type NotifyFailure = (title: string, body: string) => void;

type SettingsMutationControllerOptions = {
  ludusaviStore: LudusaviStateStore;
  notifyFailure: NotifyFailure;
};

type QueuedMutation = {
  patch: SettingsPatch;
  key: string;
  sequence: number;
};

export type SettingsMutationRuntime = ReturnType<typeof createSettingsMutationRuntime>;

function completeSettings(candidate: Partial<Settings>, base = defaultSettings()): Settings {
  return {
    ...base,
    ...candidate,
    sync_disabled_games: [
      ...(candidate.sync_disabled_games ?? base.sync_disabled_games),
    ],
    notifications: {
      ...base.notifications,
      ...candidate.notifications,
    },
  };
}

function mutationKey(patch: SettingsPatch): string {
  if (patch.kind === "game_sync") return `${patch.kind}:${patch.game_name}`;
  if (patch.kind === "notification") return `${patch.kind}:${patch.key}`;
  return patch.kind;
}

function settingKey(patch: SettingsPatch): string {
  if (patch.kind === "auto_sync") return "auto_sync_enabled";
  if (patch.kind === "game_sync") return "sync_disabled_games";
  if (patch.kind === "selected_game") return "selected_game";
  if (patch.kind === "notification") return `notifications.${String(patch.key)}`;
  return patch.kind;
}

function settingValue(patch: SettingsPatch): LogFieldValue {
  if (patch.kind === "selected_game") return patch.game_name;
  if (patch.kind === "update_channel") return patch.channel;
  return patch.enabled;
}

function applyOptimisticPatch(store: LudusaviStateStore, patch: SettingsPatch): void {
  if (patch.kind === "auto_sync") {
    store.setAutoSyncEnabled(patch.enabled);
  } else if (patch.kind === "game_sync") {
    store.setGameSyncEnabled(patch.game_name, patch.enabled);
  } else if (patch.kind === "selected_game") {
    store.setDisplayedGame(patch.game_name);
  } else if (patch.kind === "notification") {
    const current = store.getSnapshot().settings?.notifications ?? defaultNotificationSettings;
    store.setNotificationSettings({ ...current, [patch.key]: patch.enabled });
  } else if (patch.kind === "update_channel") {
    store.setUpdateChannel(patch.channel);
  } else if (patch.kind === "automatic_update_checks") {
    store.setAutomaticUpdateChecks(patch.enabled);
  } else {
    store.setDebugLogging(patch.enabled);
  }
}

function applyPersistedField(
  store: LudusaviStateStore,
  patch: SettingsPatch,
  persisted: Settings,
): void {
  if (patch.kind === "auto_sync") {
    store.setAutoSyncEnabled(persisted.auto_sync_enabled);
  } else if (patch.kind === "game_sync") {
    store.setGameSyncEnabled(
      patch.game_name,
      !persisted.sync_disabled_games.includes(patch.game_name),
    );
  } else if (patch.kind === "selected_game") {
    store.patchSettings({ selected_game: persisted.selected_game });
  } else if (patch.kind === "notification") {
    const current = store.getSnapshot().settings?.notifications ?? defaultNotificationSettings;
    store.setNotificationSettings({
      ...current,
      [patch.key]: persisted.notifications[patch.key],
    });
  } else if (patch.kind === "update_channel") {
    store.setUpdateChannel(persisted.update_channel);
  } else if (patch.kind === "automatic_update_checks") {
    store.setAutomaticUpdateChecks(persisted.automatic_update_checks);
  } else {
    store.setDebugLogging(persisted.debug_logging);
  }
}

function mergeLateField(
  current: Settings,
  patch: SettingsPatch,
  resolved: Settings,
): Settings {
  const merged = completeSettings({}, current);
  if (patch.kind === "auto_sync") {
    merged.auto_sync_enabled = resolved.auto_sync_enabled;
  } else if (patch.kind === "game_sync") {
    const disabled = new Set(merged.sync_disabled_games);
    if (resolved.sync_disabled_games.includes(patch.game_name)) disabled.add(patch.game_name);
    else disabled.delete(patch.game_name);
    merged.sync_disabled_games = [...disabled].sort();
  } else if (patch.kind === "selected_game") {
    merged.selected_game = resolved.selected_game;
  } else if (patch.kind === "notification") {
    merged.notifications[patch.key] = resolved.notifications[patch.key];
  } else if (patch.kind === "update_channel") {
    merged.update_channel = resolved.update_channel;
  } else if (patch.kind === "automatic_update_checks") {
    merged.automatic_update_checks = resolved.automatic_update_checks;
  } else {
    merged.debug_logging = resolved.debug_logging;
  }
  return merged;
}

export function createSettingsMutationRuntime() {
  const settingsQueue: Array<() => Promise<void>> = [];
  const latestSequenceByKey = new Map<string, number>();
  let settingsProcessing = false;
  let nextSequence = 0;
  let persistedSettings: Settings | null = null;
  let lastQueuedSelectedGame: string | null = null;

  async function processSettingsQueue() {
    if (settingsProcessing) return;
    settingsProcessing = true;
    try {
      while (settingsQueue.length > 0) {
        const task = settingsQueue.shift();
        if (task) await task();
      }
    } finally {
      settingsProcessing = false;
    }
  }

  function enqueueSettingsUpdate(task: () => Promise<void>) {
    settingsQueue.push(task);
    logUiEvent(
      "settings_update_queued",
      { queue_depth: settingsQueue.length },
      "debug",
      "ui_settings",
    );
    void processSettingsQueue();
  }

  function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
    let timeoutID: number;
    const timeout = new Promise<never>((_, reject) => {
      timeoutID = window.setTimeout(
        () => reject(new Error("Settings update timed out")),
        timeoutMs,
      );
    });
    return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timeoutID));
  }

  function applySettings(store: LudusaviStateStore, nextSettings: Settings) {
    const normalized = store.applySettings(completeSettings(nextSettings));
    persistedSettings = completeSettings(normalized);
    return normalized;
  }

  function syncLastQueuedSelectedGame(selectedGame: string) {
    lastQueuedSelectedGame = selectedGame;
  }

  function clearLastQueuedSelectedGame() {
    lastQueuedSelectedGame = null;
  }

  function createController({
    ludusaviStore,
    notifyFailure,
  }: SettingsMutationControllerOptions) {
    const isLatest = (mutation: QueuedMutation) =>
      latestSequenceByKey.get(mutation.key) === mutation.sequence;

    const rollback = (mutation: QueuedMutation) => {
      const fallback = persistedSettings ?? defaultSettings();
      applyPersistedField(ludusaviStore, mutation.patch, fallback);
      if (mutation.patch.kind === "selected_game") {
        ludusaviStore.setDisplayedGame(fallback.selected_game);
        lastQueuedSelectedGame = fallback.selected_game;
      }
    };

    const execute = async (mutation: QueuedMutation) => {
      let awaitFailed = false;
      const originalPromise = updateSettingsCall(mutation.patch)
        .then((result) => {
          if (awaitFailed && !isRpcStatus(result)) {
            const completed = completeSettings(result, persistedSettings ?? defaultSettings());
            persistedSettings = mergeLateField(
              persistedSettings ?? defaultSettings(),
              mutation.patch,
              completed,
            );
            if (isLatest(mutation)) {
              applyPersistedField(ludusaviStore, mutation.patch, persistedSettings);
            }
            logUiEvent(
              "settings_change_late_success",
              { sequence: mutation.sequence, setting: settingKey(mutation.patch) },
              "info",
              "ui_settings",
            );
          }
          return result;
        })
        .catch((error) => {
          if (awaitFailed) log("error", `Late settings failure: ${error}`);
          throw error;
        });

      try {
        const result = await withTimeout(originalPromise, 10_000);
        if (isRpcStatus(result)) throw new Error(result.message || result.status);
        persistedSettings = completeSettings(result, persistedSettings ?? defaultSettings());
        if (isLatest(mutation)) {
          applyPersistedField(ludusaviStore, mutation.patch, persistedSettings);
        }
        logUiEvent(
          "settings_change_persisted",
          { sequence: mutation.sequence, setting: settingKey(mutation.patch) },
          "info",
          "ui_settings",
        );
      } catch (error) {
        awaitFailed = true;
        if (isLatest(mutation)) {
          rollback(mutation);
          logUiEvent(
            "settings_change_rolled_back",
            {
              message: error instanceof Error ? error.message : String(error),
              sequence: mutation.sequence,
              setting: settingKey(mutation.patch),
            },
            "error",
            "ui_settings",
          );
          notifyFailure(
            "SDH-Ludusavi settings failed",
            error instanceof Error ? error.message : String(error),
          );
        }
      }
    };

    const request = (patch: SettingsPatch) => {
      const key = mutationKey(patch);
      const sequence = ++nextSequence;
      latestSequenceByKey.set(key, sequence);
      logUiEvent(
        "settings_change_requested",
        { sequence, setting: settingKey(patch), value: settingValue(patch) },
        "info",
        "ui_settings",
        patch.kind === "game_sync" || patch.kind === "selected_game"
          ? patch.game_name
          : undefined,
      );
      applyOptimisticPatch(ludusaviStore, patch);
      enqueueSettingsUpdate(() => execute({ patch, key, sequence }));
    };

    const onGameChange = (data: SingleDropdownOption | string | null | undefined) => {
      const value = typeof data === "object" && data !== null ? data.data : data;
      if (typeof value !== "string" || value.trim() === "") {
        logUiEvent(
          "settings_change_rejected",
          { setting: "selected_game", value: String(value) },
          "warning",
          "ui_settings",
        );
        return;
      }
      const lastQueued = lastQueuedSelectedGame ?? ludusaviStore.getSnapshot().selectedGame;
      if (value === lastQueued) return;
      lastQueuedSelectedGame = value;
      request({ kind: "selected_game", game_name: value });
    };

    return {
      onGameChange,
      toggleAutoSync: (enabled: boolean) => request({ kind: "auto_sync", enabled }),
      toggleGameSync: (gameName: string, enabled: boolean) =>
        request({ kind: "game_sync", game_name: gameName, enabled }),
      toggleAutomaticUpdateChecks: (enabled: boolean) =>
        request({ kind: "automatic_update_checks", enabled }),
      toggleNotificationSetting: (key: keyof NotificationSettings, enabled: boolean) =>
        request({ kind: "notification", key, enabled }),
      toggleUpdateChannel: (enabled: boolean) =>
        request({
          kind: "update_channel",
          channel: enabled ? "development" : "stable",
        }),
      toggleDebugLogging: (enabled: boolean) =>
        request({ kind: "debug_logging", enabled }),
    };
  }

  function dispose() {
    settingsQueue.length = 0;
    latestSequenceByKey.clear();
    settingsProcessing = false;
    nextSequence = 0;
    persistedSettings = null;
    lastQueuedSelectedGame = null;
  }

  return {
    applySettings,
    syncLastQueuedSelectedGame,
    clearLastQueuedSelectedGame,
    createController,
    dispose,
  };
}
