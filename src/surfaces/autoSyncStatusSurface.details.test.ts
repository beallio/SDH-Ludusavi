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

import { selectGameDetailsStatus } from "./gameDetailsStatusModel";
function trackedStore() {
  const store = createLudusaviStateStore();
  store.patchSettings({ auto_sync_enabled: true });
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
    const model = selectGameDetailsStatus({
      snapshot: store.getSnapshot(), appID: "100", gameName: "Fixture",
      canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(model.status).toBe("syncthing_folder_not_found");
    expect(model.label).toContain("Remote folder was not found");
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

  it("keeps only the strip readable while a same-game exit row is clipped, then hands off when it can own the band", () => {
    const store = trackedStore();
    const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
    const surface = createAutoSyncStatusSurface(view, store);

    surface.publish("backing_up", {
      source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 8,
      gameName: "Fixture", appID: "100", tracked: true,
    });

    // A clipped row cannot own the status area, so it must not paint beside
    // the fallback strip for the same app.
    expect(surface.shouldDetailsRowYield("100")).toBe(true);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({
      appID: "100", status: "backing_up", visible: true,
    }));

    // The row may measure while hidden. Once its geometry is valid, it owns
    // the area and the same status no longer has duplicate strip pixels.
    const release = surface.registerDetailsOwner({ appID: "100", visible: true, layoutValid: true });
    expect(surface.shouldDetailsRowYield("100")).toBe(false);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));

    release();
    expect(surface.shouldDetailsRowYield("100")).toBe(true);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
  });

  it("records a terminal local result even when the strip timed out", () => {
    const store = trackedStore();
    const surface = createAutoSyncStatusSurface({ setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() } as any, store);
    surface.publish("checking", { source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 5, gameName: "Fixture", appID: "100", tracked: true });
    vi.advanceTimersByTime(210_000);
    surface.complete({ status: "backed_up", game: "Fixture" }, { lifecycle: "lifecycle_exit", generation: 5, gameName: "Fixture", appID: "100", tracked: true });
    expect(store.getSnapshot().autoSyncObservations["100"].localOperation?.status).toBe("has_backup");
  });

  it("makes the row yield to protected or other-game strips and settles hidden active work", () => {
    const store = trackedStore();
    const surface = createAutoSyncStatusSurface({ setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() } as any, store);
    surface.publish("checking", { source: "lifecycle_start", lifecycle: "lifecycle_start", generation: 6, gameName: "Fixture", appID: "100", tracked: true });
    expect(surface.shouldDetailsRowYield("100")).toBe(true);
    surface.hide({ source: "hide", appID: "100", generation: 6 });
    expect(store.getSnapshot().autoSyncObservations["100"].activity).toBe("unverified");
    surface.publish("backing_up", { source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 7, gameName: "Other", appID: "101", tracked: true });
    expect(surface.shouldDetailsRowYield("100")).toBe(true);
    expect(surface.shouldDetailsRowYield("101")).toBe(true);
  });

  it("keeps a stopped pre-launch transfer inactive and explicitly unverified", () => {
    const store = trackedStore();
    const surface = createAutoSyncStatusSurface({ setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() } as any, store);
    surface.publish("syncthing_downloading", {
      source: "lifecycle_start", lifecycle: "lifecycle_start", generation: 6,
      gameName: "Fixture", appID: "100", tracked: true,
    });

    surface.settleObservation({ appID: "100", generation: 6 });

    const model = selectGameDetailsStatus({
      snapshot: store.getSnapshot(), appID: "100", gameName: "Fixture",
      canonicalGameName: "Fixture", eligibility: "eligible",
    });
    expect(model.active).toBe(false);
    expect(model.syncStatus).toBe("syncthing_downloading");
    expect(model.syncVerification).toBe("unverified");
    expect(model.description).toContain("Remote sync is unverified after interrupted activity.");
  });

  it("retires a stopped pre-launch transfer from both presentations", () => {
    const store = trackedStore();
    const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
    const surface = createAutoSyncStatusSurface(view, store);
    surface.publish("syncthing_downloading", {
      source: "lifecycle_start", lifecycle: "lifecycle_start", generation: 7,
      gameName: "Fixture", appID: "100", tracked: true,
    });

    surface.settleObservation({ appID: "100", generation: 7 });

    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({
      appID: "100", status: "syncthing_downloading", visible: false,
    }));
    expect(surface.shouldDetailsRowYield("100")).toBe(false);
  });

});
