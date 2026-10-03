import { cloneElement, createContext, createElement, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const routeMock = vi.hoisted(() => ({ addPatch: vi.fn((_: string, patch: unknown) => patch), removePatch: vi.fn() }));
vi.mock("@decky/api", () => ({ routerHook: routeMock }));
vi.mock("@decky/ui", () => ({}));
vi.mock("../ludusaviLauncher", () => ({}));
vi.mock("../utils/logging", () => ({ log: vi.fn() }));
vi.mock("../utils/steam", () => ({
  normalize: (name: string) => name.toLowerCase(),
  sessionFromAppOverview: (app: any) => app?.display_name ? { name: app.display_name, appID: String(app.appid) } : null,
}));
vi.mock("../utils/steamRuntime", () => ({
  getAppDetailsForAppID: vi.fn(() => null), getAppOverviewForAppID: vi.fn(() => null), subscribeToAppDetails: vi.fn(() => () => {}),
}));

import { createLudusaviStateStore } from "../state/ludusaviState";
import { createAutoSyncStatusSurface, type DetailsStatusPresentationSurface } from "./autoSyncStatusSurface";
import {
  createGameDetailsStatusSurface,
  type GameDetailsStatusContributionSource,
  isVisibleStatusBand,
  isFullyIntersecting,
} from "./gameDetailsStatus";

describe("game details route adapter", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    const routePatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
    if (routePatch?.removalTimer !== null && routePatch?.removalTimer !== undefined) {
      clearTimeout(routePatch.removalTimer);
    }
    Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRoutePatch");
    Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRegistry");
  });

  it("clones the supported React route child, keeps its props, and reuses the native header wrapper", () => {
    const surface = createGameDetailsStatusSurface(createLudusaviStateStore(), {
      registerDetailsOwner: vi.fn(), registerDetailsPage: vi.fn(() => () => {}),
      subscribeDetailsPresentation: vi.fn(() => () => {}), shouldDetailsRowYield: vi.fn(() => false),
    } satisfies DetailsStatusPresentationSurface);
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
    const firstProvider = first as ReactElement<{ children: ReactElement; value: unknown }>;
    const secondProvider = second as ReactElement<{ children: ReactElement; value: unknown }>;
    expect(firstProvider.props.children).toBeDefined();
    expect(firstProvider.props.value).not.toBe(nativeHeader);
    expect(secondProvider.props.value).toBe(firstProvider.props.value);

    const unsupported = { children: {} };
    expect(patch(unsupported)).toBe(unsupported);
    surface.dispose();
    expect(routeMock.removePatch).not.toHaveBeenCalled();
    vi.runOnlyPendingTimers();
    expect(routeMock.removePatch).toHaveBeenCalledWith("/library/app/:appid", patch);
  });

  it("preserves a native provider root for downstream details patches in cold and hot-reload order", () => {
    const surface = createGameDetailsStatusSurface(createLudusaviStateStore(), {
      registerDetailsOwner: vi.fn(), registerDetailsPage: vi.fn(() => () => {}),
      subscribeDetailsPresentation: vi.fn(() => () => {}), shouldDetailsRowYield: vi.fn(() => false),
    } satisfies DetailsStatusPresentationSurface);
    try {
      const sdhPatch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
      const context = createContext<unknown>(null);
      const nativeHeader = () => createElement("native-header");
      type PlayTimeDetails = { nPlaytimeForever: number };
      type RouteBodyProps = { overview: { appid: number }; details: PlayTimeDetails };
      const routeBody = ({ details }: RouteBodyProps) => createElement("output", {
        "data-sdh-playtime": "true",
      }, details.nPlaytimeForever);

      const withPlayTimeUpdate = (route: any) => {
        const child = route.children as ReactElement<{ renderFunc: (...args: unknown[]) => ReactElement }>;
        return {
          ...route,
          children: cloneElement(child, {
            ...child.props,
            renderFunc: (...args: unknown[]) => {
              const result = child.props.renderFunc(...args) as ReactElement<{ children: ReactElement<RouteBodyProps> }>;
              // This is the direct access pattern used by the installed downstream
              // PlayTime route patch. It must not see an SDH wrapper Fragment.
              const overview = result.props.children.props.overview;
              const details = result.props.children.props.details;
              if (overview.appid === 100) details.nPlaytimeForever = 0;
              return result;
            },
          }),
        };
      };
      const makeRoute = (details: PlayTimeDetails, headerValue: unknown = nativeHeader) => ({
        path: "/library/app/:appid",
        children: createElement("native-route", {
          renderFunc: () => createElement(
            context.Provider,
            { value: headerValue },
            createElement(routeBody, { overview: { appid: 100 }, details }),
          ),
        }),
      });
      const makeNonProviderRoute = (details: PlayTimeDetails) => ({
        path: "/library/app/:appid",
        children: createElement("native-route", {
          renderFunc: () => createElement(
            "native-route-result",
            null,
            createElement(routeBody, { overview: { appid: 100 }, details }),
          ),
        }),
      });
      const expectPeerAndNativeRender = (
        result: ReactElement<{
          children: ReactElement<RouteBodyProps>;
          value: unknown;
        }>,
        details: PlayTimeDetails,
        headerValue: unknown,
        isProvider = true,
      ) => {
        expect(result.type).toBe(isProvider ? context.Provider : "native-route-result");
        expect(result.props.children.props.overview.appid).toBe(100);
        expect(details.nPlaytimeForever).toBe(0);
        const presenceBoundary = (result.props.children.type as (props: RouteBodyProps) => ReactElement<{ children: ReactElement[] }>)(result.props.children.props);
        const nativeRouteBody = presenceBoundary.props.children[1] as ReactElement<RouteBodyProps, typeof routeBody>;
        expect(nativeRouteBody.type).toBe(routeBody);
        expect(nativeRouteBody.props.overview.appid).toBe(100);
        const visibleRouteBody = nativeRouteBody.type(nativeRouteBody.props);
        expect((visibleRouteBody.props as { children?: unknown }).children).toBe(0);
        if (isProvider && typeof result.props.value === "function") {
          const headerBoundary = result.props.value({});
          const statusHeader = headerBoundary.props.children as ReactElement<{ header: () => ReactElement }>;
          expect(statusHeader.props.header().type).toBe("native-header");
        } else if (isProvider) {
          expect(result.props.value).toBe(headerValue);
        }
      };

      const coldDetails = { nPlaytimeForever: -999 };
      const coldRendered = withPlayTimeUpdate(sdhPatch(makeRoute(coldDetails)))
        .children.props.renderFunc({ params: { appid: "100" } });
      expectPeerAndNativeRender(coldRendered, coldDetails, nativeHeader);

      const hotDetails = { nPlaytimeForever: -999 };
      const hotRendered = sdhPatch(withPlayTimeUpdate(makeRoute(hotDetails)))
        .children.props.renderFunc({ params: { appid: "100" } });
      expectPeerAndNativeRender(hotRendered, hotDetails, nativeHeader);

      const unsupportedHeader = {};
      const coldUnsupportedDetails = { nPlaytimeForever: -999 };
      const coldUnsupportedRendered = withPlayTimeUpdate(sdhPatch(makeRoute(coldUnsupportedDetails, unsupportedHeader)))
        .children.props.renderFunc({ params: { appid: "100" } });
      expectPeerAndNativeRender(coldUnsupportedRendered, coldUnsupportedDetails, unsupportedHeader);

      const hotUnsupportedDetails = { nPlaytimeForever: -999 };
      const hotUnsupportedRendered = sdhPatch(withPlayTimeUpdate(makeRoute(hotUnsupportedDetails, unsupportedHeader)))
        .children.props.renderFunc({ params: { appid: "100" } });
      expectPeerAndNativeRender(hotUnsupportedRendered, hotUnsupportedDetails, unsupportedHeader);

      const nonProviderDetails = { nPlaytimeForever: -999 };
      const nonProviderRendered = withPlayTimeUpdate(sdhPatch(makeNonProviderRoute(nonProviderDetails)))
        .children.props.renderFunc({ params: { appid: "100" } });
      expectPeerAndNativeRender(nonProviderRendered, nonProviderDetails, undefined, false);
    } finally {
      surface.dispose();
    }
  });

  it("keeps the mounted route contribution alive through a dispose and replacement without adding another patch", () => {
    const firstStore = createLudusaviStateStore();
    const firstSurface = createGameDetailsStatusSurface(firstStore, {
      registerDetailsOwner: vi.fn(), registerDetailsPage: vi.fn(() => () => {}),
      subscribeDetailsPresentation: vi.fn(() => () => {}), shouldDetailsRowYield: vi.fn(() => false),
    } satisfies DetailsStatusPresentationSurface);
    const firstPatch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
    const context = createContext<unknown>(null);
    const nativeHeader = () => createElement("native-header");
    const originalRender = vi.fn(() => createElement(context.Provider, { value: nativeHeader }, createElement("native-children")));
    const child = createElement("native-route", { renderFunc: originalRender });
    const patched = firstPatch({ path: "/library/app/:appid", children: child });
    const rendered = patched.children.props.renderFunc({ params: { appid: "100" } });
    const retainedProvider = rendered as ReactElement<{ value: unknown }>;
    const retainedHeader = retainedProvider.props.value as (props: unknown) => ReactElement<{
      children: ReactElement;
    }>;
    const retainedStatusHeader = () => retainedHeader({}).props.children as ReactElement<{
      store: unknown;
      contributionSource: GameDetailsStatusContributionSource;
    }>;
    const retainedContributionSource = retainedStatusHeader().props.contributionSource;
    const notifyRetainedHeader = vi.fn();
    const unsubscribe = retainedContributionSource.subscribe(notifyRetainedHeader);

    expect(retainedStatusHeader().props.store).toBe(firstStore);

    firstSurface.dispose();
    expect(retainedContributionSource.getSnapshot()).toBeNull();
    expect(routeMock.removePatch).not.toHaveBeenCalled();
    const replacementStore = createLudusaviStateStore();
    const replacementSurface = createGameDetailsStatusSurface(replacementStore, {
      registerDetailsOwner: vi.fn(), registerDetailsPage: vi.fn(() => () => {}),
      subscribeDetailsPresentation: vi.fn(() => () => {}), shouldDetailsRowYield: vi.fn(() => false),
    } satisfies DetailsStatusPresentationSurface);

    // This is the original mounted route contribution. It must update to the
    // current runtime rather than requiring Steam to navigate or rerender it.
    expect(retainedStatusHeader().props.store).toBe(replacementStore);
    expect(retainedContributionSource.getSnapshot()?.store).toBe(replacementStore);
    expect(notifyRetainedHeader).toHaveBeenCalledTimes(2);
    expect(routeMock.addPatch).toHaveBeenCalledTimes(1);
    unsubscribe();
    replacementSurface.dispose();
    vi.runOnlyPendingTimers();
    expect(routeMock.removePatch).toHaveBeenCalledTimes(1);
  });

  it("replaces only an older retained route patch when the plugin UI changes", () => {
    const statusSurface = {
      subscribeDetailsPresentation: vi.fn(() => () => {}),
      shouldDetailsRowYield: vi.fn(() => false),
      registerDetailsPage: vi.fn(() => () => {}),
      registerDetailsOwner: vi.fn(() => () => {}),
    } satisfies DetailsStatusPresentationSurface;
    const original = createGameDetailsStatusSurface(createLudusaviStateStore(), statusSurface);
    const oldPatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
    expect(oldPatch).toBeDefined();
    if (!oldPatch) throw new Error("The original patch was not installed");
    Reflect.deleteProperty(oldPatch, "version");
    original.dispose();

    const replacement = createGameDetailsStatusSurface(createLudusaviStateStore(), statusSurface);

    expect(routeMock.removePatch).toHaveBeenCalledWith("/library/app/:appid", oldPatch.installedPatch);
    expect(routeMock.addPatch).toHaveBeenCalledTimes(2);
    expect(globalThis.__sdhLudusaviGameDetailsStatusRoutePatch).not.toBe(oldPatch);
    replacement.dispose();
    vi.runOnlyPendingTimers();
    expect(routeMock.removePatch).toHaveBeenCalledTimes(2);
  });



  it("hands a recovered native band from the fallback strip to one row, then restores the strip", () => {
    vi.stubGlobal("window", globalThis);
    const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
    const surface = createAutoSyncStatusSurface(view, createLudusaviStateStore());
    const releasePage = surface.registerDetailsPage("100");
    surface.publish("backing_up", {
      source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 9,
      gameName: "Fixture", appID: "100", tracked: true,
    });

    let clipped = true;
    const nativeContainer = {
      hidden: false,
      parentElement: null,
      getBoundingClientRect: () => clipped
        ? { width: 854, height: 15, top: 252, left: 0, right: 854, bottom: 267 }
        : { width: 854, height: 30, top: 252, left: 0, right: 854, bottom: 282 },
    };
    const row = {
      hidden: false,
      parentElement: nativeContainer,
      getBoundingClientRect: () => ({ width: 854, height: 30, top: 252, left: 0, right: 854, bottom: 282 }),
      contains: (candidate: unknown) => candidate === row,
      ownerDocument: undefined as unknown,
    };
    const gamepadWindow = {
      getComputedStyle: () => ({ display: "flex", visibility: "visible", overflow: "hidden" }),
    };
    const gamepadDocument = {
      documentElement: { clientHeight: 534, clientWidth: 854 },
      defaultView: gamepadWindow,
      elementFromPoint: () => row,
    };
    row.ownerDocument = gamepadDocument;

    expect(surface.shouldDetailsRowYield("100")).toBe(true);
    expect(isVisibleStatusBand(row as unknown as HTMLDivElement, true)).toBe(false);

    clipped = false;
    expect(isVisibleStatusBand(row as unknown as HTMLDivElement, true)).toBe(true);
    const release = surface.registerDetailsOwner({ appID: "100", visible: true, layoutValid: true });
    expect(surface.shouldDetailsRowYield("100")).toBe(false);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));

    release();
    expect(surface.shouldDetailsRowYield("100")).toBe(true);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
    releasePage();
    surface.dispose();
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
