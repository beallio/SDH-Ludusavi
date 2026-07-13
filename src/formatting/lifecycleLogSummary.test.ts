import { describe, it, expect } from "vitest";
import { summarizeLifecycleResult } from "./lifecycleLogSummary";
import type { LifecycleCheckResult, OperationResult } from "../types";

describe("summarizeLifecycleResult", () => {
  it("summarizes LifecycleCheckResult with overall aggregates and canonical game", () => {
    const result: LifecycleCheckResult = {
      status: "needed",
      operation: "restore",
      game: "Hades",
      result: {
        overall: {
          totalGames: 1,
          totalBytes: 1024,
          processedGames: 1,
          processedBytes: 512,
        },
        games: {
          "AdversarialGame": { files: 9999, registry: 9999 }
        }
      }
    };

    expect(summarizeLifecycleResult(result)).toBe(
      '{"status":"needed","operation":"restore","game":"Hades","totalGames":1,"totalBytes":1024,"processedGames":1,"processedBytes":512}'
    );
  });

  it("summarizes OperationResult and sanitizes all free-form fields", () => {
    const result: OperationResult = {
      status: "failed",
      reason: "Could not read /home/deck/.config/ludusavi",
      message: "Failed at /home/deck/somewhere because of a ".repeat(10),
    };

    const summaryStr = summarizeLifecycleResult(result);
    const summary = JSON.parse(summaryStr);

    expect(summary.status).toBe("failed");
    expect(summary.reason).toBe("Could not read [PATH]");
    expect(summary.message.length).toBeLessThanOrEqual(150);
    expect(summary.message).not.toContain("/home/deck");
    expect(summary.message).toContain("[PATH]");
  });

  it("omits nested payloads and top-level backup paths without untyped casts", () => {
    const result: LifecycleCheckResult = {
      status: "conflict",
      operation: "restore",
      game: "Fictional /run/media/deck/save",
      backupPath: "/home/deck/backups/Fictional",
      localLabel: "/home/deck/local/save",
      backupLabel: "/run/media/mmc/backup/save",
      result: {
        games: { Fictional: { files: { save: "/home/deck/save.dat" } } },
        errors: { registry: { path: "/run/media/mmc/registry" } },
      },
    };

    const summary = summarizeLifecycleResult(result);

    expect(summary).toBe('{"status":"conflict","operation":"restore","game":"Fictional [PATH]"}');
    expect(summary).not.toMatch(/backupPath|files|registry|games|\/home\/deck|\/run\/media/);
  });

  it("bounds every included free-form field", () => {
    const result: OperationResult = {
      status: "failed",
      game: "g".repeat(1000),
      reason: "r".repeat(1000),
      message: "m".repeat(1000),
    };

    const summary = JSON.parse(summarizeLifecycleResult(result)) as Record<string, string>;

    expect(summary.game).toHaveLength(150);
    expect(summary.reason).toHaveLength(150);
    expect(summary.message).toHaveLength(150);
  });
});
