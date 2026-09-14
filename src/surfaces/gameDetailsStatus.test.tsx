import { createContext, createElement } from "react";
import { describe, expect, it, vi } from "vitest";

const routeMock = vi.hoisted(() => ({ addPatch: vi.fn((_: string, patch: unknown) => patch), removePatch: vi.fn() }));
vi.mock("@decky/api", () => ({ routerHook: routeMock }));
vi.mock("@decky/ui", () => ({}));
vi.mock("../ludusaviLauncher", () => ({}));
vi.mock("../utils/steam", () => ({
  normalize: (name: string) => name.toLowerCase(),
  sessionFromAppOverview: (app: any) => app?.display_name ? { name: app.display_name, appID: String(app.appid) } : null,
}));
vi.mock("../utils/steamRuntime", () => ({
  getAppDetailsForAppID: vi.fn(() => null), getAppOverviewForAppID: vi.fn(() => null), subscribeToAppDetails: vi.fn(() => () => {}),
}));

import { createLudusaviStateStore } from "../state/ludusaviState";
import {
  composeInNativeStatusSlot,
  createGameDetailsStatusSurface,
  isVisibleStatusBand,
} from "./gameDetailsStatus";

describe("game details route adapter", () => {
  it("clones the supported React route child, keeps its props, and reuses the native header wrapper", () => {
    const surface = createGameDetailsStatusSurface(createLudusaviStateStore(), {
      registerDetailsOwner: vi.fn(), subscribeDetailsPresentation: vi.fn(() => () => {}), shouldDetailsRowYield: vi.fn(() => false),
    } as any);
    const patch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
    const context = createContext<unknown>(null);
    const nativeHeader = () => createElement("native-header");
    const originalRender = vi.fn(() => createElement(context.Provider, { value: nativeHeader }, createElement("native-children")));
    const child = createElement("native-route", { preserved: "yes", renderFunc: originalRender });
    const patched = patch({ path: "/library/app/:appid", children: child });

    expect(patched.children).not.toBe(child);
    expect(patched.children.props.preserved).toBe("yes");
    expect(patched.children.props.renderFunc).not.toBe(originalRender);
    const first = patched.children.props.renderFunc({ params: { appid: "100" } });
    const second = patched.children.props.renderFunc({ params: { appid: "100" } });
    expect(first.props.children.type).toBe("native-children");
    expect(first.props.value).not.toBe(nativeHeader);
    expect(second.props.value).toBe(first.props.value);

    const unsupported = { children: {} };
    expect(patch(unsupported)).toBe(unsupported);
    surface.dispose();
    expect(routeMock.removePatch).toHaveBeenCalledWith("/library/app/:appid", patch);
  });

  it("uses only an empty verified status slot and preserves an occupied native slot", () => {
    const play = createElement("play");
    const tabs = createElement("tabs");
    const root = createElement("app-details-root", { marker: "native" }, [play, null, tabs]);
    const row = createElement("ludusavi-status");
    const contributed = composeInNativeStatusSlot(root, row) as any;
    expect(contributed.props.marker).toBe("native");
    expect(contributed.props.children).toEqual([play, row, tabs]);

    const cloud = createElement("steam-cloud");
    const occupied = createElement("app-details-root", null, [play, cloud, tabs]);
    expect(composeInNativeStatusSlot(occupied, row)).toBe(occupied);
  });

  it("releases ownership when an ancestor hides the otherwise measured row", () => {
    const ancestor = { hidden: false, parentElement: null };
    const element = {
      hidden: false,
      parentElement: ancestor,
      getBoundingClientRect: () => ({ width: 600, height: 30, top: 40, left: 30, right: 630, bottom: 70 }),
      contains: (candidate: unknown) => candidate === element,
    };
    vi.stubGlobal("window", {
      getComputedStyle: (candidate: unknown) => ({
        display: "block",
        visibility: candidate === ancestor ? "hidden" : "visible",
      }),
    });
    vi.stubGlobal("document", {
      documentElement: { clientHeight: 800, clientWidth: 1280 },
      elementFromPoint: () => element,
    });

    expect(isVisibleStatusBand(element as unknown as HTMLDivElement, true)).toBe(false);
    vi.unstubAllGlobals();
  });

  it("releases ownership when the native details container clips the status band", () => {
    const ancestor = {
      hidden: false,
      parentElement: null,
      getBoundingClientRect: () => ({ width: 600, height: 15, top: 40, left: 30, right: 630, bottom: 55 }),
    };
    const element = {
      hidden: false,
      parentElement: ancestor,
      getBoundingClientRect: () => ({ width: 600, height: 30, top: 40, left: 30, right: 630, bottom: 70 }),
      contains: (candidate: unknown) => candidate === element,
    };
    vi.stubGlobal("window", { getComputedStyle: () => ({ display: "block", visibility: "visible" }) });
    vi.stubGlobal("document", {
      documentElement: { clientHeight: 800, clientWidth: 1280 },
      elementFromPoint: () => element,
    });

    expect(isVisibleStatusBand(element as unknown as HTMLDivElement, true)).toBe(false);
    vi.unstubAllGlobals();
  });
});
