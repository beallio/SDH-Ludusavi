import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {},
}));

const { logMock } = vi.hoisted(() => ({
  logMock: vi.fn(),
}));

vi.mock("../utils/logging", () => ({
  log: logMock,
  logUiEvent: vi.fn(),
}));

vi.mock("./autoSyncStatusBrowserView", () => ({
  syncAutoSyncStatusBrowserView: vi.fn(),
  destroyAutoSyncStatusBrowserView: vi.fn(),
  setBrowserViewSyncStateContext: vi.fn(),
}));

async function freshSurface() {
  vi.resetModules();
  return await import("./autoSyncStatusSurface");
}

describe("AutoSyncStatusSurface timeout suppression logging", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    (globalThis as any).window = globalThis;
    logMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const loggedMessages = () => logMock.mock.calls.map((call) => `${call[0]}:${call[1]}`);

  it("logs when the running status times out and warns the final result will be hidden", async () => {
    const surface = await freshSurface();
    surface.publishAutoSyncStatus("backing_up", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });

    await vi.advanceTimersByTimeAsync(10000);

    const messages = loggedMessages();
    expect(
      messages.some((message) => message.startsWith("info:") && message.includes("timed out")),
    ).toBe(true);
  });

  it("logs an explanation when a final result is suppressed by an earlier timeout", async () => {
    const surface = await freshSurface();
    surface.publishAutoSyncStatus("backing_up", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });
    await vi.advanceTimersByTimeAsync(10000);
    logMock.mockClear();

    surface.completeAutoSyncStatus(
      { status: "backed_up", game: "Hades" },
      { gameName: "Hades", appID: "1145300", tracked: true },
    );

    const messages = loggedMessages();
    expect(
      messages.some(
        (message) =>
          message.startsWith("info:") &&
          message.includes("suppressed") &&
          message.includes("backed_up"),
      ),
    ).toBe(true);
    // The suppressed result must not surface as a new status publication.
    expect(messages.some((message) => message.includes("Status update:"))).toBe(false);
  });

  it("logs the auto-hide schedule at debug level", async () => {
    const surface = await freshSurface();
    surface.publishAutoSyncStatus("backing_up", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });

    const messages = loggedMessages();
    expect(
      messages.some(
        (message) =>
          message.startsWith("debug:") &&
          message.includes("uto-hide") &&
          message.includes("10000"),
      ),
    ).toBe(true);
  });

  it("logs unhandled result statuses instead of silently ignoring them", async () => {
    const surface = await freshSurface();
    surface.completeAutoSyncStatus(
      { status: "paused" as any, game: "Hades" },
      { gameName: "Hades", appID: "1145300", tracked: true },
    );

    const messages = loggedMessages();
    expect(
      messages.some((message) => message.includes("paused") && message.includes("unhandled")),
    ).toBe(true);
  });
});
