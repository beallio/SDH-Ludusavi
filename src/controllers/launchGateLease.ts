import { PauseGameProcessResult, RenewGameProcessPauseResult, RpcResult, ProcessSignalResult } from "../types";

export interface PauseLeaseHandle {
  /** Stop renewing and resume the process. */
  release(): Promise<void>;
  /** Promise that resolves with the loss reason if the lease is lost prematurely. */
  onLost: Promise<string>;
}

export interface LeaseRpcContract {
  renewGameProcessPause(pid: number, leaseId: string): Promise<RpcResult<RenewGameProcessPauseResult>>;
  resumeGameProcess(pid: number): Promise<RpcResult<ProcessSignalResult>>;
}

export function createPauseLease(
  rpc: LeaseRpcContract,
  pauseResult: Extract<PauseGameProcessResult, { status: "paused" }>,
  logger: { warn: (msg: string) => void; error: (msg: string, e?: any) => void } = console
): PauseLeaseHandle {
  const { pid, lease_id, lease_ttl_seconds } = pauseResult;
  
  if (!lease_id || typeof lease_id !== "string" || lease_id.trim() === "") {
    throw new Error("Invalid lease_id: must be non-blank");
  }
  if (typeof lease_ttl_seconds !== "number" || lease_ttl_seconds <= 0 || !isFinite(lease_ttl_seconds)) {
    throw new Error("Invalid lease_ttl_seconds: must be a positive finite number");
  }

  // Safety margin: renew halfway through the TTL, min 1s
  const renewIntervalMs = Math.max(1000, (lease_ttl_seconds * 1000) / 2);
  
  let state: "renewing" | "lost" | "released" = "renewing";
  let timer: ReturnType<typeof setTimeout> | undefined;
  let currentRenewPromise: Promise<void> | undefined;
  
  let resolveLost: (reason: string) => void;
  const onLost = new Promise<string>((resolve) => {
    resolveLost = resolve;
  });

  const doResume = async () => {
    try {
      await rpc.resumeGameProcess(pid);
    } catch (e) {
      logger.error(`[PauseLease] Exception resuming PID ${pid}`, e);
    }
  };

  const handleLoss = (reason: string) => {
    if (state !== "renewing") return;
    state = "lost";
    if (timer) clearTimeout(timer);
    logger.warn(`[PauseLease] Lease lost for PID ${pid}: ${reason}`);
    resolveLost(reason);
    // best-effort resume on loss
    doResume();
  };

  const renew = async () => {
    if (state !== "renewing") return;
    try {
      const res = await rpc.renewGameProcessPause(pid, lease_id);
      if (res.status === "failed" || res.status === "skipped") {
        handleLoss(res.message || (res as any).reason || "renewal failed");
      }
    } catch (e) {
      handleLoss(e instanceof Error ? e.message : String(e));
    }
  };

  const scheduleNext = () => {
    if (state !== "renewing") return;
    timer = setTimeout(async () => {
      if (state !== "renewing") return;
      // Serialize slow renewals
      if (!currentRenewPromise) {
        currentRenewPromise = renew().finally(() => {
          currentRenewPromise = undefined;
        });
      }
      await currentRenewPromise;
      if (state === "renewing") {
        scheduleNext();
      }
    }, renewIntervalMs);
  };
  
  scheduleNext();

  return {
    onLost,
    release: async () => {
      if (state === "released") return;
      const wasRenewing = state === "renewing";
      state = "released";
      if (timer) clearTimeout(timer);
      if (wasRenewing) {
        await doResume();
      }
    },
  };
}
