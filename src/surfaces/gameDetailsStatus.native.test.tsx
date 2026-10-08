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
  root: { PlaySection: "native-play-section" },
  details: { InnerContainer: "native-inner-container" },
}));
const routeMock = vi.hoisted(() => ({ addPatch: vi.fn((_: string, patch: unknown) => patch), removePatch: vi.fn() }));
vi.mock("@decky/api", () => ({ routerHook: routeMock }));
vi.mock("@decky/ui", () => ({
  playSectionClasses: nativeClasses.play,
  basicAppDetailsSectionStylerClasses: nativeClasses.root,
  appDetailsClasses: nativeClasses.details,
}));
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
  const icon = row?.querySelector(":scope > .native-status-icon > svg.native-status-svg") as SVGElement | null;
  expect(icon).not.toBeNull();
  expect(row?.querySelector(":scope > .native-status-label")?.textContent).toContain("Ludusavi: Up to date");
  expect(row?.getAttribute("aria-label")).toContain("remote delivery is not verified");
  expect(row?.querySelector("[tabindex],button,a,input")).toBeNull();
});

it("replaces a retained prior-renderer wrapper while preserving direct cold-peer overview and details props", async () => {
  const legacyPatch = vi.fn();
  const legacyInstalledPatch = vi.fn();
  globalThis.__sdhLudusaviGameDetailsStatusRoutePatch = {
    version: 23, patch: legacyPatch, installedPatch: legacyInstalledPatch, removalTimer: null,
  };
  const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
  const store = createLudusaviStateStore();
  const statusSurface = createAutoSyncStatusSurface(view, store);
  const gameDetailsSurface = createGameDetailsStatusSurface(store, statusSurface);

  try {
    expect(routeMock.removePatch).toHaveBeenCalledWith("/library/app/:appid", legacyInstalledPatch);
    const patch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
    const context = createContext<unknown>(null);
    const routeChild = createElement("native-route-body", {
      overview: { appid: 100 }, details: { nPlaytimeForever: 12 },
    }, "Cold peer content");
    const nativeRoute = createElement("native-route", {
      renderFunc: () => createElement(context.Provider, { value: {} }, routeChild),
    });
    const patched = patch({ path: "/library/app/:appid", children: nativeRoute });
    type ColdPeerProps = { overview: { appid: number }; details: { nPlaytimeForever: number } };
    const result = patched.children.props.renderFunc({ params: { appid: "100" } }) as ReactElement<{
      children: ReactElement<ColdPeerProps>;
    }>;
    const peerChild = result.props.children;

    expect(peerChild.props.overview.appid).toBe(100);
    expect(peerChild.props.details.nPlaytimeForever).toBe(12);
    await render(result);
    expect(host.querySelector("native-route-body")?.textContent).toBe("Cold peer content");
  } finally {
    gameDetailsSurface.dispose();
    statusSurface.dispose();
    const routePatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
    if (routePatch?.removalTimer !== null && routePatch?.removalTimer !== undefined) clearTimeout(routePatch.removalTimer);
    Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRoutePatch");
    Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRegistry");
  }
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

it("keeps foreign-center rejection for nonplugin and incomplete status rows", () => {
  const row = document.createElement("div");
  const hit = document.createElement("div");
  document.body.append(row, hit);
  document.elementFromPoint = () => hit;
  expect(isVisibleStatusBand(row, true)).toBe(false);

  row.dataset.sdhLudusaviStatusRow = "true";
  row.innerHTML = '<span data-sdh-ludusavi-status-label="true">Readable status</span><span data-sdh-ludusavi-status-icon="true"></span>';
  expect(isVisibleStatusBand(row, true)).toBe(false);
});

function footerPaintFixture() {
  const box = (left: number, top: number, right: number, bottom: number) =>
    ({ left, top, right, bottom, width: right - left, height: bottom - top } as DOMRect);
  const container = document.createElement("section");
  const row = document.createElement("div");
  row.dataset.sdhLudusaviStatusRow = "true";
  row.innerHTML = '<span data-sdh-ludusavi-status-icon="true"><svg viewBox="0 0 16 16"></svg></span><span data-sdh-ludusavi-status-label="true">Readable status</span>';
  const label = row.querySelector<HTMLElement>("[data-sdh-ludusavi-status-label]")!;
  const svg = row.querySelector("svg")!;
  const footer = document.createElement("div");
  const hit = document.createElement("div");
  footer.append(hit);
  container.append(row, footer);
  document.body.append(container);
  const colors = new Map<Element, string>([[footer, "rgba(0, 0, 0, 0.5)"]]);
  const opacities = new Map<Element, string>();
  container.getBoundingClientRect = () => box(0, 0, 854, 534);
  row.getBoundingClientRect = () => box(0, 494, 854, 524);
  label.getBoundingClientRect = () => box(300, 498, 600, 520);
  svg.getBoundingClientRect = () => box(276, 501, 292, 517);
  let paintTop = 519;
  footer.getBoundingClientRect = () => box(0, paintTop, 854, 534);
  hit.getBoundingClientRect = () => box(16, 508, 838, 546);
  document.elementFromPoint = () => hit;
  document.elementsFromPoint = () => [hit, label, row, container];
  document.createRange = (() => ({
    selectNodeContents() {},
    getClientRects: () => [box(300, 500, 600, 516)],
    detach() {},
  })) as unknown as typeof document.createRange;
  window.getComputedStyle = ((element: HTMLElement, pseudo?: string) => ({
    display: "block", visibility: "visible", opacity: opacities.get(element) ?? (element.style.opacity || "1"),
    overflow: "visible", overflowX: "visible", overflowY: "visible",
    backgroundColor: pseudo ? "rgba(0, 0, 0, 0)" : colors.get(element) ?? "rgba(0, 0, 0, 0)",
    backgroundImage: "none", color: "rgb(220, 222, 223)", content: "none",
    boxShadow: "none", textShadow: "none", filter: "none", backdropFilter: "none",
    maskImage: "none", clipPath: "none", mixBlendMode: "normal",
    borderTopWidth: "0px", borderRightWidth: "0px", borderBottomWidth: "0px", borderLeftWidth: "0px",
    borderTopColor: "rgba(0, 0, 0, 0)", borderRightColor: "rgba(0, 0, 0, 0)",
    borderBottomColor: "rgba(0, 0, 0, 0)", borderLeftColor: "rgba(0, 0, 0, 0)",
    pointerEvents: element.style.pointerEvents || "auto",
  })) as typeof window.getComputedStyle;
  return { container, row, footer, hit, colors, opacities, box, set paintTop(value: number) { paintTop = value; } };
}

it("admits a complete message behind a transparent hit layer when footer paint is below its text and icon", () => {
  const fixture = footerPaintFixture();
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
});

it("rejects footer paint that intersects the message rather than exempting the whole footer", () => {
  const fixture = footerPaintFixture();
  fixture.paintTop = 513;
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
});

it("admits a contained footer border image below the message but rejects potentially spilling paint", () => {
  const fixture = footerPaintFixture();
  const computedStyle = window.getComputedStyle;
  let outset = "0";
  window.getComputedStyle = ((element: HTMLElement, pseudo?: string) => ({
    ...computedStyle(element, pseudo),
    borderImageSource: element === fixture.footer && !pseudo ? "linear-gradient(white, transparent)" : "none",
    borderImageOutset: element === fixture.footer && !pseudo ? outset : "0",
  })) as typeof window.getComputedStyle;
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
  outset = "4px";
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
});

it("rejects a painted noninteractive child inside an otherwise transparent covering branch", () => {
  const fixture = footerPaintFixture();
  const paint = document.createElement("div");
  paint.style.pointerEvents = "none";
  paint.getBoundingClientRect = () => fixture.box(450, 503, 470, 512);
  fixture.colors.set(paint, "rgb(0, 0, 0)");
  fixture.hit.append(paint);
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
});

it("keeps painted overlay siblings authoritative even when they do not receive pointer hits", () => {
  const fixture = footerPaintFixture();
  const backdrop = document.createElement("div");
  backdrop.style.pointerEvents = "none";
  backdrop.getBoundingClientRect = () => fixture.box(0, 0, 854, 534);
  fixture.colors.set(backdrop, "rgba(0, 0, 0, 0.7)");
  fixture.container.append(backdrop);
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
  fixture.opacities.set(backdrop, "0");
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
});

it("rejects painted overlays outside the nearest shared footer ancestor", () => {
  const fixture = footerPaintFixture();
  const backdrop = document.createElement("div");
  backdrop.style.pointerEvents = "none";
  backdrop.getBoundingClientRect = () => fixture.box(0, 0, 854, 534);
  fixture.colors.set(backdrop, "rgba(0, 0, 0, 0.7)");
  document.body.append(backdrop);
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
  fixture.opacities.set(backdrop, "0");
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
});

it("does not admit a zero-opacity covering layer while a paint animation is still active", () => {
  const fixture = footerPaintFixture();
  const backdrop = document.createElement("div");
  backdrop.getBoundingClientRect = () => fixture.box(0, 0, 854, 534);
  fixture.colors.set(backdrop, "rgba(0, 0, 0, 0.7)");
  fixture.opacities.set(backdrop, "0");
  document.body.append(backdrop);
  let running = true;
  backdrop.getAnimations = () => running ? [{ playState: "running", pending: false } as Animation] : [];
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
  running = false;
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
});

it("keeps moving painted layers conservative until their animation settles", () => {
  const fixture = footerPaintFixture();
  const moving = document.createElement("div");
  moving.getBoundingClientRect = () => fixture.box(0, -30, 854, -10);
  fixture.colors.set(moving, "rgba(0, 0, 0, 0.7)");
  document.body.append(moving);
  let running = true;
  moving.getAnimations = () => running ? [{ playState: "running", pending: false } as Animation] : [];
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
  running = false;
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
});

it("does not treat non-rendered text in an offscreen overlay as message-covering paint", () => {
  const fixture = footerPaintFixture();
  const tooltip = document.createElement("div");
  const text = document.createTextNode("Offscreen title");
  tooltip.append(text);
  tooltip.getBoundingClientRect = () => fixture.box(8, -43, 276, -9);
  fixture.colors.set(tooltip, "rgb(35, 38, 46)");
  document.body.append(tooltip);
  let selected: Node | null = null;
  document.createRange = (() => ({
    selectNodeContents(node: Node) { selected = node; },
    getClientRects: () => selected === text ? [] : [fixture.box(300, 500, 600, 516)],
    detach() {},
  })) as unknown as typeof document.createRange;
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
});

it("admits offscreen generated paint only when its positioned host clips it on both axes", () => {
  const fixture = footerPaintFixture();
  const track = document.createElement("div");
  track.getBoundingClientRect = () => fixture.box(55, -29, 259, -23);
  document.body.append(track);
  const computedStyle = window.getComputedStyle;
  let pseudoPosition = "absolute";
  let clips = true;
  window.getComputedStyle = ((element: HTMLElement, pseudo?: string) => ({
    ...computedStyle(element, pseudo),
    position: element === track ? pseudo ? pseudoPosition : "relative" : "static",
    overflowX: element === track && clips ? "hidden" : "visible",
    overflowY: element === track && clips ? "hidden" : "visible",
    content: element === track && pseudo === "::before" ? '""' : "none",
    backgroundColor: element === track && pseudo === "::before" ? "rgb(26, 159, 255)" : "rgba(0, 0, 0, 0)",
  })) as typeof window.getComputedStyle;
  expect(isVisibleStatusBand(fixture.row, true)).toBe(true);
  clips = false;
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
  clips = true;
  pseudoPosition = "fixed";
  expect(isVisibleStatusBand(fixture.row, true)).toBe(false);
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

it("releases and reacquires native ownership for footer and overlay paint changes without replacing active facts", async () => {
  const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
  const store = createLudusaviStateStore();
  store.applyRefreshResult({
    games: [{ name: "Fixture", steam_id: "100", configured: true, has_backup: true, needs_first_backup: false, error: null, status: "has_backup" }],
    aliases: {}, history: {}, dependency_error: null,
  });
  const statusSurface = createAutoSyncStatusSurface(view, store);
  const releasePage = statusSurface.registerDetailsPage("100");
  const box = (left: number, top: number, right: number, bottom: number) =>
    ({ left, top, right, bottom, width: right - left, height: bottom - top } as DOMRect);
  const footer = document.createElement("div");
  const hit = document.createElement("div");
  footer.append(hit);
  document.body.append(footer);
  let paintTop = 519;
  footer.getBoundingClientRect = () => box(0, paintTop, 854, 534);
  hit.getBoundingClientRect = () => box(16, 508, 838, 546);
  let row: HTMLDivElement | null = null;
  let label: HTMLElement | null = null;
  let icon: HTMLElement | null = null;
  let menu: HTMLElement | null = null;
  let centerHit: Element | null = null;
  document.elementFromPoint = () => centerHit ?? row;
  document.elementsFromPoint = () => [hit, ...(menu ? [menu] : []), ...(label ? [label] : []), ...(row ? [row] : []), host];
  document.createRange = (() => ({
    selectNodeContents() {},
    getClientRects: () => [box(300, 500, 600, 516)],
    detach() {},
  })) as unknown as typeof document.createRange;
  window.getComputedStyle = ((element: HTMLElement, pseudo?: string) => ({
    display: element.style.display || "block", visibility: element.style.visibility || "visible",
    opacity: element.style.opacity || "1", overflow: "visible", overflowX: "visible", overflowY: "visible",
    backgroundColor: pseudo ? "rgba(0, 0, 0, 0)" : element.style.backgroundColor || "rgba(0, 0, 0, 0)",
    backgroundImage: "none", color: "rgb(220, 222, 223)", content: "none",
    boxShadow: "none", textShadow: "none", filter: "none", backdropFilter: "none",
    maskImage: "none", clipPath: "none", mixBlendMode: "normal",
    borderTopWidth: "0px", borderRightWidth: "0px", borderBottomWidth: "0px", borderLeftWidth: "0px",
    borderTopColor: "rgba(0, 0, 0, 0)", borderRightColor: "rgba(0, 0, 0, 0)",
    borderBottomColor: "rgba(0, 0, 0, 0)", borderLeftColor: "rgba(0, 0, 0, 0)",
    pointerEvents: element.style.pointerEvents || "auto",
  })) as typeof getComputedStyle;
  const setBounds = (element: Element, bounds: DOMRect) => {
    Object.defineProperty(element, "getBoundingClientRect", { configurable: true, value: () => bounds });
  };
  const settlePaintMutations = async () => {
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 20)); });
  };

  try {
    statusSurface.publish("backing_up", {
      source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 22,
      gameName: "Fixture", appID: "100", tracked: true,
    });
    const observation = store.getSnapshot().autoSyncObservations["100"];
    expect(observation).toMatchObject({ status: "backing_up", activity: "active", generation: 22 });
    await render(createElement(GameDetailsStatusRow, { appID: "100", model, statusSurface, suppressed: false }));
    row = host.querySelector('[data-sdh-ludusavi-status-row="true"]') as HTMLDivElement;
    label = row.querySelector<HTMLElement>('[data-sdh-ludusavi-status-label="true"]');
    icon = row.querySelector<HTMLElement>('[data-sdh-ludusavi-status-icon="true"]');
    setBounds(row, box(0, 494, 854, 524));
    setBounds(label!, box(300, 498, 600, 520));
    setBounds(icon!, box(276, 501, 292, 517));
    setBounds(icon!.querySelector("svg")!, box(276, 501, 292, 517));
    centerHit = hit;
    footer.style.backgroundColor = "rgba(0, 0, 0, 0)";
    await settlePaintMutations();
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(false);

    paintTop = 513;
    footer.setAttribute("style", "background-color: rgba(0, 0, 0, 0.5)");
    await settlePaintMutations();
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(true);
    expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);

    paintTop = 519;
    footer.setAttribute("style", "background-color: rgba(0, 0, 0, 0)");
    menu = document.createElement("div");
    menu.style.pointerEvents = "none";
    menu.style.backgroundColor = "rgba(0, 0, 0, 0.7)";
    menu.getBoundingClientRect = () => box(0, 503, 854, 512);
    document.body.append(menu);
    await settlePaintMutations();
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(true);
    expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);

    menu.setAttribute("style", "pointer-events: none; background-color: rgba(0, 0, 0, 0.7); opacity: 0");
    await settlePaintMutations();
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(false);
    expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);

    // Linkedom exposes the matching Event constructor through its DOM window.
    const domWindow = window as unknown as { Event: typeof Event };
    const DOMEvent = domWindow.Event;
    footer.setAttribute("style", "background-color: rgba(0, 0, 0, 0.5)");
    await settlePaintMutations();
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(false);
    paintTop = 513;
    footer.dispatchEvent(new DOMEvent("transitionend", { bubbles: true }));
    await settlePaintMutations();
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(true);
    paintTop = 519;
    footer.dispatchEvent(new DOMEvent("transitioncancel", { bubbles: true }));
    await settlePaintMutations();
    expect(statusSurface.shouldDetailsRowYield("100")).toBe(false);
    expect(store.getSnapshot().autoSyncObservations["100"]).toBe(observation);
  } finally {
    menu?.remove();
    footer.remove();
    releasePage();
    statusSurface.dispose();
  }
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

it("keeps the same-page fallback through loading, multi-child, and empty route roots", async () => {
  const cases = [
    {
      name: "loading text",
      renderResult: () => createElement("native-loading", { "data-loading": "true" }, "Loading details"),
      assertOriginalContent: () => expect(host.querySelector("[data-loading=\"true\"]")?.textContent).toBe("Loading details"),
    },
    {
      name: "multi-child provider",
      renderResult: () => {
        const context = createContext<unknown>(null);
        return createElement(context.Provider, { value: {} }, [
          createElement("native-first", { key: "first" }, "First"),
          createElement("native-second", { key: "second" }, "Second"),
        ]);
      },
      assertOriginalContent: () => expect(host.textContent).toBe("FirstSecond"),
    },
    {
      name: "empty provider",
      renderResult: () => {
        const context = createContext<unknown>(null);
        return createElement(context.Provider, { value: {} });
      },
      assertOriginalContent: () => expect(host.textContent).toBe(""),
    },
  ];

  for (const testCase of cases) {
    const view = { setContext: vi.fn(), sync: vi.fn(), destroy: vi.fn(), clearShowTimeout: vi.fn() };
    const store = createLudusaviStateStore();
    store.applyRefreshResult({
      games: [{ name: "Fixture", steam_id: "100", configured: true, has_backup: false, needs_first_backup: true, error: null, status: "needs_first_backup" }],
      aliases: {}, history: {}, dependency_error: null,
    });
    const statusSurface = createAutoSyncStatusSurface(view, store);
    const gameDetailsSurface = createGameDetailsStatusSurface(store, statusSurface);
    const patch = routeMock.addPatch.mock.calls.at(-1)?.[1] as (route: any) => any;
    const child = createElement("native-route", { renderFunc: testCase.renderResult });
    const patched = patch({ path: "/library/app/:appid", children: child });
    const renderKnownPage = () => patched.children.props.renderFunc({ params: { appid: "100" } });

    try {
      await render(renderKnownPage());
      testCase.assertOriginalContent();
      statusSurface.publish("backing_up", {
        source: "lifecycle_exit", lifecycle: "lifecycle_exit", generation: 25,
        gameName: "Fixture", appID: "100", tracked: true,
      });
      const observation = store.getSnapshot().autoSyncObservations["100"];
      expect(observation, testCase.name).toBeDefined();
      expect(view.sync, testCase.name).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));

      await render(createElement("native-home"));
      expect(view.sync, testCase.name).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));
      expect(store.getSnapshot().autoSyncObservations["100"], testCase.name).toBe(observation);

      await render(renderKnownPage());
      testCase.assertOriginalContent();
      expect(view.sync, testCase.name).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
      expect(store.getSnapshot().autoSyncObservations["100"], testCase.name).toBe(observation);

      await render(createElement("native-home"));
      expect(view.sync, testCase.name).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }));
      expect(store.getSnapshot().autoSyncObservations["100"], testCase.name).toBe(observation);
    } finally {
      gameDetailsSurface.dispose();
      statusSurface.dispose();
      const routePatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
      if (routePatch?.removalTimer !== null && routePatch?.removalTimer !== undefined) clearTimeout(routePatch.removalTimer);
      Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRoutePatch");
      Reflect.deleteProperty(globalThis, "__sdhLudusaviGameDetailsStatusRegistry");
    }
  }
});
