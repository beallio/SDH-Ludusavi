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

export async function resetCssLoaderThemes(): Promise<boolean> {
  const backend = window.DeckyBackend;
  if (typeof backend?.callable !== "function") return false;
  // Native plugin backends refuse the legacy route; the modern one rejects on a
  // real failure, and CSS Loader's own reply ({"fails": []}) carries no success flag.
  await backend.callable("loader/call_plugin_method")("CSS Loader", "reset");
  return true;
}
