import { createContentLoadCoordinator } from "./contentLoadCoordinator";
import { createAutoSyncStatusSurface } from "../surfaces/autoSyncStatusSurface";
import { createAutoSyncStatusBrowserView, type AutoSyncStatusBrowserViewApi } from "../surfaces/autoSyncStatusBrowserView";

export type PluginRuntimeOverrides = {
  contentLoad?: ReturnType<typeof createContentLoadCoordinator>;
  settings?: any;
  statusSurface?: ReturnType<typeof createAutoSyncStatusSurface>;
  statusView?: AutoSyncStatusBrowserViewApi;
};

export type PluginRuntime = Readonly<{
  settings: any;
  statusSurface: ReturnType<typeof createAutoSyncStatusSurface>;
  statusView: AutoSyncStatusBrowserViewApi;
  contentLoad: ReturnType<typeof createContentLoadCoordinator>;
  dispose(): void;
}>;

export function createPluginRuntime(overrides?: PluginRuntimeOverrides): PluginRuntime {
  const contentLoad = overrides?.contentLoad ?? createContentLoadCoordinator();
  const statusView = overrides?.statusView ?? createAutoSyncStatusBrowserView();
  const statusSurface = overrides?.statusSurface ?? createAutoSyncStatusSurface(statusView);

  return {
    settings: overrides?.settings ?? {},
    statusSurface,
    statusView,
    contentLoad,
    dispose() {
      // order mirrors old onDismount: statusSurface -> settings -> contentLoad
      if (this.statusSurface && typeof this.statusSurface.dispose === "function") {
        this.statusSurface.dispose();
      }
      if (this.settings && typeof this.settings.dispose === "function") {
        this.settings.dispose();
      }
      contentLoad.dispose();
    }
  };
}
