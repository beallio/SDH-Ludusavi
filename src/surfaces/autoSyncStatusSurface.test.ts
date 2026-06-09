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

  it("should render correct icon for syncthing_pending_upload matching syncthing_uploading", () => {
    const pendingIcon = iconSvgForAutoSyncStatus("syncthing_pending_upload");
    const uploadingIcon = iconSvgForAutoSyncStatus("syncthing_uploading");
    expect(pendingIcon).toBe(uploadingIcon);
    expect(pendingIcon).toContain("<svg");
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

  it("uses the amber warning style and fallback icon treatment", () => {
    const html = renderAutoSyncStatusHtml({
      status: "syncthing_no_peers",
      visible: true,
      source: "rpc_result",
    });
    expect(html).toContain("LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE");
    expect(html).toContain("#f59e0b");
    expect(iconSvgForAutoSyncStatus("syncthing_no_peers")).toBe(
      iconSvgForAutoSyncStatus("syncthing_unavailable"),
    );
  });
});
