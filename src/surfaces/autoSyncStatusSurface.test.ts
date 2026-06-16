import { describe, it, expect, vi } from "vitest";
import {
  autoSyncStatusText,
  isSyncthingActiveStatus,
  iconSvgForAutoSyncStatus,
  shouldAutoHideStatus,
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
