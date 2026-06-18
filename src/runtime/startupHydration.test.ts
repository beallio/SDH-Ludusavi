import { describe, it, expect, vi } from "vitest";
import { createStartupHydration, StartupHydrationDeps } from "./startupHydration";
import { Settings, RpcStatus } from "../types";
import { isRpcStatus } from "../utils/rpc";

const SETTINGS: Settings = {
  auto_sync_enabled: true,
  selected_game: "Celeste",
  notifications: {
    enabled: true,
    auto_sync_progress: true,
    auto_sync_results: true,
    manual_operations: false,
    refresh_status: false,
    failures_errors: true,
  },
  update_channel: "stable",
  automatic_update_checks: true,
  debug_logging: true,
};

function makeDeps(overrides: Partial<StartupHydrationDeps> = {}): StartupHydrationDeps {
  return {
    fetchSettings: vi.fn().mockResolvedValue(SETTINGS),
    getStoredSettings: vi.fn().mockReturnValue(null),
    isRpcStatus,
    applySettings: vi.fn(),
    logRpcStatus: vi.fn(),
    logUiEvent: vi.fn(),
    logError: vi.fn(),
    ...overrides,
  };
}

describe("createStartupHydration", () => {
  it("applies fetched settings and logs hydration once", async () => {
    const deps = makeDeps();

    const hydration = createStartupHydration(deps);
    await hydration.ready;

    expect(deps.applySettings).toHaveBeenCalledTimes(1);
    expect(deps.applySettings).toHaveBeenCalledWith(SETTINGS);
    expect(deps.logUiEvent).toHaveBeenCalledWith(
      "startup_settings_hydrated",
      {
        auto_sync_enabled: true,
        selected_game: "Celeste",
        update_channel: "stable",
      },
      "info",
    );
  });

  it("skips when the store is already populated", async () => {
    const deps = makeDeps({ getStoredSettings: vi.fn().mockReturnValue(SETTINGS) });

    const hydration = createStartupHydration(deps);
    await hydration.ready;

    expect(deps.applySettings).not.toHaveBeenCalled();
    expect(deps.logUiEvent).toHaveBeenCalledWith("startup_settings_hydration_skipped", {
      reason: "state_already_populated",
    });
  });

  it("routes RPC failure payloads to logRpcStatus without applying", async () => {
    const failure: RpcStatus = { status: "failed", message: "nope" };
    const deps = makeDeps({ fetchSettings: vi.fn().mockResolvedValue(failure) });

    const hydration = createStartupHydration(deps);
    await hydration.ready;

    expect(deps.applySettings).not.toHaveBeenCalled();
    expect(deps.logRpcStatus).toHaveBeenCalledWith(failure, "startup settings");
  });

  it("does not apply settings or log hydration after dispose", async () => {
    let resolveFetch: (settings: Settings) => void = () => {};
    const deps = makeDeps({
      fetchSettings: vi.fn().mockReturnValue(
        new Promise<Settings>((resolve) => {
          resolveFetch = resolve;
        }),
      ),
    });

    const hydration = createStartupHydration(deps);
    hydration.dispose();
    resolveFetch(SETTINGS);
    await hydration.ready;

    expect(deps.applySettings).not.toHaveBeenCalled();
    expect(deps.logUiEvent).toHaveBeenCalledWith("startup_settings_hydration_skipped", {
      reason: "plugin_dismounted",
    });
    const hydratedCalls = (deps.logUiEvent as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([event]) => event === "startup_settings_hydrated",
    );
    expect(hydratedCalls).toHaveLength(0);
  });

  it("logs fetch errors without throwing, and stays quiet after dispose", async () => {
    const failing = makeDeps({ fetchSettings: vi.fn().mockRejectedValue(new Error("boom")) });
    await createStartupHydration(failing).ready;
    expect(failing.logError).toHaveBeenCalledTimes(1);

    let rejectFetch: (err: Error) => void = () => {};
    const disposed = makeDeps({
      fetchSettings: vi.fn().mockReturnValue(
        new Promise<Settings>((_resolve, reject) => {
          rejectFetch = reject;
        }),
      ),
    });
    const hydration = createStartupHydration(disposed);
    hydration.dispose();
    rejectFetch(new Error("late boom"));
    await hydration.ready;
    expect(disposed.logError).not.toHaveBeenCalled();
  });
});
