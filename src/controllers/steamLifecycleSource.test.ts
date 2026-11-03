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

import { Router } from "@decky/ui";
import { createSteamLifecycleSource } from "./steamLifecycleSource";

const router = Router as { RunningApps: unknown[]; MainRunningApp?: unknown };

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

const lostPlanet = { appid: 6510, display_name: "Lost Planet: Extreme Condition" };

describe("steamLifecycleSource", () => {
  afterEach(() => {
    router.RunningApps = [];
    router.MainRunningApp = undefined;
    Reflect.deleteProperty(globalThis, "window");
    Reflect.deleteProperty(globalThis, "SteamClient");
    Reflect.deleteProperty(globalThis, "appStore");
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

  it("resolves an exit whose instance ID changed since the start notification", () => {
    const registrations = registerLifetimeCallback();
    const onAppStart = vi.fn();
    const onAppExit = vi.fn();
    router.RunningApps = [lostPlanet];
    const source = createSteamLifecycleSource({ onAppStart, onAppExit });
    source.start();

    registrations[0]({ unAppID: 6510, nInstanceID: 22357, bRunning: true });
    expect(onAppStart).toHaveBeenCalledTimes(1);
    expect(onAppStart).toHaveBeenCalledWith({ appID: "6510", name: lostPlanet.display_name }, 22357);

    // Steam drops the app from the Router and reports the exit under a new ID.
    router.RunningApps = [];
    registrations[0]({ unAppID: 6510, nInstanceID: 22627, bRunning: false });

    expect(onAppExit).toHaveBeenCalledTimes(1);
    expect(onAppExit).toHaveBeenCalledWith({ appID: "6510", name: lostPlanet.display_name });
    source.dispose();
  });

  it("starts again when a second start notification uses a new instance ID", () => {
    const registrations = registerLifetimeCallback();
    const onAppStart = vi.fn();
    const onAppExit = vi.fn();
    router.RunningApps = [lostPlanet];
    const source = createSteamLifecycleSource({ onAppStart, onAppExit });
    source.start();

    registrations[0]({ unAppID: 6510, nInstanceID: 22357, bRunning: true });
    registrations[0]({ unAppID: 6510, nInstanceID: 22358, bRunning: true });
    expect(onAppStart).toHaveBeenCalledTimes(2);

    // An unknown exit instance ID closes one recorded session and fires once.
    router.RunningApps = [];
    registrations[0]({ unAppID: 6510, nInstanceID: 22627, bRunning: false });
    expect(onAppExit).toHaveBeenCalledTimes(1);

    registrations[0]({ unAppID: 6510, nInstanceID: 22628, bRunning: false });
    expect(onAppExit).toHaveBeenCalledTimes(2);
    source.dispose();
  });

  it("does not report an exit for an app that was never started", () => {
    const registrations = registerLifetimeCallback();
    const onAppStart = vi.fn();
    const onAppExit = vi.fn();
    const source = createSteamLifecycleSource({ onAppStart, onAppExit });
    source.start();

    registrations[0]({ unAppID: 6510, nInstanceID: 22627, bRunning: false });

    expect(onAppStart).not.toHaveBeenCalled();
    expect(onAppExit).not.toHaveBeenCalled();
    expect(logMock).toHaveBeenCalledWith(
      "debug",
      expect.stringContaining("Could not resolve app lifetime notification"),
      "lifecycle",
    );
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

  it("warns for an unresolved notification of a game tracked by name", () => {
    const registrations = registerLifetimeCallback();
    Object.assign(globalThis, {
      appStore: {
        GetAppOverviewByAppID: (appID: number) =>
          appID === 1145300 ? { appid: 1145300, display_name: "Fixture Game" } : null,
      },
    });
    const source = createSteamLifecycleSource(
      { onAppStart: vi.fn(), onAppExit: vi.fn() },
      (_appID, name) => name === "Fixture Game",
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
