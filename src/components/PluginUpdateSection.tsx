import React, { useCallback, useEffect, useRef, useState } from "react";
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
const logRpc = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");

function logUpdate(traceId: string | null, stage: string, details?: any) {
  const detailsStr = details
    ? Object.entries(details)
        .map(([k, v]) => `${k}=${v}`)
        .join(", ")
    : "";
  const prefix = traceId ? `trace_id=${traceId}` : "trace_id=none";
  const message = `${stage}: ${prefix}${detailsStr ? ", " + detailsStr : ""}`;
  try {
    void logRpc("info", message, "update");
  } catch (_) {}
}

function generateUpdateTraceId(): string {
  return "tr-" + Date.now() + "-" + Math.random().toString(36).substr(2, 9);
}

const buttonRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "8px",
  minHeight: "20px",
  lineHeight: "20px",
};

const spinnerSlotStyle: React.CSSProperties = {
  width: "16px",
  height: "16px",
  flex: "0 0 16px",
  overflow: "hidden",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

export interface PluginUpdateSectionProps {
  currentVersion: string;
  updateChannel: UpdateChannel;
  automaticUpdateChecks: boolean;
  onToggleUpdateChannel: (enabled: boolean) => void;
  onToggleAutomaticUpdateChecks: (enabled: boolean) => void;
}

interface InstalledOverride {
  version: string;
  channel: UpdateChannel;
  preInstallVersion: string;
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
  const [isHandoffPending, setIsHandoffPending] = useState(false);
  const [checkResult, setCheckResult] = useState<UpdateCheckResult | null>(null);
  const [candidate, setCandidate] = useState<PluginUpdateCandidate | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [installedReleasePublishedAt, setInstalledReleasePublishedAt] = useState<string | null>(null);
  const [installedOverride, setInstalledOverride] = useState<InstalledOverride | null>(null);
  const hasChecked = useRef(false);
  const inFlightCheck = useRef<Promise<any> | null>(null);

  // Effective version used for display and RPC calls.
  // After a successful handoff, shows the installed target version until the
  // real currentVersion prop updates (which clears the override).
  const effectiveCurrentVersion = installedOverride?.version ?? currentVersion;

  const checkForUpdates = useCallback(
    async (opts: { force: boolean; notify: boolean }) => {
      if (!currentVersion || currentVersion === "Loading...") {
        return;
      }
      if (inFlightCheck.current) {
        logUpdate(null, "check_reuse", { channel: updateChannel, elapsed_ms: 0 });
        return inFlightCheck.current;
      }

      const promise = (async () => {
        const checkStart = performance.now();
        setIsChecking(true);
        setErrorMsg(null);
        logUpdate(null, "check_start", { channel: updateChannel });
        try {
          const res = await checkForPluginUpdateCall(effectiveCurrentVersion, opts.force);
          const elapsed_ms = Math.round(performance.now() - checkStart);
          setCheckResult(res);
          if (res.status === "failed") {
            logUpdate(null, "check_failed", { message: res.message || "unknown", elapsed_ms });
            setErrorMsg(res.message || "Failed to check for updates");
            if (opts.notify && opts.force) {
              toaster.toast({
                title: "Update Check Failed",
                body: res.message || "Failed to check for updates",
                duration: 3000
              });
            }
          } else if (res.status === "available") {
            // Coerce stale available results: if the server says a version is available
            // that matches what we just installed, treat it as current.
            if (installedOverride && res.candidate?.version === installedOverride.version) {
              logUpdate(null, "check_success", { status: "current", stale_coerced: true, elapsed_ms });
              setCheckResult({ status: "current", checked_at: res.checked_at, channel: updateChannel });
              setCandidate(null);
            } else {
              logUpdate(null, "check_success", { status: "available", version: res.candidate?.version, elapsed_ms });
              setCandidate(res.candidate);
            }
          } else {
            logUpdate(null, "check_success", { status: "current", elapsed_ms });
            setCandidate(null);
          }
          return res;
        } catch (err) {
          const elapsed_ms = Math.round(performance.now() - checkStart);
          const msg = err instanceof Error ? err.message : String(err);
          logUpdate(null, "check_failed", { message: msg, elapsed_ms });
          setErrorMsg(msg);
          if (opts.notify && opts.force) {
            toaster.toast({
              title: "Update Check Failed",
              body: msg,
              duration: 3000
            });
          }
          const failedRes: UpdateCheckResult = {
            status: "failed",
            checked_at: new Date().toISOString(),
            message: msg
          };
          setCheckResult(failedRes);
          return failedRes;
        } finally {
          setIsChecking(false);
          inFlightCheck.current = null;
        }
      })();

      inFlightCheck.current = promise;
      return promise;
    },
    [currentVersion, updateChannel, installedOverride, effectiveCurrentVersion]
  );

  // Shared post-install success helper. Called from both handoff success paths:
  // immediate (installerPromise resolved before 3 s) and delayed (after timeout).
  const handleHandoffSuccess = React.useCallback(
    (version: string, channel: UpdateChannel, traceId: string, handoffStart: number) => {
      logUpdate(traceId, "handoff_resolved", { status: "success", elapsed_ms: Math.round(performance.now() - handoffStart) });
      setInstalledOverride({ version, channel, preInstallVersion: currentVersion });
      setCheckResult({ status: "current", checked_at: new Date().toISOString(), channel });
      setCandidate(null);
      setErrorMsg(null);
      setIsInstalling(false);
      setIsHandoffPending(false);
      toaster.toast({
        title: "Installation Initiated",
        body: `Requested installation of v${version} via Decky Loader.`,
        duration: 3000
      });
    },
    [currentVersion]
  );

  // Clear the installed override once the real loaded version matches or exceeds
  // what we installed — or diverges unexpectedly. This ensures the override is
  // only active while waiting for Decky to reload the plugin.
  useEffect(() => {
    if (!installedOverride) return;
    if (
      currentVersion &&
      currentVersion !== "Loading..." &&
      currentVersion !== installedOverride.preInstallVersion
    ) {
      setInstalledOverride(null);
    }
  }, [currentVersion, installedOverride]);

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
    setIsHandoffPending(false);
    setErrorMsg(null);

    const updateTraceId = generateUpdateTraceId();
    logUpdate(updateTraceId, "install_clicked", { version: targetCandidate.version });

    try {
      const revalStart = performance.now();
      logUpdate(updateTraceId, "revalidate_start", { tag: targetCandidate.tag });
      const revalRes = await revalidatePluginUpdateCall(targetCandidate);
      const revalElapsed = Math.round(performance.now() - revalStart);
      if (revalRes.status === "failed" || !revalRes.version) {
        logUpdate(updateTraceId, "revalidate_failed", { message: revalRes.message || "unknown", elapsed_ms: revalElapsed });
        throw new Error(revalRes.message || "Revalidation failed");
      }
      logUpdate(updateTraceId, "revalidate_success", { version: revalRes.version, elapsed_ms: revalElapsed });

      const installType =
        targetCandidate.action === "downgrade_to_stable"
          ? INSTALL_TYPE_DOWNGRADE
          : INSTALL_TYPE_UPDATE;

      const payload = { ...revalRes, updateTraceId };

      const recordStart = performance.now();
      logUpdate(updateTraceId, "record_install_start", { version: revalRes.version });
      await recordUpdateInstallRequestedCall(payload);
      logUpdate(updateTraceId, "record_install_success", { version: revalRes.version, elapsed_ms: Math.round(performance.now() - recordStart) });

      const handoffStart = performance.now();
      logUpdate(updateTraceId, "handoff_start", {
        version: revalRes.version,
        sha256_prefix: revalRes.sha256 ? revalRes.sha256.slice(0, 8) : "none"
      });

      let handoffTimerFired = false;
      const handoffTimer = new Promise<void>((resolve) => {
        setTimeout(() => {
          handoffTimerFired = true;
          resolve();
        }, 3000);
      });

      const installerPromise = invokeDeckyInstaller(
        revalRes.artifact_url,
        revalRes.version,
        revalRes.sha256,
        installType,
        updateTraceId
      );

      await Promise.race([installerPromise, handoffTimer]);

      if (handoffTimerFired) {
        logUpdate(updateTraceId, "handoff_pending", { status: "installer_handoff_pending", elapsed_ms: Math.round(performance.now() - handoffStart) });
        setIsHandoffPending(true);
        void (async () => {
          try {
            await installerPromise;
            handleHandoffSuccess(revalRes.version, revalRes.channel as UpdateChannel, updateTraceId, handoffStart);
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            logUpdate(updateTraceId, "handoff_rejected", { message: msg, elapsed_ms: Math.round(performance.now() - handoffStart) });
            setIsInstalling(false);
            setIsHandoffPending(false);
            setErrorMsg(msg);
            toaster.toast({
              title: "Installation Failed",
              body: msg,
              duration: 4000
            });
          }
        })();
      } else {
        await installerPromise;
        handleHandoffSuccess(revalRes.version, revalRes.channel as UpdateChannel, updateTraceId, handoffStart);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg);
      setIsInstalling(false);
      setIsHandoffPending(false);
      toaster.toast({
        title: "Installation Failed",
        body: msg,
        duration: 4000
      });
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

  const isLocalBuild = effectiveCurrentVersion.includes("+");
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
            {effectiveCurrentVersion} {isLocalBuild ? "(Local Build)" : ""}
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
              <div style={buttonRowStyle}>
                {isInstalling ? (
                  <>
                    <div style={spinnerSlotStyle}>
                      <Spinner size="small" />
                    </div>
                    <span>{isHandoffPending ? "Waiting for Decky..." : "Preparing..."}</span>
                  </>
                ) : (
                  <span>{getActionText(candidate)}</span>
                )}
              </div>
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
