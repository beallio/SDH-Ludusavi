import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  autoSyncStatusText,
  isSyncthingActiveStatus,
  iconSvgForAutoSyncStatus,
  shouldAutoHideStatus,
  createAutoSyncStatusSurface,
  HAS_BACKUP_MIN_DWELL_MS,
  RESULT_HIDE_DELAY_MS,
} from "./autoSyncStatusSurface";
import { renderAutoSyncStatusHtml } from "./autoSyncStatusRenderer";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {},
}));

describe("AutoSyncStatusSurface Status Pending Upload", () => {
  it("should have correct display text for syncthing_pending_upload", () => {
    expect(autoSyncStatusText.syncthing_pending_upload).toBe("SYNCTHING PREPARING");
  });

  it("should consider syncthing_pending_upload as active status", () => {
    expect(isSyncthingActiveStatus("syncthing_pending_upload")).toBe(true);
    expect(isSyncthingActiveStatus("syncthing_uploading")).toBe(true);
    expect(isSyncthingActiveStatus("syncthing_downloading")).toBe(true);
    expect(isSyncthingActiveStatus("checking")).toBe(false);
  });

  it("renders a spinner-ring cloud icon for syncthing_pending_upload", () => {
    const pendingIcon = iconSvgForAutoSyncStatus("syncthing_pending_upload");
    expect(pendingIcon).toContain("<svg");
    expect(pendingIcon).toContain('class="spinner-ring"');
    // Static cloud path from IoCloudCircleOutline stays outside the spinning group.
    expect(pendingIcon).toContain("M333.88 240.59");
    expect(pendingIcon).not.toBe(iconSvgForAutoSyncStatus("syncthing_uploading"));
  });

  it("tightens the pending icon viewBox so the ring fills the box like sibling icons", () => {
    const pendingIcon = iconSvgForAutoSyncStatus("syncthing_pending_upload");
    // Ring outer edge spans 48..464 (circle 64..448 plus 32-wide stroke), so the
    // viewBox must crop to that 416-unit window centered on (256, 256).
    expect(pendingIcon).toContain('viewBox="48 48 416 416"');
  });

  it("applies the ring-spin animation class only to syncthing_pending_upload", () => {
    const pendingHtml = renderAutoSyncStatusHtml({
      status: "syncthing_pending_upload",
      visible: true,
      source: "rpc_result",
    });
    expect(pendingHtml).toContain('class="icon icon-spin-ring"');
    expect(pendingHtml).toContain(".icon-spin-ring .spinner-ring");

    const completeHtml = renderAutoSyncStatusHtml({
      status: "syncthing_complete",
      visible: true,
      source: "rpc_result",
    });
    expect(completeHtml).not.toContain('class="icon icon-spin-ring"');
    
    const completeIcon = iconSvgForAutoSyncStatus("syncthing_complete");
    expect(completeIcon).toContain("<svg");
  });

  it("keeps active Syncthing states visible until the monitor replaces them", () => {
    expect(shouldAutoHideStatus("syncthing_pending_upload")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_uploading")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_downloading")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_complete")).toBe(true);
  });

  it("defines distinct local-backup warnings", () => {
    expect(autoSyncStatusText.syncthing_unavailable).toBe(
      "LOCAL BACKUP SAVED - SYNCTHING UNAVAILABLE",
    );
    expect(autoSyncStatusText.syncthing_folder_not_found).toBe(
      "LOCAL BACKUP SAVED - PATH NOT SHARED",
    );
  });

  it("renders a 22px filling icon box", () => {
    const html = renderAutoSyncStatusHtml({
      status: "checking",
      visible: true,
      source: "rpc_result",
    });
    expect(html).toContain("width: 22px; height: 22px;");
    expect(html).toContain(".icon svg { width: 100%; height: 100%; display: block; }");
  });
});

describe("AutoSyncStatusSurface Uploading Arrow Animation", () => {
  it("renders the uploading cloud with a clipped fill rect over the arrow cutout", () => {
    const uploadIcon = iconSvgForAutoSyncStatus("syncthing_uploading");
    expect(uploadIcon).toContain("<svg");
    // Cloud body with the arrow cutout from IoMdCloudUpload stays intact.
    expect(uploadIcon).toContain("M403.002 217.001");
    expect(uploadIcon).toContain("M288 276v76h-64v-76h-68l100-100 100 100h-68z");
    expect(uploadIcon).toContain("<clipPath");
    expect(uploadIcon).toContain('class="upload-arrow-fill"');
  });

  it("animates the arrow fill upward only for syncthing_uploading", () => {
    const uploadingHtml = renderAutoSyncStatusHtml({
      status: "syncthing_uploading",
      visible: true,
      source: "rpc_result",
    });
    expect(uploadingHtml).toContain("@keyframes arrow-fill-up");
    expect(uploadingHtml).toContain(".upload-arrow-fill");

    const downloadingHtml = renderAutoSyncStatusHtml({
      status: "syncthing_downloading",
      visible: true,
      source: "rpc_result",
    });
    expect(downloadingHtml).not.toContain('class="upload-arrow-fill"');
    expect(downloadingHtml).toContain('class="download-arrow-fill"');
    expect(downloadingHtml).toContain("@keyframes arrow-fill-down");
  });
});

describe("AutoSyncStatusSurface No Connected Peers", () => {
  it("renders the no-peers warning with the exact selected text", () => {
    expect(autoSyncStatusText.syncthing_no_peers).toBe(
      "LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE",
    );
  });

  it("treats the no-peers warning as terminal with auto-hide", () => {
    expect(isSyncthingActiveStatus("syncthing_no_peers")).toBe(false);
    expect(shouldAutoHideStatus("syncthing_no_peers")).toBe(true);
  });

  it("uses the amber warning style and cloud-with-X icon treatment", () => {
    const html = renderAutoSyncStatusHtml({
      status: "syncthing_no_peers",
      visible: true,
      source: "rpc_result",
    });
    expect(html).toContain("LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE");
    expect(html).toContain("#f59e0b");
    
    const icon = iconSvgForAutoSyncStatus("syncthing_unavailable");
    expect(icon).toContain("M403.002 217.001");
    expect(icon).toContain("M196 232 316 352");
    expect(icon).not.toContain('r="8.8"');
    expect(iconSvgForAutoSyncStatus("syncthing_no_peers")).toBe(icon);
    expect(iconSvgForAutoSyncStatus("syncthing_folder_not_found")).toBe(icon);
  });
});

describe("AutoSyncStatusSurface Local Backup Arrow Animation", () => {
  it("renders the backing_up circle with an arrow cutout and clipped fill rect", () => {
    const backupIcon = iconSvgForAutoSyncStatus("backing_up");
    expect(backupIcon).toContain("<svg");
    expect(backupIcon).toContain("<clipPath");
    expect(backupIcon).toContain('id="backup-arrow-clip"');
    expect(backupIcon).toContain('class="backup-arrow-fill"');
    expect(backupIcon).toContain('fill-rule="evenodd"');
  });

  it("shares the animated icon with restoring, rotated 180 degrees", () => {
    const restoreIcon = iconSvgForAutoSyncStatus("restoring");
    expect(restoreIcon).toContain('class="backup-arrow-fill"');
    expect(restoreIcon).toContain("rotate(180deg)");
    expect(iconSvgForAutoSyncStatus("backing_up")).not.toContain("rotate(180deg)");
  });

  it("keeps the static fallback icon for warning statuses", () => {
    expect(iconSvgForAutoSyncStatus("backing_up")).not.toBe(
      iconSvgForAutoSyncStatus("syncthing_unavailable"),
    );
    expect(iconSvgForAutoSyncStatus("syncthing_no_peers")).not.toContain(
      "backup-arrow-fill",
    );
    expect(iconSvgForAutoSyncStatus("conflict")).not.toContain("backup-arrow-fill");
  });

  it("defines the backup arrow fill keyframes in the rendered html", () => {
    const backingUpHtml = renderAutoSyncStatusHtml({
      status: "backing_up",
      visible: true,
      source: "rpc_result",
    });
    expect(backingUpHtml).toContain("@keyframes backup-arrow-fill-up");
    expect(backingUpHtml).toContain(".backup-arrow-fill");
  });

  it("renders the save-conflict status in amber", () => {
    const html = renderAutoSyncStatusHtml({ status: "conflict", visible: true, source: "rpc_result" });
    expect(html).toContain("#f59e0b");
  });
});

describe("AutoSyncStatusSurface Dwell Time", () => {
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

  const completePostGameBackup = () => {
    surface.complete(
      { status: "backed_up", game: "Hades" },
      { lifecycle: "lifecycle_exit", gameName: "Hades", appID: "1145300", tracked: true },
    );
  };

  it("delays the post-game Syncthing handoff behind the backed-up dwell time", () => {
    completePostGameBackup();
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "has_backup" }));
    
    mockStatusView.sync.mockClear();
    surface.publish("syncthing_pending_upload", { source: "lifecycle_exit" });
    expect(mockStatusView.sync).not.toHaveBeenCalled();

    vi.advanceTimersByTime(HAS_BACKUP_MIN_DWELL_MS);
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "syncthing_pending_upload" }));
  });

  it("does not apply the post-game dwell to pre-game current or restored results", () => {
    surface.complete(
      { status: "skipped", reason: "local_current", game: "Hades" },
      { lifecycle: "lifecycle_start", gameName: "Hades", appID: "1145300", tracked: true },
    );
    mockStatusView.sync.mockClear();
    surface.publish("syncthing_downloading", { source: "lifecycle_start" });
    expect(mockStatusView.sync).toHaveBeenCalledWith(
      expect.objectContaining({ status: "syncthing_downloading" }),
    );

    mockStatusView.sync.mockClear();
    surface.complete(
      { status: "restored", game: "Hades" },
      { lifecycle: "lifecycle_start", gameName: "Hades", appID: "1145300", tracked: true },
    );
    mockStatusView.sync.mockClear();
    surface.publish("syncthing_uploading", { source: "lifecycle_start" });
    expect(mockStatusView.sync).toHaveBeenCalledWith(
      expect.objectContaining({ status: "syncthing_uploading" }),
    );
  });

  it("coalesces multiple syncthing publishes during the dwell time", () => {
    completePostGameBackup();
    mockStatusView.sync.mockClear();

    surface.publish("syncthing_pending_upload", { source: "lifecycle_exit" });
    surface.publish("syncthing_uploading", { source: "lifecycle_exit" });

    vi.advanceTimersByTime(HAS_BACKUP_MIN_DWELL_MS);
    expect(mockStatusView.sync).toHaveBeenCalledTimes(1);
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "syncthing_uploading" }));
  });

  it("applies error immediately and cancels deferral", () => {
    completePostGameBackup();
    mockStatusView.sync.mockClear();

    surface.publish("syncthing_pending_upload", { source: "lifecycle_exit" });
    surface.publish("error", { source: "rpc_result" });
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "error" }));

    mockStatusView.sync.mockClear();
    vi.advanceTimersByTime(HAS_BACKUP_MIN_DWELL_MS);
    expect(mockStatusView.sync).not.toHaveBeenCalled();
  });

  it("cancels deferral on hide", () => {
    completePostGameBackup();
    mockStatusView.sync.mockClear();

    surface.publish("syncthing_pending_upload", { source: "lifecycle_exit" });
    surface.hide();

    mockStatusView.sync.mockClear();
    vi.advanceTimersByTime(HAS_BACKUP_MIN_DWELL_MS);
    expect(mockStatusView.sync).not.toHaveBeenCalled();
  });

  it("auto-hides has_backup after RESULT_HIDE_DELAY_MS if no syncthing syncs occur", () => {
    surface.publish("has_backup", { source: "rpc_result", resultStatus: "backed_up" });
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "has_backup", visible: true }));

    mockStatusView.sync.mockClear();
    vi.advanceTimersByTime(RESULT_HIDE_DELAY_MS);
    expect(mockStatusView.sync).toHaveBeenCalledWith(expect.objectContaining({ status: "has_backup", visible: false }));
  });
});
