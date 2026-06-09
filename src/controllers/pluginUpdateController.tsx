import React, { useState, useRef, useCallback, useEffect } from "react";
import { toaster } from "@decky/api";
import {
  PluginUpdateCandidate,
  UpdateCheckResult,
  UpdateChannel
} from "../types";
import {
  checkForPluginUpdateCall,
  clearPendingUpdateInstallCall,
  confirmUpdateInstallHandoffCall,
  getUpdateCheckContextCall,
  recordUpdateInstallRequestedCall,
  revalidatePluginUpdateCall,
} from "../api/ludusaviRpc";
import {
  invokeDeckyInstaller,
  INSTALL_TYPE_DOWNGRADE,
  INSTALL_TYPE_UPDATE,
} from "../utils/deckyInstaller";
import { callable } from "@decky/api";

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

export const UPDATE_CHECK_UI_TIMEOUT_MS = 60000;

export interface PluginUpdateControllerProps {
  currentVersion: string;
  updateChannel: UpdateChannel;
  automaticUpdateChecks: boolean;
  onInstallVersionConfirmed?: (version: string) => void;
}

interface InstalledOverride {
  version: string;
  channel: UpdateChannel;
  preInstallVersion: string;
}

export type PluginUpdateController = {
  effectiveCurrentVersion: string;
  candidate: PluginUpdateCandidate | null;
  checkResult: UpdateCheckResult | null;
  errorMessage: string | null;
  isChecking: boolean;
  isInstalling: boolean;
  isHandoffPending: boolean;
  installedReleasePublishedAt: string | null;
  checkNow(): Promise<void>;
  install(candidate: PluginUpdateCandidate): Promise<void>;
};

export function usePluginUpdateController({
  currentVersion,
  updateChannel,
  automaticUpdateChecks,
  onInstallVersionConfirmed
}: PluginUpdateControllerProps): PluginUpdateController {
  const [isChecking, setIsChecking] = useState(false);
  const [isInstalling, setIsInstalling] = useState(false);
  const [isHandoffPending, setIsHandoffPending] = useState(false);
  const [checkResult, setCheckResult] = useState<UpdateCheckResult | null>(null);
  const [candidate, setCandidate] = useState<PluginUpdateCandidate | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [installedReleasePublishedAt, setInstalledReleasePublishedAt] = useState<string | null>(null);
  const [installedOverride, setInstalledOverride] = useState<InstalledOverride | null>(null);
  
  const hasChecked = useRef(false);
  const inFlightCheck = useRef<Promise<any> | null>(null);
  const pendingInstallVersion = useRef<string | null>(null);
  const hydratedPendingInstallVersion = useRef<string | null>(null);

  const activeCheckId = useRef(0);
  const checkTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [contextHydrated, setContextHydrated] = useState(false);
  const skipInitialCheck = useRef(false);
  const automaticCheckToggleHydrated = useRef(false);

  const effectiveCurrentVersion = installedOverride?.version ?? currentVersion;

  const clearCheckTimeout = useCallback(() => {
    if (checkTimeoutRef.current !== null) {
      clearTimeout(checkTimeoutRef.current);
      checkTimeoutRef.current = null;
    }
  }, []);

  const enterPostInstallGuard = useCallback(
    (version: string, channel: UpdateChannel, preInstall?: string) => {
      activeCheckId.current += 1;
      clearCheckTimeout();
      inFlightCheck.current = null;
      setIsChecking(false);
      setInstalledOverride({
        version,
        channel,
        preInstallVersion: preInstall ?? currentVersion
      });
      pendingInstallVersion.current = version;
      setCheckResult({
        status: "current",
        checked_at: new Date().toISOString(),
        channel
      });
      setCandidate(null);
      setErrorMessage(null);
    },
    [currentVersion, clearCheckTimeout]
  );

  const finishCheck = useCallback((checkId: number) => {
    if (checkId === activeCheckId.current) {
      setIsChecking(false);
      inFlightCheck.current = null;
      clearCheckTimeout();
    }
  }, [clearCheckTimeout]);

  const checkForUpdates = useCallback(
    async (opts: { force: boolean; notify: boolean; source: "automatic" | "manual" }) => {
      if (!effectiveCurrentVersion || effectiveCurrentVersion === "Loading...") {
        return;
      }
      if (opts.source === "automatic" && (installedOverride || pendingInstallVersion.current)) {
        logUpdate(null, "automatic_check_suppressed_pending_install");
        return;
      }
      if (inFlightCheck.current) {
        logUpdate(null, "check_reuse", { channel: updateChannel, elapsed_ms: 0 });
        return inFlightCheck.current;
      }

      activeCheckId.current += 1;
      const checkId = activeCheckId.current;

      const promise = (async () => {
        const checkStart = performance.now();
        setIsChecking(true);
        setErrorMessage(null);
        logUpdate(null, "check_start", { channel: updateChannel });

        clearCheckTimeout();
        checkTimeoutRef.current = setTimeout(() => {
          if (activeCheckId.current === checkId) {
            activeCheckId.current += 1;
            setIsChecking(false);
            inFlightCheck.current = null;
            setErrorMessage("Update check interrupted. Check again.");
            setCheckResult({
              status: "failed",
              checked_at: new Date().toISOString(),
              message: "Update check interrupted. Check again."
            });
            logUpdate(null, "check_timeout", { checkId });
          }
        }, UPDATE_CHECK_UI_TIMEOUT_MS);

        try {
          const res = await checkForPluginUpdateCall(effectiveCurrentVersion, opts.force);

          if (activeCheckId.current !== checkId) {
            return { status: "failed", message: "stale" } as any;
          }

          const elapsed_ms = Math.round(performance.now() - checkStart);
          setCheckResult(res);
          if (res.status === "failed") {
            logUpdate(null, "check_failed", { message: res.message || "unknown", elapsed_ms });
            setErrorMessage(res.message || "Failed to check for updates");
            if (opts.notify && opts.force) {
              toaster.toast({
                title: "Update Check Failed",
                body: res.message || "Failed to check for updates",
                duration: 3000
              });
            }
          } else if (res.status === "available") {
            const candidateVersion = res.candidate?.version;
            const isStale =
              (installedOverride && candidateVersion === installedOverride.version) ||
              candidateVersion === pendingInstallVersion.current ||
              candidateVersion === effectiveCurrentVersion;
            if (isStale) {
              logUpdate(null, "check_success", { status: "current", stale_coerced: true, elapsed_ms });
              setCheckResult({ status: "current", checked_at: res.checked_at, channel: updateChannel });
              setCandidate(null);
            } else {
              logUpdate(null, "check_success", { status: "available", version: candidateVersion, elapsed_ms });
              setCandidate(res.candidate);
            }
          } else {
            logUpdate(null, "check_success", { status: "current", elapsed_ms });
            setCandidate(null);
          }
          return res;
        } catch (err) {
          if (activeCheckId.current !== checkId) {
            return { status: "failed", message: "stale" } as any;
          }

          const elapsed_ms = Math.round(performance.now() - checkStart);
          const msg = err instanceof Error ? err.message : String(err);
          logUpdate(null, "check_failed", { message: msg, elapsed_ms });
          setErrorMessage(msg);
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
          finishCheck(checkId);
        }
      })();

      inFlightCheck.current = promise;
      return promise;
    },
    [currentVersion, updateChannel, installedOverride, effectiveCurrentVersion, clearCheckTimeout, finishCheck]
  );

  const checkNow = useCallback(async () => {
    await checkForUpdates({ force: true, notify: true, source: "manual" });
  }, [checkForUpdates]);

  const handleHandoffSuccess = React.useCallback(
    async (version: string, channel: UpdateChannel, traceId: string, handoffStart: number) => {
      enterPostInstallGuard(version, channel);
      // activeCheckId.current, setIsChecking(false), clearCheckTimeout
      try {
        await confirmUpdateInstallHandoffCall(version);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        logUpdate(traceId, "handoff_confirm_failed", { message: msg });
      }
      logUpdate(traceId, "handoff_resolved", { status: "success", elapsed_ms: Math.round(performance.now() - handoffStart) });
      setIsInstalling(false);
      setIsHandoffPending(false);
      onInstallVersionConfirmed?.(version);
      toaster.toast({
        title: "Installation Initiated",
        body: `Requested installation of v${version} via Decky Loader.`,
        duration: 3000
      });
    },
    [currentVersion, onInstallVersionConfirmed, enterPostInstallGuard]
  );

  useEffect(() => {
    if (!installedOverride) return;
    // currentVersion !== installedOverride.version
    if (
      currentVersion &&
      currentVersion !== "Loading..." &&
      (currentVersion !== installedOverride.preInstallVersion ||
       currentVersion === installedOverride.version)
    ) {
      setInstalledOverride(null);
      pendingInstallVersion.current = null;
    }
  }, [currentVersion, installedOverride]);

  useEffect(() => {
    return () => {
      clearCheckTimeout();
    };
  }, [clearCheckTimeout]);

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
          const pendingInstall = ctx.pending_update_install;
          if (
            pendingInstall?.version &&
            ctx.effective_installed_version === pendingInstall.version &&
            hydratedPendingInstallVersion.current !== pendingInstall.version
          ) {
            const pendingChannel: UpdateChannel =
              pendingInstall.channel === "development" ? "development" : "stable";
            hydratedPendingInstallVersion.current = pendingInstall.version;
            setInstalledOverride({
              version: pendingInstall.version,
              channel: pendingChannel,
              preInstallVersion: ctx.installed_version ?? currentVersion
            });
            enterPostInstallGuard(pendingInstall.version, pendingChannel, ctx.installed_version ?? currentVersion);
            onInstallVersionConfirmed?.(pendingInstall.version);
            skipInitialCheck.current = true;
          }
          if (ctx.last_checked_at && ctx.last_checked_channel === updateChannel) {
            const hasPending =
              !!ctx.pending_update_install &&
              ctx.effective_installed_version === ctx.pending_update_install.version;
            if (ctx.last_available_tag && !hasPending) {
              void checkForUpdates({ force: false, notify: false, source: "automatic" });
            }
          }
        }
      } catch (err) {
        // Quiet failure on context check
      } finally {
        if (active) {
          setContextHydrated(true);
        }
      }
    }
    void loadCache();
    return () => {
      active = false;
    };
  }, [currentVersion, onInstallVersionConfirmed, updateChannel, enterPostInstallGuard, checkForUpdates]);

  useEffect(() => {
    if (!contextHydrated) {
      return;
    }
    if (!currentVersion || currentVersion === "Loading...") {
      return;
    }
    const isFirstMount = !hasChecked.current;
    hasChecked.current = true;

    if (isFirstMount) {
      if (skipInitialCheck.current) {
        logUpdate(null, "initial_check_skipped_hydration");
        return;
      }
      if (automaticUpdateChecks) {
        void checkForUpdates({ force: false, notify: false, source: "automatic" });
      }
    } else {
      void checkForUpdates({ force: true, notify: false, source: "automatic" });
    }
  }, [updateChannel, currentVersion, contextHydrated, checkForUpdates]);

  useEffect(() => {
    if (!contextHydrated) {
      return;
    }
    if (!automaticCheckToggleHydrated.current) {
      automaticCheckToggleHydrated.current = true;
      return;
    }
    if (!automaticUpdateChecks || !currentVersion || currentVersion === "Loading...") {
      return;
    }
    void checkForUpdates({ force: false, notify: false, source: "automatic" });
  }, [automaticUpdateChecks, currentVersion, contextHydrated, checkForUpdates]);

  const install = useCallback(async (targetCandidate: PluginUpdateCandidate) => {
    if (isInstalling) return;
    setIsInstalling(true);
    setIsHandoffPending(false);
    setErrorMessage(null);

    const updateTraceId = generateUpdateTraceId();
    logUpdate(updateTraceId, "install_clicked", { version: targetCandidate.version });

    try {
      const revalStart = performance.now();
      logUpdate(updateTraceId, "revalidate_start", { tag: targetCandidate.tag });
      const revalRes = await revalidatePluginUpdateCall(targetCandidate);
      const revalElapsed = Math.round(performance.now() - revalStart);
      if ("status" in revalRes && revalRes.status === "failed" || !("version" in revalRes)) {
        const msg = "message" in revalRes ? revalRes.message : "unknown";
        logUpdate(updateTraceId, "revalidate_failed", { message: msg, elapsed_ms: revalElapsed });
        throw new Error(msg || "Revalidation failed");
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

      enterPostInstallGuard(revalRes.version, revalRes.channel as UpdateChannel);

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
              await handleHandoffSuccess(revalRes.version, revalRes.channel as UpdateChannel, updateTraceId, handoffStart);
            } catch (err) {
              const msg = err instanceof Error ? err.message : String(err);
              logUpdate(updateTraceId, "handoff_rejected", { message: msg, elapsed_ms: Math.round(performance.now() - handoffStart) });
              try {
                await clearPendingUpdateInstallCall(revalRes.version);
              } catch (clearErr) {
                const clearMsg = clearErr instanceof Error ? clearErr.message : String(clearErr);
                logUpdate(updateTraceId, "pending_clear_failed", { message: clearMsg });
              }
              setInstalledOverride(null);
              pendingInstallVersion.current = null;
              void checkForUpdates({ force: false, notify: false, source: "automatic" });
              setIsInstalling(false);
              setIsHandoffPending(false);
              setErrorMessage(msg);
              toaster.toast({
                title: "Installation Failed",
                body: msg,
                duration: 4000
              });
            }
        })();
      } else {
        await installerPromise;
        await handleHandoffSuccess(revalRes.version, revalRes.channel as UpdateChannel, updateTraceId, handoffStart);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      try {
        await clearPendingUpdateInstallCall(targetCandidate.version);
      } catch (clearErr) {
        const clearMsg = clearErr instanceof Error ? clearErr.message : String(clearErr);
        logUpdate(updateTraceId, "pending_clear_failed", { message: clearMsg });
      }
      setInstalledOverride(null);
      pendingInstallVersion.current = null;
      void checkForUpdates({ force: false, notify: false, source: "automatic" });
      setErrorMessage(msg);
      setIsInstalling(false);
      setIsHandoffPending(false);
      toaster.toast({
        title: "Installation Failed",
        body: msg,
        duration: 4000
      });
    }
  }, [isInstalling, enterPostInstallGuard, handleHandoffSuccess, checkForUpdates]);

  return {
    effectiveCurrentVersion,
    candidate,
    checkResult,
    errorMessage,
    isChecking,
    isInstalling,
    isHandoffPending,
    installedReleasePublishedAt,
    checkNow,
    install,
  };
}
