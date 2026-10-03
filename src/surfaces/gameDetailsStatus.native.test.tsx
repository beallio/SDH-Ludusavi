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
vi.mock("../utils/steam", () => ({ normalize: (name: string) => name.toLowerCase(), sessionFromAppOverview: () => null }));
vi.mock("../utils/steamRuntime", () => ({ getAppDetailsForAppID: () => null, getAppOverviewForAppID: () => null, getGamepadMainWindow: () => null, subscribeToAppDetails: () => () => {} }));
import { createGameDetailsStatusSurface, composeInNativeStatusSlot, GameDetailsStatusRow, isStatusLabelFullyVisible, isVisibleStatusBand } from "./gameDetailsStatus";
import type { GameDetailsStatusViewModel } from "./gameDetailsStatusModel";
import { createLudusaviStateStore } from "../state/ludusaviState";
import { createAutoSyncStatusSurface } from "./autoSyncStatusSurface";

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
  window.getComputedStyle = ((element: HTMLElement) => ({ display: element.style.display || "flex", visibility: element.style.visibility || "visible", opacity: element.style.opacity || "1", overflow: "visible" })) as typeof getComputedStyle;
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

it("rejects non-painted and vertically clipped full labels before visible text recovers", () => {
  const row = document.createElement("div");
  const label = document.createElement("span");
  label.dataset.sdhLudusaviStatusLabel = "true";
  row.append(label); document.body.append(row);
  row.getBoundingClientRect = () => ({ width: 100, height: 30, left: 0, top: 0, right: 100, bottom: 30 } as DOMRect);
  let labelBounds = { width: 100, height: 22, left: 0, top: 4, right: 100, bottom: 26 } as DOMRect;
  label.getBoundingClientRect = () => label.style.display === "none"
    ? ({ width: 0, height: 0, left: 0, top: 0, right: 0, bottom: 0 } as DOMRect)
    : labelBounds;
  Object.defineProperties(label, {
    clientWidth: { configurable: true, value: 100 }, scrollWidth: { configurable: true, value: 100 },
    clientHeight: { configurable: true, value: 22 }, scrollHeight: { configurable: true, value: 22 },
  });

  label.style.display = "none";
  expect(isStatusLabelFullyVisible(row)).toBe(false);
  label.style.removeProperty("display");
  label.style.visibility = "hidden";
  expect(isStatusLabelFullyVisible(row)).toBe(false);
  label.style.removeProperty("visibility");
  label.style.opacity = "0";
  expect(isStatusLabelFullyVisible(row)).toBe(false);
  label.style.removeProperty("opacity");
  labelBounds = { width: 100, height: 34, left: 0, top: 0, right: 100, bottom: 34 } as DOMRect;
  expect(isStatusLabelFullyVisible(row)).toBe(false);
  labelBounds = { width: 100, height: 22, left: 0, top: 4, right: 100, bottom: 26 } as DOMRect;
  expect(isStatusLabelFullyVisible(row)).toBe(true);
});

it("releases a row owner when only its paint style changes, then restores same-page fallback handoff", async () => {
  const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
  const store = createLudusaviStateStore();
  const statusSurface = createAutoSyncStatusSurface(view, store);
  const releasePage = statusSurface.registerDetailsPage("100");
  try {
    statusSurface.publish("backing_up", {
      source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 21,
      gameName: "Fixture", appID: "100", tracked: true,
    });
    const observation = store.getSnapshot().autoSyncObservations["100"];

    await render(createElement(GameDetailsStatusRow, { appID: "100", model, statusSurface, suppressed: false }));
    const row = host.querySelector('[data-sdh-ludusavi-status-row="true"]') as HTMLDivElement;
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(false);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));

    await act(async () => {
      row.style.display = "none";
      await new Promise<void>((resolve) => setTimeout(resolve, 20));
    });
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(true);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
    expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);

    await act(async () => {
      row.setAttribute("style", "");
      expect(isVisibleStatusBand(row, true)).toBe(true);
      await new Promise<void>((resolve) => setTimeout(resolve, 20));
    });
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(false);
    expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));
    expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);
  } finally {
    releasePage(); statusSurface.dispose();
  }
});

it("rechecks row ownership when a full post-game label changes", async () => {
  await render(pluginRow());
  expect(owners).toEqual(new Set(["100"]));
  const clippedModel = { ...model, label: `Ludusavi: ${"W".repeat(64)}` };
  await render(createElement(GameDetailsStatusRow, { appID: "100", model: clippedModel, statusSurface: surface, suppressed: false }));
  const label = host.querySelector('[data-sdh-ludusavi-status-label="true"]') as HTMLElement;
  Object.defineProperties(label, {
    clientWidth: { configurable: true, value: 100 }, scrollWidth: { configurable: true, value: 300 },
    clientHeight: { configurable: true, value: 22 }, scrollHeight: { configurable: true, value: 22 },
  });
  label.getBoundingClientRect = () => ({ width: 300, height: 22, left: 0, top: 256, right: 300, bottom: 278 } as DOMRect);

  await render(createElement(GameDetailsStatusRow, { appID: "100", model: { ...clippedModel, label: `${clippedModel.label} ` }, statusSurface: surface, suppressed: false }));
  expect(owners).toEqual(new Set());

  Object.defineProperties(label, {
    clientWidth: { configurable: true, value: 854 }, scrollWidth: { configurable: true, value: 854 },
  });
  label.getBoundingClientRect = () => ({ width: 854, height: 22, left: 0, top: 256, right: 854, bottom: 278 } as DOMRect);
  await render(createElement(GameDetailsStatusRow, { appID: "100", model: { ...clippedModel, label: `${clippedModel.label}  ` }, statusSurface: surface, suppressed: false }));
  expect(owners).toEqual(new Set(["100"]));
});

it("keeps same-page fallback active through an unsupported header and runtime replacement", async () => {
  const firstView = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
  const firstStore = createLudusaviStateStore();
  const firstStatusSurface = createAutoSyncStatusSurface(firstView, firstStore);
  const first = createGameDetailsStatusSurface(firstStore, firstStatusSurface);
  const patch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
  const context = createContext<unknown>(null);
  const child = createElement("native-route", {
    renderFunc: () => createElement(context.Provider, { value: {} }, createElement("native-children")),
  });
  const patched = patch({ path: "/library/app/:appid", children: child });
  await render(patched.children.props.renderFunc({ params: { appid: "100" } }));
  expect(host.querySelector("native-children")).not.toBeNull();
  firstStatusSurface.publish("backing_up", {
    source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 22,
    gameName: "Fixture", appID: "100", tracked: true,
  });
  expect(firstView.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));

  const replacementView = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
  const replacementStore = createLudusaviStateStore();
  const replacementStatusSurface = createAutoSyncStatusSurface(replacementView, replacementStore);
  const replacement = createGameDetailsStatusSurface(replacementStore, replacementStatusSurface);
  await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 20)); });
  expect(firstView.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));
  replacementStatusSurface.publish("syncthing_uploading", {
    source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 23,
    gameName: "Fixture", appID: "100", tracked: true,
  });
  expect(replacementView.sync).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));

  first.dispose(); replacement.dispose(); firstStatusSurface.dispose(); replacementStatusSurface.dispose();
  const routePatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
  if (routePatch?.removalTimer !== null && routePatch?.removalTimer !== undefined) clearTimeout(routePatch.removalTimer);
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRoutePatch");
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRegistry");
});

it("keeps same-page fallback active when the mounted route body never renders its optional header", async () => {
  const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
  const store = createLudusaviStateStore();
  store.applyRefreshResult({
    games: [{ name: "Fixture", steam_id: "100", configured: true, has_backup: false, needs_first_backup: true, error: null, status: "needs_first_backup" }],
    aliases: {}, history: {}, dependency_error: null,
  });
  const statusSurface = createAutoSyncStatusSurface(view, store);
  const gameDetailsSurface = createGameDetailsStatusSurface(store, statusSurface);
  const patch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
  const context = createContext<unknown>(null);
  const nativeHeader = vi.fn(() => createElement("native-header"));
  type RouteBodyProps = { overview: { appid: number }; details: { nPlaytimeForever: number } };
  const routeBody = ({ details }: RouteBodyProps) => createElement("native-children", {
    "data-sdh-playtime": "true",
  }, details.nPlaytimeForever);
  const child = createElement("native-route", {
    renderFunc: () => createElement(
      context.Provider,
      { value: nativeHeader },
      createElement(routeBody, { overview: { appid: 100 }, details: { nPlaytimeForever: 12 } }),
    ),
  });
  const patched = patch({ path: "/library/app/:appid", children: child });

  await render(patched.children.props.renderFunc({ params: { appid: "100" } }));
  expect(host.querySelector("native-children")?.textContent).toBe("12");
  expect(nativeHeader).not.toHaveBeenCalled();

  statusSurface.publish("backing_up", {
    source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 24,
    gameName: "Fixture", appID: "100", tracked: true,
  });
  const observation = store.getSnapshot().autoSyncObservations["100"];
  expect(observation).toBeDefined();
  expect(view.sync).toHaveBeenLastCalledWith(expect.objectContaining({ status: "backing_up", visible: true }));
  expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);

  gameDetailsSurface.dispose(); statusSurface.dispose();
  const routePatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
  if (routePatch?.removalTimer !== null && routePatch?.removalTimer !== undefined) clearTimeout(routePatch.removalTimer);
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRoutePatch");
  Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRegistry");
});
