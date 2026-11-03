import { afterEach, describe, expect, it, vi } from "vitest";

const { logMock } = vi.hoisted(() => ({ logMock: vi.fn() }));

vi.mock("@decky/api", () => ({
  callable: () => () => Promise.resolve(),
}));

vi.mock("@decky/ui", () => ({
  Router: {
    RunningApps: []
  },
}));

vi.mock("../utils/logging", () => ({
  log: logMock,
  logUiEvent: vi.fn(),
}));

import { createSteamLifecycleSource } from "./steamLifecycleSource";

const registerLifetimeCallback = () => {
  const registrations: ((notification: unknown) => void)[] = [];
  Object.assign(globalThis, {
    window: globalThis,
    SteamClient: {
      GameSessions: {
        RegisterForAppLifetimeNotifications: (callback: (notification: unknown) => void) => {
          registrations.push(callback);
          return { unregister: vi.fn() };
        },
      },
    },
  });
  return registrations;
};

describe("steamLifecycleSource", () => {
  afterEach(() => {
    Reflect.deleteProperty(globalThis, "window");
    Reflect.deleteProperty(globalThis, "SteamClient");
    logMock.mockClear();
  });

  it("can be created and disposed without errors", () => {
    const observer = {
      onAppStart: vi.fn(),
      onAppExit: vi.fn(),
    };
    const source = createSteamLifecycleSource(observer);
    expect(source.start).toBeDefined();
    expect(source.dispose).toBeDefined();

    source.dispose();
  });

  it("logs an untracked unresolved app lifetime notification at debug, not warning", () => {
    const registrations = registerLifetimeCallback();
    const source = createSteamLifecycleSource(
      { onAppStart: vi.fn(), onAppExit: vi.fn() },
      () => false,
    );
    source.start();
    registrations[0]({ unAppID: 234140, nInstanceID: 13116, bRunning: true });

    expect(logMock).toHaveBeenCalledWith(
      "debug",
      expect.stringContaining("Could not resolve app lifetime notification"),
      "lifecycle",
    );
    expect(logMock.mock.calls.filter((call) => call[0] === "warning")).toEqual([]);
    source.dispose();
  });

  it("keeps the warning when a tracked game's lifetime notification cannot be resolved", () => {
    const registrations = registerLifetimeCallback();
    const source = createSteamLifecycleSource(
      { onAppStart: vi.fn(), onAppExit: vi.fn() },
      (appID) => appID === "1145300",
    );
    source.start();
    registrations[0]({ unAppID: 1145300, nInstanceID: 4242, bRunning: true });

    expect(logMock).toHaveBeenCalledWith(
      "warning",
      expect.stringContaining("Could not resolve app lifetime notification"),
      "lifecycle",
    );
    source.dispose();
  });
});
