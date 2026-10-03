import { act, cloneElement, createContext, createElement, useEffect, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { parseHTML } from "linkedom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const nativeClasses = vi.hoisted(() => ({
  play: {
    CloudStatusRow: "native-status-row", CloudStatusIcon: "native-status-icon",
    CloudStatusLabel: "native-status-label", CloudIconSVG: "native-status-svg",
    CloudSyncProblem: "native-status-problem", CloudSynching: "native-status-active",
    CloudStatusUploading: "native-status-uploading",
  } as Record<string, string | undefined>,
  root: { AppDetailsRoot: "native-details-root", PlaySection: "native-play-section" },
}));
const routeMock = vi.hoisted(() => ({ addPatch: vi.fn((_: string, patch: unknown) => patch), removePatch: vi.fn() }));
vi.mock("@decky/api", () => ({ routerHook: routeMock }));
vi.mock("@decky/ui", () => ({ playSectionClasses: nativeClasses.play, basicAppDetailsSectionStylerClasses: nativeClasses.root }));
vi.mock("../utils/logging", () => ({ log: vi.fn() }));
vi.mock("../utils/steam", () => ({ sessionFromAppOverview: () => null }));
vi.mock("../utils/steamRuntime", () => ({ getAppDetailsForAppID: () => null, getAppOverviewForAppID: () => null, getGamepadMainWindow: () => null, subscribeToAppDetails: () => () => {} }));
import { createGameDetailsStatusSurface, composeInNativeStatusSlot, GameDetailsStatusRow, isStatusLabelFullyVisible, isVisibleStatusBand } from "./gameDetailsStatus";
import type { GameDetailsStatusViewModel } from "./gameDetailsStatusModel";
import { createLudusaviStateStore } from "../state/ludusaviState";

const model: GameDetailsStatusViewModel = {
  eligibility: "eligible", kind: "local_backup_available", status: "has_backup",
  localStatus: "has_backup", syncStatus: null, syncVerification: "unverified",
  label: "Ludusavi: Up to date", description: "Local backup available; remote delivery is not verified.",
  tone: "success", active: false, showRow: true, canOwnStatusArea: true,
};
let root: Root;
let host: HTMLElement;
let document: Document;
let window: Window & { MutationObserver: typeof MutationObserver };
const owners = new Set<string>();
const surface = {
  subscribeDetailsPresentation: () => () => {}, shouldDetailsRowYield: () => false,
  registerDetailsPage: () => () => {},
  registerDetailsOwner: ({ appID }: { appID: string }) => { owners.add(appID); return () => owners.delete(appID); },
};

beforeEach(() => {
  const dom = parseHTML("<html><head></head><body><main></main></body></html>");
  document = dom.document as unknown as Document;
  window = dom.window as unknown as typeof window;
  vi.stubGlobal("window", window); vi.stubGlobal("document", document);
  vi.stubGlobal("HTMLElement", dom.window.HTMLElement); vi.stubGlobal("Node", dom.window.Node);
  vi.stubGlobal("MutationObserver", dom.window.MutationObserver);
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  Object.defineProperty(document.documentElement, "clientWidth", { value: 854 });
  Object.defineProperty(document.documentElement, "clientHeight", { value: 534 });
  Object.defineProperty(dom.window.HTMLElement.prototype, "getBoundingClientRect", { configurable: true, writable: true, value() {
    const hidden = this.style.display === "none";
    return { width: hidden ? 0 : 854, height: hidden ? 0 : 30, left: 0, top: 252, right: hidden ? 0 : 854, bottom: hidden ? 252 : 282 };
  } });
  Object.defineProperty(dom.window.HTMLElement.prototype, "getClientRects", { configurable: true, value() { return this.style.display === "none" ? [] : [this.getBoundingClientRect()]; } });
  window.getComputedStyle = ((element: HTMLElement) => ({ display: element.style.display || "flex", visibility: "visible", opacity: element.style.opacity || "1", overflow: "visible" })) as typeof getComputedStyle;
  window.requestAnimationFrame = callback => setTimeout(() => callback(0), 0) as unknown as number;
  window.cancelAnimationFrame = id => clearTimeout(id);
  document.elementFromPoint = () => document.querySelector('[data-sdh-ludusavi-status-row="true"]');
  host = document.querySelector("main")!;
  root = createRoot(host);
  owners.clear(); nativeClasses.play.CloudStatusRow = "native-status-row";
});
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); });

const pluginRow = (suppressed = false) => createElement(GameDetailsStatusRow, { appID: "100", model, statusSurface: surface, suppressed });
const header = (nativeStatus: ReactElement) => createElement("div", { className: "native-details-root" }, [
  createElement("div", { key: "play", className: "native-play-section" }, "Play"), cloneElement(nativeStatus, { key: "cloud" }),
  createElement("div", { key: "feedback" }), createElement("div", { key: "activity" }, "Activity"),
]);
const render = async (node: ReactElement) => { await act(async () => { root.render(node); await new Promise<void>((resolve) => setTimeout(resolve, 20)); }); };

it("lets direct-child, sibling, and descendant Steam theme selectors reach the fallback row", async () => {
  await render(composeInNativeStatusSlot(header(createElement(() => null)), pluginRow()) as ReactElement);
  const row = host.querySelector(".native-details-root > .native-play-section + .native-status-row") as HTMLElement | null;
  expect(row).not.toBeNull();
  expect(row?.style.display).not.toBe("none");
  expect(row?.querySelector(":scope > .native-status-icon > svg.native-status-svg")).not.toBeNull();
  expect(row?.querySelector(":scope > .native-status-label")?.textContent).toContain("Ludusavi: Up to date");
  expect(row?.getAttribute("aria-label")).toContain("remote delivery is not verified");
  expect(row?.querySelector("[tabindex],button,a,input")).toBeNull();
});

it("keeps native Cloud controls mounted and authoritative even when a theme hides them", async () => {
  const activate = vi.fn(); let mounts = 0; let unmounts = 0;
  function NativeCloud() {
    useEffect(() => { mounts++; return () => { unmounts++; }; }, []);
    return createElement("div", { className: "native-status-row", style: { display: "none" } }, createElement("button", { onClick: activate }, "Native Cloud action"));
  }
  const native = createElement(NativeCloud);
  await render(composeInNativeStatusSlot(header(native), pluginRow()) as ReactElement);
  const row = host.querySelector('[data-sdh-ludusavi-status-row="true"]') as HTMLElement;
  expect(row?.style.display).toBe("none");
  expect(owners.size).toBe(0);
  await act(async () => { (host.querySelector("button") as HTMLButtonElement).click(); });
  expect(activate).toHaveBeenCalledTimes(1);
  expect(mounts).toBe(1); expect(unmounts).toBe(0);
});

it("does not replace native presentation when Steam class capabilities are unavailable", async () => {
  nativeClasses.play.CloudStatusRow = undefined;
  await render(composeInNativeStatusSlot(header(createElement("button", null, "Native Cloud")), pluginRow()) as ReactElement);
  expect(host.querySelector('[data-sdh-ludusavi-status-row="true"]')).toBeNull();
  expect(host.querySelector("button")?.textContent).toBe("Native Cloud");
});

it("accepts a fully visible compact indicator instead of requiring a full-height status band", () => {
  const row = document.createElement("div"); document.body.append(row);
  row.getBoundingClientRect = () => ({ width: 32, height: 16, left: 640, top: 100, right: 672, bottom: 116 } as DOMRect);
  document.elementFromPoint = () => row;
  expect(isVisibleStatusBand(row, true)).toBe(true);
});

it("rejects theme-hidden opacity while allowing only our own temporary paint suppression", () => {
  const row = document.createElement("div"); document.body.append(row);
  document.elementFromPoint = () => row;
  let themeOpacity = "0";
  window.getComputedStyle = ((element: HTMLElement) => ({ display: "flex", visibility: "visible", overflow: "visible", opacity: element === row ? element.style.getPropertyValue("opacity") || themeOpacity : "1" })) as typeof getComputedStyle;
  expect(isVisibleStatusBand(row, true)).toBe(false);
  row.setAttribute("data-sdh-ludusavi-paint-suppressed", "true"); row.style.opacity = "0";
  expect(isVisibleStatusBand(row, true)).toBe(false);
  themeOpacity = "1";
  expect(isVisibleStatusBand(row, true)).toBe(true);
  expect(row.style.opacity).toBe("0");
});

it("rejects a clipped full label until its available content width recovers", () => {
  const row = document.createElement("div");
  const label = document.createElement("span");
  label.dataset.sdhLudusaviStatusLabel = "true";
  row.append(label); document.body.append(row);
  row.getBoundingClientRect = () => ({ width: 100, height: 30, left: 0, top: 0, right: 100, bottom: 30 } as DOMRect);
  label.getBoundingClientRect = () => ({ width: 140, height: 22, left: 0, top: 4, right: 140, bottom: 26 } as DOMRect);
  Object.defineProperties(label, {
    clientWidth: { configurable: true, value: 100 }, scrollWidth: { configurable: true, value: 140 },
    clientHeight: { configurable: true, value: 22 }, scrollHeight: { configurable: true, value: 22 },
  });

  expect(isStatusLabelFullyVisible(row)).toBe(false);
  label.getBoundingClientRect = () => ({ width: 100, height: 22, left: 0, top: 4, right: 100, bottom: 26 } as DOMRect);
  Object.defineProperty(label, "scrollWidth", { configurable: true, value: 100 });
  expect(isStatusLabelFullyVisible(row)).toBe(true);
});

it("rechecks row ownership when a full post-game label changes", async () => {
  await render(pluginRow());
  expect(owners).toEqual(new Set(["100"]));
  const label = host.querySelector('[data-sdh-ludusavi-status-label="true"]') as HTMLElement;
  Object.defineProperties(label, {
    clientWidth: { configurable: true, value: 100 }, scrollWidth: { configurable: true, value: 300 },
    clientHeight: { configurable: true, value: 22 }, scrollHeight: { configurable: true, value: 22 },
  });
  label.getBoundingClientRect = () => ({ width: 300, height: 22, left: 0, top: 256, right: 300, bottom: 278 } as DOMRect);
  const clippedModel = { ...model, label: `Ludusavi: ${"W".repeat(64)}` };

  await render(createElement(GameDetailsStatusRow, { appID: "100", model: clippedModel, statusSurface: surface, suppressed: false }));
  expect(owners).toEqual(new Set());

  Object.defineProperties(label, {
    clientWidth: { configurable: true, value: 854 }, scrollWidth: { configurable: true, value: 854 },
  });
  label.getBoundingClientRect = () => ({ width: 854, height: 22, left: 0, top: 256, right: 854, bottom: 278 } as DOMRect);
  await render(createElement(GameDetailsStatusRow, { appID: "100", model: { ...clippedModel, label: `${clippedModel.label} ` }, statusSurface: surface, suppressed: false }));
  expect(owners).toEqual(new Set(["100"]));
});

it("transfers page presence on route changes and runtime replacement without requiring a status row", async () => {
  const firstPages = vi.fn(() => vi.fn());
  const first = createGameDetailsStatusSurface(createLudusaviStateStore(), {
    subscribeDetailsPresentation: () => () => {}, shouldDetailsRowYield: () => false,
    registerDetailsPage: firstPages, registerDetailsOwner: () => () => {},
  });
  const patch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
  const context = createContext<unknown>(null);
  const nativeHeader = () => header(createElement(() => null));
  const child = createElement("native-route", {
    renderFunc: () => createElement(context.Provider, { value: nativeHeader }, createElement("native-children")),
  });
  const patched = patch({ path: "/library/app/:appid", children: child });
  const routeHeader = (appID: string) => patched.children.props.renderFunc({ params: { appid: appID } }).props.value;

  await render(createElement(routeHeader("100"), {}));
  expect(firstPages).toHaveBeenCalledWith("100");
  const firstCleanup = firstPages.mock.results[0]?.value as ReturnType<typeof vi.fn>;

  await render(createElement(routeHeader("101"), {}));
  expect(firstCleanup).toHaveBeenCalledOnce();
  expect(firstPages).toHaveBeenLastCalledWith("101");

  const replacementPages = vi.fn(() => vi.fn());
  const replacement = createGameDetailsStatusSurface(createLudusaviStateStore(), {
    subscribeDetailsPresentation: () => () => {}, shouldDetailsRowYield: () => false,
    registerDetailsPage: replacementPages, registerDetailsOwner: () => () => {},
  });
  await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 20)); });
  expect(replacementPages).toHaveBeenCalledWith("101");
  expect(firstPages.mock.results.at(-1)?.value).toHaveBeenCalledOnce();

  first.dispose(); replacement.dispose();
  const routePatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
  if (routePatch?.removalTimer !== null && routePatch?.removalTimer !== undefined) clearTimeout(routePatch.removalTimer);
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRoutePatch");
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRegistry");
});
