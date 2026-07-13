import { describe, it, expect, vi, beforeEach, afterEach, type Mocked } from "vitest";
import { createPauseLease, type LeaseRpcContract, type LeaseLogger } from "./launchGateLease";
import type { PauseGameProcessResult } from "../types";

describe("createPauseLease", () => {
  let rpc: Mocked<LeaseRpcContract>;
  let logger: Mocked<LeaseLogger>;

  const validPause: Extract<PauseGameProcessResult, { status: "paused" }> = {
    status: "paused",
    pid: 123,
    lease_id: "test_lease",
    lease_ttl_seconds: 30,
  };

  beforeEach(() => {
    vi.useFakeTimers();
    rpc = {
      renewGameProcessPause: vi.fn(),
      resumeGameProcess: vi.fn().mockResolvedValue({ status: "resumed", pid: 123 }),
    };
    logger = {
      warn: vi.fn(),
      error: vi.fn(),
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("validates lease metadata on construction", () => {
    expect(() => createPauseLease(rpc, { ...validPause, lease_id: "" }, logger)).toThrow(/Invalid lease_id/);
    expect(() => createPauseLease(rpc, { ...validPause, lease_id: "   " }, logger)).toThrow(/Invalid lease_id/);
    expect(() => createPauseLease(rpc, { ...validPause, lease_ttl_seconds: 0 }, logger)).toThrow(/Invalid lease_ttl_seconds/);
    expect(() => createPauseLease(rpc, { ...validPause, lease_ttl_seconds: -5 }, logger)).toThrow(/Invalid lease_ttl_seconds/);
    expect(() => createPauseLease(rpc, { ...validPause, lease_ttl_seconds: NaN }, logger)).toThrow(/Invalid lease_ttl_seconds/);
    expect(() => createPauseLease(rpc, { ...validPause, lease_ttl_seconds: Infinity }, logger)).toThrow(/Invalid lease_ttl_seconds/);
  });

  it("renews lease periodically until released, tracking a 60-second wait", async () => {
    rpc.renewGameProcessPause.mockResolvedValue({ status: "renewed", pid: 123, lease_ttl_seconds: 30 });
    rpc.resumeGameProcess.mockResolvedValue({ status: "resumed", pid: 123 });

    const handle = createPauseLease(rpc, validPause, logger);
    expect(handle.state).toBe("renewing");
    expect(rpc.renewGameProcessPause).not.toHaveBeenCalled();

    // The normal backend TTL uses the plan's five-second renewal cadence.
    for (let i = 0; i < 12; i++) {
      await vi.advanceTimersByTimeAsync(5000);
    }

    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(12);
    expect(rpc.resumeGameProcess).not.toHaveBeenCalled(); // No resume during the wait

    // Now resolve with one resume
    await handle.release();
    expect(handle.state).toBe("released");
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    expect(rpc.resumeGameProcess).toHaveBeenCalledWith(123, "test_lease");

    // No more renewals after release
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(12);
  });

  it("serializes slow renewals", async () => {
    // Make renewal take 20 seconds, longer than the five-second interval.
    rpc.renewGameProcessPause.mockImplementation(async () => {
      return new Promise((resolve) => setTimeout(() => resolve({ status: "renewed", pid: 123, lease_ttl_seconds: 30 }), 20000));
    });

    createPauseLease(rpc, validPause, logger);

    // First renew starts at t=5s and takes 20s (resolves at t=25s).
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);

    // Advance 20s so the promise resolves (t=25s).
    await vi.advanceTimersByTimeAsync(20000);

    // It schedules the next one five seconds later (t=30s).
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(2);
  });

  it("handles renewal failure with one loss notification and resume", async () => {
    rpc.renewGameProcessPause.mockResolvedValue({ status: "failed", message: "mismatch" });

    const handle = createPauseLease(rpc, validPause, logger);
    let lostReason: string | undefined;
    handle.onLost.then(r => lostReason = r);

    await vi.advanceTimersByTimeAsync(5000);

    // Await microtasks to let promise settle
    await Promise.resolve();

    expect(handle.state).toBe("lost");
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);
    expect(logger.warn).toHaveBeenCalledWith("[PauseLease] Lease lost for PID 123: mismatch");
    expect(lostReason).toBe("mismatch");
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);

    // Further time doesn't trigger more renewals or resumes
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
  });

  it("handles renewal exception with one loss notification and resume", async () => {
    rpc.renewGameProcessPause.mockRejectedValue(new Error("network error"));

    const handle = createPauseLease(rpc, validPause, logger);
    let lostReason: string | undefined;
    handle.onLost.then(r => lostReason = r);

    await vi.advanceTimersByTimeAsync(5000);
    await Promise.resolve();

    expect(handle.state).toBe("lost");
    expect(lostReason).toBe("network error");
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
  });

  it("is idempotent on release", async () => {
    rpc.resumeGameProcess.mockResolvedValue({ status: "resumed", pid: 123 });
    const handle = createPauseLease(rpc, validPause, logger);
    await handle.release();
    await handle.release();
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
  });

  it("awaits the same in-flight resume after renewal loss", async () => {
    let finishResume: (() => void) | undefined;
    rpc.renewGameProcessPause.mockResolvedValue({ status: "failed", message: "expired" });
    rpc.resumeGameProcess.mockReturnValue(
      new Promise((resolve) => {
        finishResume = () => resolve({ status: "resumed", pid: 123 });
      }),
    );
    const handle = createPauseLease(rpc, validPause, logger);

    await vi.advanceTimersByTimeAsync(5000);
    let releaseSettled = false;
    const release = handle.release().then(() => {
      releaseSettled = true;
    });
    await Promise.resolve();

    expect(releaseSettled).toBe(false);
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
    finishResume?.();
    await release;
    expect(releaseSettled).toBe(true);
  });

  it("dismount cleanup clears timers and doesn't crash", async () => {
    rpc.resumeGameProcess.mockResolvedValue({ status: "resumed", pid: 123 });
    const handle = createPauseLease(rpc, validPause, logger);
    await handle.release();
    await vi.advanceTimersByTimeAsync(5000);
    expect(rpc.renewGameProcessPause).not.toHaveBeenCalled();
  });

  it("runProtected executes if renewing and races loss", async () => {
    const handle = createPauseLease(rpc, validPause, logger);
    let ran = false;
    const result = await handle.runProtected(async () => {
      ran = true;
      return 42;
    });
    expect(ran).toBe(true);
    expect(result).toBe(42);

    // Simulate loss
    rpc.renewGameProcessPause.mockResolvedValue({ status: "failed" });
    await vi.advanceTimersByTimeAsync(5000);

    await expect(handle.runProtected(async () => 42)).rejects.toThrow("Lease lost: already lost");
  });

  it("runProtected throws if lease released", async () => {
    rpc.resumeGameProcess.mockResolvedValue({ status: "resumed", pid: 123 });
    const handle = createPauseLease(rpc, validPause, logger);
    await handle.release();
    await expect(handle.runProtected(async () => 42)).rejects.toThrow("Lease lost: already released");
  });

  it("release resolves onLost to cancel in-flight runProtected", async () => {
    rpc.resumeGameProcess.mockResolvedValue({ status: "resumed", pid: 123 });
    const handle = createPauseLease(rpc, validPause, logger);
    const thunk = async () => {
      await new Promise(r => setTimeout(r, 5000));
      return "success";
    };

    let caughtError: Error | undefined;
    const promise = handle.runProtected(thunk).catch(e => { caughtError = e; });

    // release while thunk is pending
    await handle.release();

    // advance timers to let thunk finish
    await vi.advanceTimersByTimeAsync(5000);
    await promise;

    expect(caughtError).toBeInstanceOf(Error);
    expect(caughtError?.message).toBe("Lease lost: released");
  });
});
