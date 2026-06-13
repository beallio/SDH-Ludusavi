import { describe, it, expect } from "vitest";
import { formatHistoryTimestamp } from "./dateTime";

describe("formatHistoryTimestamp", () => {
  // 2026-06-13T20:32:00Z -> 4:32 PM EDT (UTC-4)
  it("converts a UTC ISO timestamp to the given local timezone", () => {
    expect(
      formatHistoryTimestamp("2026-06-13T20:32:00.000000+00:00", {
        timeZone: "America/New_York",
      })
    ).toBe("06/13/2026 4:32 PM");
  });

  // Regression for the report: user (UTC-7 PDT) saw raw UTC 8:32 PM; correct = 1:32 PM
  it("converts to a US west-coast zone (UTC-7)", () => {
    expect(
      formatHistoryTimestamp("2026-06-13T20:32:00.000000+00:00", {
        timeZone: "America/Los_Angeles",
      })
    ).toBe("06/13/2026 1:32 PM");
  });

  it("returns the raw value when unparseable", () => {
    expect(formatHistoryTimestamp("not-a-date")).toBe("not-a-date");
  });

  it("returns empty string for null/undefined", () => {
    expect(formatHistoryTimestamp(null as any)).toBe("");
  });
});
