import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { RUNNING_STATUS_HIDE_CEILING_MS } from "./autoSyncStatusSurface";

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
  createAutoSyncStatusBrowserView: () => ({
    sync: vi.fn(),
    destroy: vi.fn(),
    setContext: vi.fn(),
    clearShowTimeout: vi.fn()
  }),
}));

async function freshSurface() {
  vi.resetModules();
  const viewMod = await import("./autoSyncStatusBrowserView");
  const mod = await import("./autoSyncStatusSurface");
  return mod.createAutoSyncStatusSurface(viewMod.createAutoSyncStatusBrowserView());
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
    surface.publish("backing_up", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });

    await vi.advanceTimersByTimeAsync(RUNNING_STATUS_HIDE_CEILING_MS);

    const messages = loggedMessages();
    expect(
      messages.some((message) => message.startsWith("info:") && message.includes("timed out")),
    ).toBe(true);
  });

  it("logs an explanation when a final result is suppressed by an earlier timeout", async () => {
    const surface = await freshSurface();
    surface.publish("backing_up", {
      source: "lifecycle_exit",
      gameName: "Hades",
      appID: "1145300",
      tracked: true,
    });
    await vi.advanceTimersByTimeAsync(RUNNING_STATUS_HIDE_CEILING_MS);
    logMock.mockClear();

    surface.complete(
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
    surface.publish("backing_up", {
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
          message.includes(String(RUNNING_STATUS_HIDE_CEILING_MS)),
      ),
    ).toBe(true);
  });

  it("keeps a running status visible well past the old 10s timeout", async () => {
    const surface = await freshSurface();
    surface.publish("backing_up", {
      source: "lifecycle_exit", gameName: "Hades", appID: "1145300", tracked: true,
    });
    logMock.mockClear();

    await vi.advanceTimersByTimeAsync(60000); // 1 minute: > 10s, < ceiling

    const messages = loggedMessages();
    expect(messages.some((m) => m.includes("timed out"))).toBe(false);
    expect(messages.some((m) => m.includes("visible=false"))).toBe(false);
  });

  it("publishes the final result when the operation completes before the ceiling", async () => {
    const surface = await freshSurface();
    surface.publish("backing_up", {
      source: "lifecycle_exit", gameName: "Hades", appID: "1145300", tracked: true,
    });
    await vi.advanceTimersByTimeAsync(60000);
    logMock.mockClear();

    surface.complete(
      { status: "backed_up", game: "Hades" },
      { gameName: "Hades", appID: "1145300", tracked: true },
    );

    const messages = loggedMessages();
    expect(messages.some((m) => m.includes("Status update:") && m.includes("status=has_backup"))).toBe(true);
    expect(messages.some((m) => m.includes("suppressed"))).toBe(false);
  });

  it("clears a previous timeout suppression when a new running status is published", async () => {
    const surface = await freshSurface();
    // Game A: backup exceeds the ceiling -> timedOut flag set
    surface.publish("backing_up", {
      source: "lifecycle_exit", gameName: "GameA", appID: "1", tracked: true,
    });
    await vi.advanceTimersByTimeAsync(RUNNING_STATUS_HIDE_CEILING_MS);

    // Game B: new lifecycle publishes "checking", which must reset the flag
    surface.publish("checking", {
      source: "lifecycle_start", gameName: "GameB", appID: "2", tracked: true,
    });
    logMock.mockClear();

    surface.complete(
      { status: "backed_up", game: "GameB" },
      { gameName: "GameB", appID: "2", tracked: true },
    );

    const messages = loggedMessages();
    expect(messages.some((m) => m.includes("suppressed"))).toBe(false);
    expect(messages.some((m) => m.includes("Status update:") && m.includes("status=has_backup"))).toBe(true);
  });

  it("logs unhandled result statuses instead of silently ignoring them", async () => {
    const surface = await freshSurface();
    surface.complete(
      { status: "paused" as any, game: "Hades" },
      { gameName: "Hades", appID: "1145300", tracked: true },
    );

    const messages = loggedMessages();
    expect(
      messages.some((message) => message.includes("paused") && message.includes("unhandled")),
    ).toBe(true);
  });
});
