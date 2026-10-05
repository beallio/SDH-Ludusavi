import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  isSyncthingActiveStatus,
  shouldAutoHideStatus,
  createAutoSyncStatusSurface,
  RESULT_HIDE_DELAY_MS,
} from "./autoSyncStatusSurface";
import { renderAutoSyncStatusHtml } from "./autoSyncStatusRenderer";
import { parseHTML } from "linkedom";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {},
}));

describe("Auto-sync status presentation policy", () => {
  it("lets the post-game fallback glyph inherit its animated icon color", () => {
    const { document } = parseHTML(renderAutoSyncStatusHtml({
      status: "backing_up",
      visible: true,
      source: "lifecycle_exit",
      lifecycle: "lifecycle_exit",
    }));
    const icon = document.querySelector(".icon svg")!;
    for (const element of icon.querySelectorAll("[fill], [stroke]")) {
      for (const attribute of ["fill", "stroke"]) {
        const paint = element.getAttribute(attribute);
        if (paint !== null) expect(["none", "currentColor"]).toContain(paint);
      }
    }
  });

  it("auto-hides the per-game disabled notice", () => {
    expect(shouldAutoHideStatus("game_sync_disabled")).toBe(true);
  });

  it("should consider syncthing_pending_upload as active status", () => {
    expect(isSyncthingActiveStatus("syncthing_pending_upload")).toBe(true);
    expect(isSyncthingActiveStatus("syncthing_uploading")).toBe(true);
    expect(isSyncthingActiveStatus("syncthing_downloading")).toBe(true);
    expect(isSyncthingActiveStatus("checking")).toBe(false);
  });

  it("keeps active Syncthing states visible until the monitor replaces them", () => {
    expect(shouldAutoHideStatus("syncthing_pending_upload")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_uploading")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_downloading")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_complete")).toBe(true);
    expect(shouldAutoHideStatus("conflict")).toBe(false);
    expect(shouldAutoHideStatus("conflict_unresolved")).toBe(true);
  });

});

describe("AutoSyncStatusSurface No Connected Peers", () => {
  it("treats the no-peers warning as terminal with auto-hide", () => {
    expect(isSyncthingActiveStatus("syncthing_no_peers")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_no_peers")).toBe(true);
  });

});

describe("AutoSyncStatusSurface Auto-hide Timing", () => {
  let mockStatusView: any;
  let surface: any;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {
      setTimeout: setTimeout,
      clearTimeout: clearTimeout,
    });
    mockStatusView = {
      setContext: vi.fn(),
      sync: vi.fn(),
      destroy: vi.fn(),
    };
    surface = createAutoSyncStatusSurface(mockStatusView);
  });

  afterEach(() => {
    surface.dispose();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });


  it("sets the hidden context once when hiding the surface", () => {
    surface.hide();

    expect(mockStatusView.setContext).toHaveBeenCalledTimes(1);
    expect(mockStatusView.setContext).toHaveBeenCalledWith(
      expect.objectContaining({ visible: false }),
    );
  });

  it("keeps conflict visible and auto-hides conflict_unresolved normally", () => {

    surface.publish("conflict", { source: "lifecycle_start" });
    mockStatusView.sync.mockClear();
    vi.advanceTimersByTime(RESULT_HIDE_DELAY_MS + 1);
    expect(mockStatusView.sync).not.toHaveBeenCalledWith(
      expect.objectContaining({ visible: false }),
    );

    surface.complete(
      { status: "skipped", reason: "conflict_unresolved", game: "Hades" },
      { lifecycle: "lifecycle_start", gameName: "Hades", appID: "1145300", tracked: true },
    );
    expect(mockStatusView.sync).toHaveBeenCalledWith(
      expect.objectContaining({ status: "conflict_unresolved", visible: true }),
    );
    vi.advanceTimersByTime(RESULT_HIDE_DELAY_MS);
    expect(mockStatusView.sync).toHaveBeenCalledWith(
      expect.objectContaining({ status: "conflict_unresolved", visible: false }),
    );
  });

  it("publishes the disabled notice on both start and exit, and auto-hides it", () => {
    const disabledResult = {
      status: "skipped",
      reason: "game_sync_disabled",
      game: "Hades",
    };

    surface.complete(disabledResult, {
      lifecycle: "lifecycle_start",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });
    expect(mockStatusView.sync).toHaveBeenCalledWith(
      expect.objectContaining({ status: "game_sync_disabled", visible: true }),
    );

    mockStatusView.sync.mockClear();
    surface.publish("checking", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });
    vi.advanceTimersByTime(0);
    mockStatusView.sync.mockClear();
    const leaveDetailsPage = surface.registerDetailsPage("1145300");
    surface.complete(disabledResult, {
      lifecycle: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });
    expect(mockStatusView.sync).toHaveBeenCalledWith(
      expect.objectContaining({ status: "game_sync_disabled", visible: true }),
    );

    // The exit notice must still auto-hide; a lingering strip after quitting
    // was a real defect fixed earlier and must not regress.
    mockStatusView.sync.mockClear();
    vi.advanceTimersByTime(RESULT_HIDE_DELAY_MS + 1);
    expect(mockStatusView.sync).toHaveBeenCalledWith(
      expect.objectContaining({ visible: false }),
    );
    leaveDetailsPage();
  });


  it("auto-hides has_backup after RESULT_HIDE_DELAY_MS if no syncthing syncs occur", () => {
    surface.publish("has_backup", { source: "rpc_result", resultStatus: "backed_up" });
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "has_backup", visible: true }));

    mockStatusView.sync.mockClear();
    vi.advanceTimersByTime(RESULT_HIDE_DELAY_MS);
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "has_backup", visible: false }));
  });
});
