import { createContext, createElement, type ReactElement } from "react";
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
  detailsRowPaintStyle,
  type GameDetailsStatusContributionSource,
  isVisibleStatusBand,
  DETAILS_STATUS_VISIBILITY_THRESHOLDS,
  isFullyIntersecting,
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

  it("moves a retained mounted route header to the replacement store after reload", () => {
    const firstStore = createLudusaviStateStore();
    const firstSurface = createGameDetailsStatusSurface(firstStore, {
      registerDetailsOwner: vi.fn(), subscribeDetailsPresentation: vi.fn(() => () => {}), shouldDetailsRowYield: vi.fn(() => false),
    } as any);
    const firstPatch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
    const context = createContext<unknown>(null);
    const nativeHeader = () => createElement("native-header");
    const originalRender = vi.fn(() => createElement(context.Provider, { value: nativeHeader }, createElement("native-children")));
    const child = createElement("native-route", { renderFunc: originalRender });
    const patched = firstPatch({ path: "/library/app/:appid", children: child });
    const rendered = patched.children.props.renderFunc({ params: { appid: "100" } });
    const retainedHeader = rendered.props.value as (props: unknown) => ReactElement<{
      store: unknown;
      contributionSource: GameDetailsStatusContributionSource;
    }>;
    const retainedContributionSource = retainedHeader({}).props.contributionSource;
    const notifyRetainedHeader = vi.fn();
    const unsubscribe = retainedContributionSource.subscribe(notifyRetainedHeader);

    expect(retainedHeader({}).props.store).toBe(firstStore);

    firstSurface.dispose();
    expect(retainedContributionSource.getSnapshot()).toBeNull();
    const replacementStore = createLudusaviStateStore();
    const replacementSurface = createGameDetailsStatusSurface(replacementStore, {
      registerDetailsOwner: vi.fn(), subscribeDetailsPresentation: vi.fn(() => () => {}), shouldDetailsRowYield: vi.fn(() => false),
    } as any);

    // This is the original header function, as it remains mounted while
    // Decky replaces the plugin. It must no longer use the disposed store.
    expect(retainedHeader({}).props.store).toBe(replacementStore);
    expect(retainedContributionSource.getSnapshot()?.store).toBe(replacementStore);
    expect(notifyRetainedHeader).toHaveBeenCalledTimes(2);
    unsubscribe();
    replacementSurface.dispose();
  });

  it("keeps a same-game fallback row measurable but non-painting", () => {
    expect(detailsRowPaintStyle(true)).toEqual({
      opacity: 0,
      pointerEvents: "none",
    });
    expect(detailsRowPaintStyle(false)).toEqual({});
  });

  it("composes through the deferred Cloud component in the real four-child header", () => {
    const play = createElement("play");
    const cloud = createElement(() => null);
    const feedback = createElement("feedback");
    const tabs = createElement("tabs");
    const root = createElement("app-details-root", { marker: "native" }, [play, cloud, feedback, tabs]);
    const row = createElement("ludusavi-status");
    const contributed = composeInNativeStatusSlot(root, row) as any;
    expect(contributed.props.marker).toBe("native");
    expect(contributed).not.toBe(root);
    expect(contributed.props.children).toHaveLength(4);
    expect(contributed.props.children[0]).toBe(play);
    expect(contributed.props.children[1].props.nativeStatus).toBe(cloud);
    expect(contributed.props.children[1].props.row).toBe(row);
    expect(contributed.props.children[2]).toBe(feedback);
    expect(contributed.props.children[3]).toBe(tabs);
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
    vi.stubGlobal("window", { getComputedStyle: () => ({ display: "block", visibility: "visible", overflow: "hidden" }) });
    vi.stubGlobal("document", {
      documentElement: { clientHeight: 800, clientWidth: 1280 },
      elementFromPoint: () => element,
    });

    expect(isVisibleStatusBand(element as unknown as HTMLDivElement, true)).toBe(false);
    vi.unstubAllGlobals();
  });
  it("keeps a fully visible row valid through a boxless display-contents ancestor", () => {
    const ancestor = {
      hidden: false,
      parentElement: null,
      getBoundingClientRect: () => ({ width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 }),
    };
    const element = {
      hidden: false,
      parentElement: ancestor,
      getBoundingClientRect: () => ({ width: 1280, height: 30, top: 40, left: 0, right: 1280, bottom: 70 }),
      contains: (candidate: unknown) => candidate === element,
    };
    vi.stubGlobal("window", {
      getComputedStyle: (candidate: unknown) => ({
        display: candidate === ancestor ? "contents" : "flex",
        visibility: "visible",
        overflow: "visible",
      }),
    });
    vi.stubGlobal("document", {
      documentElement: { clientHeight: 800, clientWidth: 1280 },
      elementFromPoint: () => element,
    });

    expect(isVisibleStatusBand(element as unknown as HTMLDivElement, true)).toBe(true);
    vi.unstubAllGlobals();
  });

  it("measures the row in its owning Gamepad document, not SharedJSContext", () => {
    const element = {
      hidden: false,
      parentElement: null,
      ownerDocument: undefined as unknown,
      getBoundingClientRect: () => ({ width: 854, height: 30, top: 252, left: 0, right: 854, bottom: 282 }),
      contains: (candidate: unknown) => candidate === element,
    };
    const gamepadWindow = {
      getComputedStyle: () => ({ display: "flex", visibility: "visible", overflow: "visible" }),
    };
    const gamepadDocument = {
      documentElement: { clientHeight: 534, clientWidth: 854 },
      elementFromPoint: () => element,
      defaultView: gamepadWindow,
    };
    element.ownerDocument = gamepadDocument;
    vi.stubGlobal("window", {
      getComputedStyle: () => ({ display: "none", visibility: "hidden", overflow: "hidden" }),
    });
    vi.stubGlobal("document", {
      documentElement: { clientHeight: 1, clientWidth: 1 },
      elementFromPoint: () => null,
    });

    expect(isVisibleStatusBand(element as unknown as HTMLDivElement, true)).toBe(true);
    vi.unstubAllGlobals();
  });

  it("observes the partial-to-full threshold needed for details ownership", () => {
    const bounds = { width: 1280, height: 30 };
    expect(DETAILS_STATUS_VISIBILITY_THRESHOLDS).toEqual([0, 0.99, 1]);
    expect(isFullyIntersecting({
      isIntersecting: true,
      intersectionRatio: 0.5,
      intersectionRect: { width: 640, height: 30 },
      boundingClientRect: bounds,
    })).toBe(false);
    expect(isFullyIntersecting({
      isIntersecting: true,
      intersectionRatio: 1,
      intersectionRect: bounds,
      boundingClientRect: bounds,
    })).toBe(true);
  });
});
