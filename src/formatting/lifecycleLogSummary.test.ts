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
      message: "a".repeat(200),
      backupPath: "/tmp/foo/bar/baz"
    };
    const summaryStr = summarizeLifecycleResult(result as any);
    const summary = JSON.parse(summaryStr);
    expect(summary.status).toBe("failed");
    expect(summary.reason).toBe("error_reason");
    expect(summary.message.length).toBe(150);
    expect(summary.backupPath).toBeUndefined();
  });
});
