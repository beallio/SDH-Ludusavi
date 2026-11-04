type ThemeRefreshDeps = {
  consumeChange(): Promise<boolean>;
  resetThemes(): Promise<boolean>;
  warn(message: string): void;
};

export function startCssLoaderThemeRefresh(deps: ThemeRefreshDeps): {
  ready: Promise<void>;
  dispose(): void;
} {
  let disposed = false;
  const ready = (async () => {
    try {
      const changed = await deps.consumeChange();
      if (!changed || disposed) return;

      const refreshed = await deps.resetThemes();
      if (!refreshed && !disposed) {
        deps.warn("CSS Loader could not reload the updated theme. Use Refresh in CSS Loader.");
      }
    } catch (error) {
      if (!disposed) {
        deps.warn(`CSS Loader could not reload the updated theme: ${error}`);
      }
    }
  })();

  return { ready, dispose: () => { disposed = true; } };
}

// Directory name from backend/src/status_theme.rs THEME_NAME; CSS Loader reports fails as [dir, error].
const STATUS_THEME = "SDH-Ludusavi Status";
// Decky's sandboxed_plugin raises this before running the method when an api_version 0 plugin
// (the stock DeckThemes CSS Loader) gets positional arguments, so only this error is safe to retry.
const API_VERSION_0_ERROR = "api_version 1 or newer is required to call methods with index-based arguments";

function statusThemeLoaded(reply: unknown): boolean {
  const fails = (reply as { fails?: unknown } | null)?.fails;
  return !Array.isArray(fails) || !fails.some((fail) => Array.isArray(fail) && fail[0] === STATUS_THEME);
}

export async function resetCssLoaderThemes(): Promise<boolean> {
  const backend = window.DeckyBackend;
  if (typeof backend?.callable !== "function") return false;
  // Native plugin backends refuse the legacy route; the modern one rejects on a
  // real failure. CSS Loader's reply ({"fails": [...]}) carries no success flag,
  // and fails lists every broken theme, so only our own entry means our reload failed.
  try {
    return statusThemeLoaded(await backend.callable("loader/call_plugin_method")("CSS Loader", "reset"));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!message.includes(API_VERSION_0_ERROR)) throw error;
  }
  const legacy = (await backend.callable("loader/call_legacy_plugin_method")("CSS Loader", "reset", {})) as
    | { success?: unknown; result?: unknown }
    | null;
  return legacy?.success === true && statusThemeLoaded(legacy.result);
}
