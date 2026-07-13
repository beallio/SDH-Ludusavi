import { PauseGameProcessResult, RenewGameProcessPauseResult, RpcResult, ProcessSignalResult } from "../types";

export interface PauseLeaseHandle {
  /** Stop renewing and resume the process. */
  release(): Promise<void>;
  /** Promise that resolves with the loss reason if the lease is lost prematurely. */
  onLost: Promise<string>;
  /** Synchronous state of the lease */
  readonly state: "renewing" | "lost" | "released";
  /** Safely run a mutation only if still renewing, racing against loss. */
  runProtected<T>(thunk: () => Promise<T>): Promise<T>;
}

export interface LeaseRpcContract {
  renewGameProcessPause(pid: number, leaseId: string): Promise<RpcResult<RenewGameProcessPauseResult>>;
  resumeGameProcess(pid: number, leaseId?: string): Promise<RpcResult<ProcessSignalResult>>;
}

export interface LeaseLogger {
  warn(msg: string): void;
  error(msg: string, e?: unknown): void;
}

export function createPauseLease(
  rpc: LeaseRpcContract,
  pauseResult: Extract<PauseGameProcessResult, { status: "paused" }>,
  logger: LeaseLogger = console
): PauseLeaseHandle {
  const { pid, lease_id, lease_ttl_seconds } = pauseResult;

  if (!lease_id || typeof lease_id !== "string" || lease_id.trim() === "") {
    throw new Error("Invalid lease_id: must be non-blank");
  }
  if (typeof lease_ttl_seconds !== "number" || lease_ttl_seconds <= 0 || !isFinite(lease_ttl_seconds)) {
    throw new Error("Invalid lease_ttl_seconds: must be a positive finite number");
  }

  // Renew every five seconds for the normal 30-second lease, or halfway through
  // a shorter backend-provided TTL so the cadence always retains safety margin.
  const renewIntervalMs = Math.max(
    100,
    Math.min(5000, (lease_ttl_seconds * 1000) / 2),
  );

  let state: "renewing" | "lost" | "released" = "renewing";
  let timer: ReturnType<typeof setTimeout> | undefined;
  let currentRenewPromise: Promise<void> | undefined;
  let resumePromise: Promise<void> | undefined;

  let resolveLost: (reason: string) => void;
  const onLost = new Promise<string>((resolve) => {
    resolveLost = resolve;
  });

  const doResume = () => {
    if (!resumePromise) {
      resumePromise = rpc
        .resumeGameProcess(pid, lease_id)
        .then(() => {})
        .catch((error: unknown) => {
          logger.error(`[PauseLease] Exception resuming PID ${pid}`, error);
        });
    }
    return resumePromise;
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
      if (res.status === "failed") {
        handleLoss(res.message || "renewal failed");
      } else if (res.status === "skipped") {
        handleLoss(res.reason || "renewal skipped");
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
    get state() { return state; },
    runProtected: async <T,>(thunk: () => Promise<T>): Promise<T> => {
      if (state !== "renewing") {
        throw new Error(`Lease lost: already ${state}`);
      }
      return await new Promise<T>((resolve, reject) => {
        let done = false;
        thunk().then(
          (val) => {
            if (!done) { done = true; resolve(val); }
          },
          (err) => {
            if (!done) { done = true; reject(err); }
          }
        );
        onLost.then((reason) => {
          if (!done) { done = true; reject(new Error(`Lease lost: ${reason}`)); }
        });
      });
    },
    release: async () => {
      if (state !== "released") {
        const wasRenewing = state === "renewing";
        state = "released";
        if (timer) clearTimeout(timer);
        if (wasRenewing) resolveLost("released");
      }
      await doResume();
    },
  };
}
