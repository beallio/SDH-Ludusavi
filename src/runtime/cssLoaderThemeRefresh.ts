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
  const result = await backend.callable("loader/call_legacy_plugin_method")(
    "CSS Loader", "reset", {},
  );
  return typeof result === "object" && result !== null && "success" in result && result.success === true;
}
