import { describe, it, expect } from "vitest";
import { getLastOperationText } from "./operationText";

describe("getLastOperationText", () => {
  it("should format backup local_current correctly", () => {
    expect(getLastOperationText("skipped", "local_current", null, "backup")).toBe("Backup skipped — local save is already current");
  });

  it("should format restore local_current correctly", () => {
    expect(getLastOperationText("skipped", "local_current", null, "restore")).toBe("Restore skipped — local save already matches backup");
  });

  it("should format exit local_current correctly", () => {
    expect(getLastOperationText("skipped", "local_current", null, "exit")).toBe("Backup skipped — local save is already current");
  });

  it("should format start local_current correctly", () => {
    expect(getLastOperationText("skipped", "local_current", null, "start")).toBe("Restore skipped — local save already matches backup");
  });

  it("should format restore no_backup correctly", () => {
    expect(getLastOperationText("skipped", "no_backup", null, "restore")).toBe("Restore skipped — no backup found");
  });

  it("should format backup operation_running correctly", () => {
    expect(getLastOperationText("skipped", "operation_running", null, "backup")).toBe("Backup skipped — another operation is running");
  });

  it("should format backward compatible null operation correctly", () => {
    expect(getLastOperationText("skipped", "local_current", null, null)).toBe("Skipped — local save is already current");
  });

  it("should format skipped with no reason correctly", () => {
    expect(getLastOperationText("skipped", null, null, "backup")).toBe("Backup skipped");
  });

  it("should not change backed_up", () => {
    expect(getLastOperationText("backed_up", null, null, "backup")).toBe("Backup complete");
  });

  it("should not change restored", () => {
    expect(getLastOperationText("restored", null, null, "restore")).toBe("Restore complete");
  });

  it("should not change failed", () => {
    expect(getLastOperationText("failed", null, "Failed to connect", "backup")).toBe("Failed — Failed to connect");
  });
});
