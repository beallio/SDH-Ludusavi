import { createContentLoadCoordinator } from "./contentLoadCoordinator";

export type PluginRuntimeOverrides = {
  contentLoad?: ReturnType<typeof createContentLoadCoordinator>;
  settings?: any;
  statusSurface?: any;
};

export type PluginRuntime = Readonly<{
  settings: any;
  statusSurface: any;
  contentLoad: ReturnType<typeof createContentLoadCoordinator>;
  dispose(): void;
}>;

export function createPluginRuntime(overrides?: PluginRuntimeOverrides): PluginRuntime {
  const contentLoad = overrides?.contentLoad ?? createContentLoadCoordinator();

  return {
    settings: overrides?.settings ?? {},
    statusSurface: overrides?.statusSurface ?? {},
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
