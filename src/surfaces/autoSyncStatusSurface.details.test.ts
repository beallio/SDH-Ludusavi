import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react", () => ({
  createContext: vi.fn(),
  useContext: vi.fn(),
  useSyncExternalStore: vi.fn(),
}));
vi.mock("react/jsx-dev-runtime", () => ({ jsxDEV: vi.fn(), Fragment: Symbol("Fragment") }));
vi.mock("@decky/ui", () => ({ Router: {} }));
vi.mock("../ludusaviLauncher", () => ({}));
vi.mock("../utils/steam", () => ({ normalize: (name: string) => name.toLowerCase() }));
vi.mock("../utils/logging", () => ({ log: vi.fn(), logUiEvent: vi.fn() }));

import { createLudusaviStateStore } from "../state/ludusaviState";
import { RESULT_HIDE_DELAY_MS, createAutoSyncStatusSurface } from "./autoSyncStatusSurface";

function trackedStore() {
  const store = createLudusaviStateStore();
  store.applyRefreshResult({
    games: [{
      name: "Fixture",
      steam_id: "100",
      configured: true,
      has_backup: true,
      needs_first_backup: false,
      error: null,
      status: "has_backup",
    }],
    aliases: {},
    history: {},
    dependency_error: null,
  });
  return store;
}

describe("details-row status ownership", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("window", globalThis);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("retains a real terminal Syncthing limitation after the strip expires", () => {
    const store = trackedStore();
    const surface = createAutoSyncStatusSurface({
      setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn(),
    } as any, store);

    surface.complete(
      { status: "backed_up", game: "Fixture" },
      { lifecycle: "lifecycle_exit", generation: 3, gameName: "Fixture", appID: "100", tracked: true },
    );
    surface.publish("syncthing_folder_not_found", {
      source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 3,
      gameName: "Fixture", appID: "100", tracked: true,
    });
    vi.advanceTimersByTime(1000);
    vi.advanceTimersByTime(RESULT_HIDE_DELAY_MS);

    const observation = store.getSnapshot().autoSyncObservations["100"];
    expect(observation.localOperation?.status).toBe("has_backup");
    expect(observation.syncObservation?.status).toBe("syncthing_folder_not_found");
  });

  it("suppresses only same-game exit pixels while a valid details row owns the area", () => {
    const store = trackedStore();
    const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
    const surface = createAutoSyncStatusSurface(view as any, store);
    const release = surface.registerDetailsOwner({ appID: "100", visible: true, layoutValid: true });

    surface.publish("backing_up", {
      source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 4,
      gameName: "Fixture", appID: "100", tracked: true,
    });
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));

    release();
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ status: "backing_up", visible: true }));
  });
});
