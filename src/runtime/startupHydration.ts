import { Settings, RpcResult, RpcStatus } from "../types";

/**
 * Startup settings hydration that can be cancelled on plugin dismount.
 *
 * Decky's update flow can dismount a plugin instance milliseconds after
 * definePlugin runs; without cancellation the dismounted instance's pending
 * settings fetch still resolved and mutated runtime state alongside the
 * replacement mount (observed as duplicate startup_settings_hydrated logs
 * after a self-update).
 */
export interface StartupHydrationDeps {
  fetchSettings(): Promise<RpcResult<Settings>>;
  /** Returns the already-hydrated settings snapshot, or null when empty. */
  getStoredSettings(): Settings | null;
  isRpcStatus(result: RpcResult<Settings>): result is RpcStatus;
  applySettings(settings: Settings): void;
  logRpcStatus(result: RpcStatus, operation: string): void;
  logUiEvent(event: string, fields?: Record<string, unknown>, level?: string): void;
  logError(message: string): void;
}

export interface StartupHydration {
  ready: Promise<void>;
  dispose(): void;
}

export function createStartupHydration(deps: StartupHydrationDeps): StartupHydration {
  let disposed = false;

  const ready = (async () => {
    try {
      const settings = await deps.fetchSettings();
      if (disposed) {
        deps.logUiEvent("startup_settings_hydration_skipped", {
          reason: "plugin_dismounted",
        });
        return;
      }
      if (deps.isRpcStatus(settings)) {
        deps.logRpcStatus(settings, "startup settings");
        return;
      }
      if (deps.getStoredSettings() !== null) {
        deps.logUiEvent("startup_settings_hydration_skipped", {
          reason: "state_already_populated",
        });
        return;
      }
      deps.applySettings(settings);
      deps.logUiEvent(
        "startup_settings_hydrated",
        {
          auto_sync_enabled: settings.auto_sync_enabled,
          selected_game: settings.selected_game,
          update_channel: settings.update_channel,
        },
        "info",
      );
    } catch (err) {
      if (disposed) {
        return;
      }
      deps.logError(`Failed to hydrate lifecycle settings at plugin startup: ${err}`);
    }
  })();

  return {
    ready,
    dispose() {
      disposed = true;
    },
  };
}
