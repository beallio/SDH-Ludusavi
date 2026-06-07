import { describe, it, expect, vi } from "vitest";
import {
  autoSyncStatusText,
  isSyncthingActiveStatus,
  iconSvgForAutoSyncStatus,
} from "./autoSyncStatusSurface";

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
});
