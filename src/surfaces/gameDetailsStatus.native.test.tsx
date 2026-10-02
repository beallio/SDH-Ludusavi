import { act, cloneElement, createElement, useEffect, type ReactElement } from "react";
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
vi.mock("@decky/api", () => ({ routerHook: { addPatch: vi.fn(), removePatch: vi.fn() } }));
vi.mock("@decky/ui", () => ({ playSectionClasses: nativeClasses.play, basicAppDetailsSectionStylerClasses: nativeClasses.root }));
vi.mock("../utils/logging", () => ({ log: vi.fn() }));
vi.mock("../utils/steam", () => ({ sessionFromAppOverview: () => null }));
vi.mock("../utils/steamRuntime", () => ({ getAppDetailsForAppID: () => null, getAppOverviewForAppID: () => null, getGamepadMainWindow: () => null, subscribeToAppDetails: () => () => {} }));
import { composeInNativeStatusSlot, GameDetailsStatusRow, isVisibleStatusBand } from "./gameDetailsStatus";
import type { GameDetailsStatusViewModel } from "./gameDetailsStatusModel";

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

