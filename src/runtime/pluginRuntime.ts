import { createContentLoadCoordinator } from "./contentLoadCoordinator";
import { createAutoSyncStatusSurface } from "../surfaces/autoSyncStatusSurface";
import { createAutoSyncStatusBrowserView, type AutoSyncStatusBrowserViewApi } from "../surfaces/autoSyncStatusBrowserView";
import { createSettingsMutationRuntime, type SettingsMutationRuntime } from "../settings/settingsMutationRuntime";
import { createGameDetailsStatusSurface, type GameDetailsStatusSurface } from "../surfaces/gameDetailsStatus";
import type { LudusaviStateStore } from "../state/ludusaviState";

export type PluginRuntimeOverrides = {
  contentLoad?: ReturnType<typeof createContentLoadCoordinator>;
  settings?: SettingsMutationRuntime;
  statusSurface?: ReturnType<typeof createAutoSyncStatusSurface>;
  statusView?: AutoSyncStatusBrowserViewApi;
  detailsSurface?: GameDetailsStatusSurface;
};

export type PluginRuntime = Readonly<{
  settings: SettingsMutationRuntime;
  statusSurface: ReturnType<typeof createAutoSyncStatusSurface>;
  statusView: AutoSyncStatusBrowserViewApi;
  contentLoad: ReturnType<typeof createContentLoadCoordinator>;
  detailsSurface: GameDetailsStatusSurface | null;
  dispose(): void;
}>;

export function createPluginRuntime(overrides?: PluginRuntimeOverrides): PluginRuntime;
export function createPluginRuntime(store: LudusaviStateStore, overrides?: PluginRuntimeOverrides): PluginRuntime;
export function createPluginRuntime(
  storeOrOverrides?: LudusaviStateStore | PluginRuntimeOverrides,
  maybeOverrides?: PluginRuntimeOverrides,
): PluginRuntime {
  const store = isLudusaviStateStore(storeOrOverrides) ? storeOrOverrides : undefined;
  const overrides = store ? maybeOverrides : storeOrOverrides as PluginRuntimeOverrides | undefined;
  const contentLoad = overrides?.contentLoad ?? createContentLoadCoordinator();
  const statusView = overrides?.statusView ?? createAutoSyncStatusBrowserView();
  const statusSurface = overrides?.statusSurface ?? createAutoSyncStatusSurface(statusView, store);
  const settings = overrides?.settings ?? createSettingsMutationRuntime();
  const detailsSurface = store
    ? overrides?.detailsSurface ?? createGameDetailsStatusSurface(store, statusSurface)
    : null;

  return {
    settings,
    statusSurface,
    statusView,
    contentLoad,
    detailsSurface,
    dispose() {
      // Remove the route contribution before the status surface it may own.
      detailsSurface?.dispose();
      statusSurface.dispose();
      settings.dispose();
      contentLoad.initPromise = null;
      contentLoad.metadataPromise = null;
    }
  };
}

function isLudusaviStateStore(value: unknown): value is LudusaviStateStore {
  return typeof value === "object" && value !== null && "getSnapshot" in value && "subscribe" in value;
}
