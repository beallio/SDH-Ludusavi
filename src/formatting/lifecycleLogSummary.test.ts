import { describe, it, expect } from "vitest";
import { summarizeLifecycleResult } from "./lifecycleLogSummary";

describe("summarizeLifecycleResult", () => {
  it("summarizes LifecycleCheckResult", () => {
    const result = {
      status: "needed",
      operation: "restore",
      result: {
        files: 5,
        registry: 2,
        bytes: 1024,
        game: "Hades",
        nestedInfo: { extremelyLong: "..." }
      }
    };
    expect(summarizeLifecycleResult(result as any)).toBe(
      '{"status":"needed","operation":"restore","files":5,"registry":2,"bytes":1024,"game":"Hades"}'
    );
  });
  
  it("summarizes OperationResult and truncates long messages", () => {
    const result = {
      status: "failed",
      reason: "error_reason",
      message: "Failed at /home/deck/somewhere because of a".repeat(10),
      backupPath: "/tmp/foo/bar/baz"
    };
    const summaryStr = summarizeLifecycleResult(result as any);
    const summary = JSON.parse(summaryStr);
    expect(summary.status).toBe("failed");
    expect(summary.reason).toBe("error_reason");
    expect(summary.message.length).toBeLessThanOrEqual(150);
    expect(summary.message).not.toContain("/home/deck");
    expect(summary.message).toContain("[PATH]");
    expect(summary.backupPath).toBeUndefined();
  });
});
