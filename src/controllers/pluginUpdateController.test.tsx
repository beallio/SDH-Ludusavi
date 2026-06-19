import { describe, it, expect, vi, beforeEach } from "vitest";
import * as ludusaviRpc from "../api/ludusaviRpc";
import * as deckyInstaller from "../utils/deckyInstaller";


let stateIdx = 0;
let states: any[] = [];
let setters: any[] = [];

vi.mock("react", () => ({
  useState: (init: any) => {
    const idx = stateIdx++;
    if (states.length <= idx) {
      states[idx] = init;
      setters[idx] = (v: any) => { states[idx] = typeof v === 'function' ? v(states[idx]) : v; };
    }
    return [states[idx], setters[idx]];
  },
  useEffect: vi.fn(),
  useCallback: (fn: any) => fn,
  useRef: (init: any) => ({ current: init }),
}));

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
  toaster: { toast: vi.fn() }
}));

vi.mock("../api/ludusaviRpc", () => ({
  checkForPluginUpdateCall: vi.fn(),
  clearPendingUpdateInstallCall: vi.fn(),
  confirmUpdateInstallHandoffCall: vi.fn(),
  getUpdateCheckContextCall: vi.fn(),
  recordUpdateInstallRequestedCall: vi.fn(),
  revalidatePluginUpdateCall: vi.fn(),
}));

vi.mock("../utils/deckyInstaller", () => ({
  invokeDeckyInstaller: vi.fn(),
  INSTALL_TYPE_UPDATE: "UPDATE",
  INSTALL_TYPE_DOWNGRADE: "DOWNGRADE",
}));

import { usePluginUpdateController } from "./pluginUpdateController";

describe("PluginUpdateController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stateIdx = 0;
    states = [];
    setters = [];
    vi.mocked(ludusaviRpc.getUpdateCheckContextCall).mockResolvedValue(null as any);
    vi.mocked(ludusaviRpc.checkForPluginUpdateCall).mockResolvedValue({ status: "current", checked_at: "now", channel: "stable" });
  });

  it("fails install and exits installing state if recordUpdateInstallRequestedCall fails", async () => {
    const candidate: any = {
      version: "0.2.0",
      tag: "v0.2.0",
      channel: "stable",
      action: "update",
      artifact_url: "url",
      sha256: "sha"
    };

    vi.mocked(ludusaviRpc.revalidatePluginUpdateCall).mockResolvedValue(candidate);
    vi.mocked(ludusaviRpc.recordUpdateInstallRequestedCall).mockResolvedValue({ status: "failed", message: "disk error" });
    vi.mocked(ludusaviRpc.clearPendingUpdateInstallCall).mockResolvedValue(null as any);

    stateIdx = 0;
    const controller = usePluginUpdateController({
      currentVersion: "0.1.0",
      updateChannel: "stable",
      automaticUpdateChecks: false
    });

    try {
      await controller.install(candidate);
    } catch (e) {}

    expect(ludusaviRpc.revalidatePluginUpdateCall).toHaveBeenCalled();
    expect(ludusaviRpc.recordUpdateInstallRequestedCall).toHaveBeenCalled();
    expect(deckyInstaller.invokeDeckyInstaller).not.toHaveBeenCalled();

    stateIdx = 0;
    const updatedController = usePluginUpdateController({
      currentVersion: "0.1.0",
      updateChannel: "stable",
      automaticUpdateChecks: false
    });

    expect(updatedController.isInstalling).toBe(false);
    expect(updatedController.errorMessage).toBe("disk error");
  });

  it("success path records, hands off, and confirms correctly", async () => {
    const candidate: any = {
      version: "0.2.0",
      tag: "v0.2.0",
      channel: "stable",
      action: "update",
      artifact_url: "url",
      sha256: "sha"
    };

    vi.mocked(ludusaviRpc.revalidatePluginUpdateCall).mockResolvedValue(candidate);
    vi.mocked(ludusaviRpc.recordUpdateInstallRequestedCall).mockResolvedValue({} as any);
    vi.mocked(deckyInstaller.invokeDeckyInstaller).mockResolvedValue(undefined as any);
    vi.mocked(ludusaviRpc.confirmUpdateInstallHandoffCall).mockResolvedValue({} as any);

    stateIdx = 0;
    const controller = usePluginUpdateController({
      currentVersion: "0.1.0",
      updateChannel: "stable",
      automaticUpdateChecks: false
    });

    await controller.install(candidate);

    expect(ludusaviRpc.revalidatePluginUpdateCall).toHaveBeenCalled();
    expect(ludusaviRpc.recordUpdateInstallRequestedCall).toHaveBeenCalled();
    expect(deckyInstaller.invokeDeckyInstaller).toHaveBeenCalled();
    expect(ludusaviRpc.confirmUpdateInstallHandoffCall).toHaveBeenCalled();

    stateIdx = 0;
    const updatedController = usePluginUpdateController({
      currentVersion: "0.1.0",
      updateChannel: "stable",
      automaticUpdateChecks: false
    });

    expect(updatedController.isInstalling).toBe(false);
    expect(updatedController.errorMessage).toBe(null);
  });
});
