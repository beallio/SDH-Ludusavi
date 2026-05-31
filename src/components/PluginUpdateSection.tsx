import { useCallback, useEffect, useRef, useState } from "react";
import {
  ButtonItem,
  ConfirmModal,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  ToggleField,
  Spinner,
  Navigation
} from "@decky/ui";
import { callable, toaster } from "@decky/api";
import { FaExclamationTriangle } from "react-icons/fa";
import { IoMdRefresh } from "react-icons/io";

import { PluginUpdateCandidate, UpdateCheckResult, UpdateChannel } from "../types";
import {
  isDeckyInstallerAvailable,
  invokeDeckyInstaller,
  INSTALL_TYPE_UPDATE,
  INSTALL_TYPE_DOWNGRADE
} from "../utils/deckyInstaller";

const checkForPluginUpdateCall = callable<[currentVersion: string, force: boolean], UpdateCheckResult>("check_for_plugin_update");
const revalidatePluginUpdateCall = callable<[candidate: any], any>("revalidate_plugin_update");
const recordUpdateInstallRequestedCall = callable<[candidate: any], any>("record_update_install_requested");
const getUpdateCheckContextCall = callable<[], any>("get_update_check_context");

export interface PluginUpdateSectionProps {
  currentVersion: string;
  updateChannel: UpdateChannel;
  automaticUpdateChecks: boolean;
  onToggleUpdateChannel: (enabled: boolean) => void;
  onToggleAutomaticUpdateChecks: (enabled: boolean) => void;
}

export function PluginUpdateSection({
  currentVersion,
  updateChannel,
  automaticUpdateChecks,
  onToggleUpdateChannel,
  onToggleAutomaticUpdateChecks
}: PluginUpdateSectionProps) {
  const [isChecking, setIsChecking] = useState(false);
  const [isInstalling, setIsInstalling] = useState(false);
  const [checkResult, setCheckResult] = useState<UpdateCheckResult | null>(null);
  const [candidate, setCandidate] = useState<PluginUpdateCandidate | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [installedReleasePublishedAt, setInstalledReleasePublishedAt] = useState<string | null>(null);
  const hasChecked = useRef(false);

  const checkForUpdates = useCallback(
    async (opts: { force: boolean; notify: boolean }) => {
      if (isChecking || !currentVersion || currentVersion === "Loading...") {
        return;
      }
      setIsChecking(true);
      setErrorMsg(null);
      try {
        const res = await checkForPluginUpdateCall(currentVersion, opts.force);
        setCheckResult(res);
        if (res.status === "failed") {
          setErrorMsg(res.message || "Failed to check for updates");
          if (opts.notify && opts.force) {
            toaster.toast({
              title: "Update Check Failed",
              body: res.message || "Failed to check for updates",
              duration: 3000
            });
          }
        } else if (res.status === "available") {
          setCandidate(res.candidate);
        } else {
          setCandidate(null);
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setErrorMsg(msg);
        if (opts.notify && opts.force) {
          toaster.toast({
            title: "Update Check Failed",
            body: msg,
            duration: 3000
          });
        }
      } finally {
        setIsChecking(false);
      }
    },
    [isChecking, currentVersion]
  );

  // Reconcile and load cache on mount
  useEffect(() => {
    let active = true;
    async function loadCache() {
      try {
        const ctx = await getUpdateCheckContextCall();
        if (!active) return;
        if (ctx) {
          if (ctx.installed_release_published_at) {
            setInstalledReleasePublishedAt(ctx.installed_release_published_at);
          }
          if (ctx.last_checked_at && ctx.last_checked_channel === updateChannel) {
            const hasPending = !!ctx.pending_update_install;
            if (ctx.last_available_tag && !hasPending) {
              // Trigger a non-blocking check to restore candidate state
              void checkForUpdates({ force: false, notify: false });
            }
          }
        }
      } catch (err) {
        // Quiet failure on context check
      }
    }
    void loadCache();
    return () => {
      active = false;
    };
  }, [updateChannel]);

  // Run check on mount or when update channel changes
  useEffect(() => {
    if (!currentVersion || currentVersion === "Loading...") {
      return;
    }
    const isFirstMount = !hasChecked.current;
    hasChecked.current = true;

    if (isFirstMount) {
      if (automaticUpdateChecks) {
        void checkForUpdates({ force: false, notify: false });
      }
    } else {
      void checkForUpdates({ force: true, notify: false });
    }
  }, [updateChannel, currentVersion]);

  // Handle automatic check toggle changes
  useEffect(() => {
    if (!automaticUpdateChecks || !currentVersion || currentVersion === "Loading...") {
      return;
    }
    void checkForUpdates({ force: false, notify: false });
  }, [automaticUpdateChecks, currentVersion]);

  const handleToggleChannel = (checked: boolean) => {
    if (checked) {
      showModal(
        <ConfirmModal
          strTitle="Enable Development Releases?"
          onOK={() => onToggleUpdateChannel(true)}
        >
          <div style={{ fontSize: "14px", color: "#cbd5e1" }}>
            Includes prerelease builds intended for testing. These builds may contain regressions.
          </div>
        </ConfirmModal>
      );
    } else {
      onToggleUpdateChannel(false);
    }
  };

  const handleInstall = async (targetCandidate: PluginUpdateCandidate) => {
    if (isInstalling) return;
    setIsInstalling(true);
    setErrorMsg(null);
    try {
      const revalRes = await revalidatePluginUpdateCall(targetCandidate);
      if (revalRes.status === "failed" || !revalRes.version) {
        throw new Error(revalRes.message || "Revalidation failed");
      }

      const installType =
        targetCandidate.action === "downgrade_to_stable"
          ? INSTALL_TYPE_DOWNGRADE
          : INSTALL_TYPE_UPDATE;

      await recordUpdateInstallRequestedCall(revalRes);
      await invokeDeckyInstaller(
        revalRes.artifact_url,
        revalRes.version,
        revalRes.sha256,
        installType
      );

      toaster.toast({
        title: "Installation Initiated",
        body: `Requested installation of v${revalRes.version} via Decky Loader.`,
        duration: 3000
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg);
      toaster.toast({
        title: "Installation Failed",
        body: msg,
        duration: 4000
      });
    } finally {
      setIsInstalling(false);
    }
  };

  const handleInstallClick = (targetCandidate: PluginUpdateCandidate) => {
    if (targetCandidate.action === "downgrade_to_stable") {
      showModal(
        <ConfirmModal
          strTitle="Revert to Stable?"
          onOK={() => handleInstall(targetCandidate)}
        >
          <div style={{ fontSize: "14px", color: "#cbd5e1" }}>
            Are you sure you want to revert to stable v{targetCandidate.version}? This is a downgrade and could result in data loss or configuration issues.
          </div>
        </ConfirmModal>
      );
    } else {
      void handleInstall(targetCandidate);
    }
  };

  const isLocalBuild = currentVersion.includes("+");
  const isDeckyAvailable = isDeckyInstallerAvailable();

  const getActionText = (c: PluginUpdateCandidate) => {
    switch (c.action) {
      case "move_to_stable":
        return `Move to Stable v${c.version}`;
      case "downgrade_to_stable":
        return `Revert to Stable v${c.version}`;
      default:
        if (c.channel === "development") {
          return `Install development build v${c.version}`;
        }
        return `Update to v${c.version}`;
    }
  };

  return (
    <PanelSection title="Updates">
      <PanelSectionRow>
        <Field label="Installed Version" padding="standard">
          <div style={{ fontSize: "14px", color: "#cbd5e1" }}>
            {currentVersion} {isLocalBuild ? "(Local Build)" : ""}
          </div>
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <ToggleField
          label="Receive development releases"
          description="Includes prerelease builds intended for testing. These builds may contain regressions."
          checked={updateChannel === "development"}
          onChange={handleToggleChannel}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <ToggleField
          label="Automatically check for updates"
          description="Checks in the background while the plugin is loaded."
          checked={automaticUpdateChecks}
          onChange={onToggleAutomaticUpdateChecks}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <Field
          label="Status"
          description={
            checkResult?.checked_at
              ? `Last checked: ${new Date(checkResult.checked_at).toLocaleTimeString()}`
              : undefined
          }
          padding="standard"
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "14px" }}>
            {isChecking && (
              <>
                <Spinner size="small" />
                <span>Checking...</span>
              </>
            )}
            {!isChecking && errorMsg && (
              <span style={{ color: "#f87171" }}>Failed to check</span>
            )}
            {!isChecking && !errorMsg && checkResult?.status === "current" && (
              <span style={{ color: "#4ade80" }}>Up to date</span>
            )}
            {!isChecking && !errorMsg && checkResult?.status === "available" && (
              <span style={{ color: "#60a5fa" }}>
                {candidate?.channel === "development" && currentVersion.includes("dev") && !installedReleasePublishedAt
                  ? "Latest available development build"
                  : "Update available"}
              </span>
            )}
            {!isChecking && !checkResult && (
              <span>Never checked</span>
            )}
          </div>
        </Field>
      </PanelSectionRow>

      {errorMsg && (
        <PanelSectionRow>
          <div style={{ display: "flex", gap: "8px", color: "#f87171", padding: "10px 15px", fontSize: "13px" }}>
            <span style={{ flexShrink: 0, marginTop: "2px", display: "inline-flex" }}>
              <FaExclamationTriangle />
            </span>
            <div>{errorMsg}</div>
          </div>
        </PanelSectionRow>
      )}

      {candidate && (
        <PanelSectionRow>
          <div style={{ padding: "8px 15px", fontSize: "14px", color: "#cbd5e1" }}>
            <div>New version: v{candidate.version} ({candidate.channel})</div>
            {candidate.action === "downgrade_to_stable" && (
              <div style={{ color: "#f87171", fontSize: "12px", marginTop: "4px" }}>
                Warning: Reverting to stable is a downgrade.
              </div>
            )}
          </div>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", padding: "8px 15px" }}>
          {candidate && isDeckyAvailable && (
            <ButtonItem
              layout="below"
              onClick={() => handleInstallClick(candidate)}
              disabled={isChecking || isInstalling}
            >
              {isInstalling ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}>
                  <Spinner size="small" />
                  <span>Preparing...</span>
                </div>
              ) : (
                getActionText(candidate)
              )}
            </ButtonItem>
          )}

          {!isDeckyAvailable && candidate && (
            <div style={{ color: "#f87171", fontSize: "13px", marginBottom: "8px" }}>
              Automatic installation is unavailable in this Decky environment. Install this release manually from GitHub Releases.
            </div>
          )}

          {candidate && (
            <ButtonItem
              layout="below"
              onClick={() => Navigation.NavigateToExternalWeb(candidate.release_url)}
            >
              View Release Notes
            </ButtonItem>
          )}

          <ButtonItem
            layout="below"
            onClick={() => checkForUpdates({ force: true, notify: true })}
            disabled={isChecking || isInstalling}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}>
              <IoMdRefresh />
              <span>Check now</span>
            </div>
          </ButtonItem>
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}
