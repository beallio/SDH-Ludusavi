import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPauseLease } from "./launchGateLease";
import { PauseGameProcessResult } from "../types";

describe("createPauseLease", () => {
  let rpc: any;
  let logger: { warn: (msg: string) => void; error: (msg: string, e?: any) => void };

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
      resumeGameProcess: vi.fn(),
    } as unknown as any;
    logger = {
      warn: vi.fn() as any,
      error: vi.fn() as any,
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

    expect(rpc.renewGameProcessPause).not.toHaveBeenCalled();

    // The interval is lease_ttl_seconds * 1000 / 2 = 15000ms
    // Wait for 60 seconds of conflict
    for (let i = 0; i < 4; i++) {
      await vi.advanceTimersByTimeAsync(15000);
    }
    
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(4);
    expect(rpc.resumeGameProcess).not.toHaveBeenCalled(); // No resume during the wait

    // Now resolve with one resume
    await handle.release();
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);

    // No more renewals after release
    await vi.advanceTimersByTimeAsync(15000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(4);
  });

  it("serializes slow renewals", async () => {
    // Make renewal take 20 seconds, longer than the 15-second interval
    rpc.renewGameProcessPause.mockImplementation(async () => {
      return new Promise((resolve) => setTimeout(() => resolve({ status: "renewed" }), 20000));
    });

    createPauseLease(rpc, validPause, logger);

    // First renew starts at t=15s and takes 20s (resolves at t=35s)
    await vi.advanceTimersByTimeAsync(15000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);

    // Advance 20s so the promise resolves (t=35s)
    await vi.advanceTimersByTimeAsync(20000);
    
    // Now it immediately schedules the next one for 15s later (t=50s). Advance 15s.
    await vi.advanceTimersByTimeAsync(15000); // 50s total.
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(2);
  });

  it("handles renewal failure with one loss notification and resume", async () => {
    rpc.renewGameProcessPause.mockResolvedValue({ status: "failed", message: "mismatch" });

    const handle = createPauseLease(rpc, validPause, logger);
    let lostReason: string | undefined;
    handle.onLost.then(r => lostReason = r);

    await vi.advanceTimersByTimeAsync(15000);
    
    // Await microtasks to let promise settle
    await Promise.resolve();

    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);
    expect(logger.warn).toHaveBeenCalledWith("[PauseLease] Lease lost for PID 123: mismatch");
    expect(lostReason).toBe("mismatch");
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);

    // Further time doesn't trigger more renewals or resumes
    await vi.advanceTimersByTimeAsync(15000);
    expect(rpc.renewGameProcessPause).toHaveBeenCalledTimes(1);
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
  });

  it("handles renewal exception with one loss notification and resume", async () => {
    rpc.renewGameProcessPause.mockRejectedValue(new Error("network error"));

    const handle = createPauseLease(rpc, validPause, logger);
    let lostReason: string | undefined;
    handle.onLost.then(r => lostReason = r);

    await vi.advanceTimersByTimeAsync(15000);
    await Promise.resolve();

    expect(lostReason).toBe("network error");
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
  });

  it("is idempotent on release", async () => {
    const handle = createPauseLease(rpc, validPause, logger);
    await handle.release();
    await handle.release();
    expect(rpc.resumeGameProcess).toHaveBeenCalledTimes(1);
  });
  
  it("dismount cleanup clears timers and doesn't crash", async () => {
    const handle = createPauseLease(rpc, validPause, logger);
    await handle.release();
    await vi.advanceTimersByTimeAsync(15000);
    expect(rpc.renewGameProcessPause).not.toHaveBeenCalled();
  });
});
