
export interface PauseLeaseHandle {
  /** Stop renewing and resume the process. */
  release(): Promise<void>;
}

export function createPauseLease(
  rpc: { renewGameProcessPause: (pid: number, leaseId: string) => Promise<{ status: string, message?: string }>, resumeGameProcess: (pid: number) => Promise<any> },
  pid: number,
  leaseId: string,
  logger: { warn: (msg: string) => void; error: (msg: string, e?: any) => void } = console
): PauseLeaseHandle {
  const renewIntervalMs = 5000;
  let isActive = true;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const scheduleNext = () => {
    if (!isActive) return;
    timer = setTimeout(async () => {
      if (!isActive) return;
      try {
        const res = await rpc.renewGameProcessPause(pid, leaseId);
        if (res.status === "failed") {
          logger.warn(`[PauseLease] Failed to renew lease for PID ${pid}: ${res.message}`);
          isActive = false;
        }
      } catch (e) {
        logger.error(`[PauseLease] Exception renewing lease for PID ${pid}`, e);
        isActive = false;
      }
      if (isActive) {
        scheduleNext();
      }
    }, renewIntervalMs);
  };
  
  scheduleNext();

  return {
    release: async () => {
      if (!isActive) return;
      isActive = false;
      if (timer) clearTimeout(timer);
      try {
        await rpc.resumeGameProcess(pid);
      } catch (e) {
        logger.error(`[PauseLease] Exception resuming PID ${pid}`, e);
      }
    },
  };
}
