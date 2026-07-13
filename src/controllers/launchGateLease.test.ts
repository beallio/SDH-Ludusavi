import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPauseLease } from "./launchGateLease";


describe("createPauseLease", () => {
  let rpc: any;
  let logger: { warn: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    vi.useFakeTimers();
    rpc = {
      renewGameProcessPause: vi.fn(),
      resumeGameProcess: vi.fn(),
    } as unknown as any;
    logger = {
      warn: vi.fn(),
      error: vi.fn(),
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renews lease periodically until released", async () => {
    rpc.renewGameProcessPause.mockResolvedValue({ status: "renewed", pid: 123, lease_ttl_seconds: 30 });
    rpc.resumeGameProcess.mockResolvedValue({ status: "resumed", pid: 123 });

    const handle = createPauseLease(rpc, 123, "test_lease", logger as any);

    expect(rpc.renewGameProcessPause).not.toHaveBeenCalled();

    // Advance first interval
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledWith(123, "test_lease");

    // Advance second interval
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(2);

    await handle.release();
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    expect(rpc.resumeGameProcess).toHaveBeenCalledWith(123);

    // Ensure no more renewals
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(2);
  });

  it("stops renewing if renewal fails", async () => {
    rpc.renewGameProcessPause.mockResolvedValue({ status: "failed", message: "mismatch" });

    createPauseLease(rpc, 123, "test_lease", logger as any);

    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);
    expect(logger.warn).toHaveBeenCalledWith("[PauseLease] Failed to renew lease for PID 123: mismatch");

    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1); // Didn't run again
  });

  it("releases multiple times safely", async () => {
    const handle = createPauseLease(rpc, 123, "test_lease", logger as any);
    await handle.release();
    await handle.release();
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
  });
});
