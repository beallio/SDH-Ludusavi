import { createContentLoadCoordinator } from "./contentLoadCoordinator";
import { createAutoSyncStatusSurface } from "../surfaces/autoSyncStatusSurface";
import { createAutoSyncStatusBrowserView, type AutoSyncStatusBrowserViewApi } from "../surfaces/autoSyncStatusBrowserView";
import { createSettingsMutationRuntime, type SettingsMutationRuntime } from "../settings/settingsMutationRuntime";

export type PluginRuntimeOverrides = {
  contentLoad?: ReturnType<typeof createContentLoadCoordinator>;
  settings?: SettingsMutationRuntime;
  statusSurface?: ReturnType<typeof createAutoSyncStatusSurface>;
  statusView?: AutoSyncStatusBrowserViewApi;
};

export type PluginRuntime = Readonly<{
  settings: SettingsMutationRuntime;
  statusSurface: ReturnType<typeof createAutoSyncStatusSurface>;
  statusView: AutoSyncStatusBrowserViewApi;
  contentLoad: ReturnType<typeof createContentLoadCoordinator>;
  dispose(): void;
}>;

export function createPluginRuntime(overrides?: PluginRuntimeOverrides): PluginRuntime {
  const contentLoad = overrides?.contentLoad ?? createContentLoadCoordinator();
  const statusView = overrides?.statusView ?? createAutoSyncStatusBrowserView();
  const statusSurface = overrides?.statusSurface ?? createAutoSyncStatusSurface(statusView);
  const settings = overrides?.settings ?? createSettingsMutationRuntime();

  return {
    settings,
    statusSurface,
    statusView,
    contentLoad,
    dispose() {
      // order mirrors old onDismount: statusSurface -> settings -> contentLoad
      statusSurface.dispose();
      settings.dispose();
      contentLoad.initPromise = null;
      contentLoad.metadataPromise = null;
    }
  };
}
