import { routerHook } from "@decky/api";
import { cloneElement, createElement, isValidElement, useEffect, useState, useSyncExternalStore, type ReactElement } from "react";

import type { LudusaviStateStore } from "../state/ludusaviState";
import { sessionFromAppOverview } from "../utils/steam";
import { getAppDetailsForAppID, getAppOverviewForAppID, subscribeToAppDetails } from "../utils/steamRuntime";
import { selectGameDetailsStatus, getSteamCloudEligibility } from "./gameDetailsStatusModel";
import { iconSvgForAutoSyncStatus } from "./autoSyncStatusRenderer";
import type { createAutoSyncStatusSurface } from "./autoSyncStatusSurface";

const GAME_DETAILS_ROUTE = "/library/app/:appid";
type DetailsStatusSurface = Pick<ReturnType<typeof createAutoSyncStatusSurface>, "registerDetailsOwner" | "subscribeDetailsPresentation" | "shouldDetailsRowYield">;
type RouteRecord = Record<string, unknown>;
type NativeHeader = (props: unknown) => unknown;

export function createGameDetailsStatusSurface(store: LudusaviStateStore, statusSurface: DetailsStatusSurface) {
  let disposed = false;
  const wrappedHeaders = new WeakMap<NativeHeader, Map<string, NativeHeader>>();
  const patch = (route: unknown) => {
    const record = asRecord(route);
    const child = record?.children;
    if (!record || !isValidElement(child)) return route as any;
    const childProps = asRecord(child.props);
    const renderFunc = childProps?.renderFunc;
    if (typeof renderFunc !== "function") return route as any;
    const wrappedRenderFunc = (...args: unknown[]) => {
      const rendered = renderFunc(...args);
      if (!isValidElement(rendered) || disposed) return rendered;
      const providerProps = asRecord(rendered.props);
      const header = providerProps?.value;
      const appID = routeAppID(args) ?? routeAppID([record]);
      if (typeof header !== "function" || !appID) return rendered;
      const nativeHeader = header as NativeHeader;
      let wrappersForHeader = wrappedHeaders.get(nativeHeader);
      if (!wrappersForHeader) {
        wrappersForHeader = new Map();
        wrappedHeaders.set(nativeHeader, wrappersForHeader);
      }
      let wrappedHeader = wrappersForHeader.get(appID);
      if (!wrappedHeader) {
        wrappedHeader = (headerProps: unknown) => createElement(
          GameDetailsStatusHeader,
          { appID, header: nativeHeader, headerProps, store, statusSurface },
        );
        wrappersForHeader.set(appID, wrappedHeader);
      }
      return cloneElement(rendered as ReactElement<any>, { ...providerProps, value: wrappedHeader } as any);
    };
    // Decky's dispatcher consumes the React child's props. Preserve every native
    // prop and replace only the route callback.
    return { ...record, children: cloneElement(child as ReactElement<any>, { ...childProps, renderFunc: wrappedRenderFunc } as any) };
  };
  const installedPatch = routerHook.addPatch(GAME_DETAILS_ROUTE, patch as any);
  return { dispose() {
    if (disposed) return;
    disposed = true;
    routerHook.removePatch(GAME_DETAILS_ROUTE, installedPatch);
  } };
}

function GameDetailsStatusHeader({ appID, header, headerProps, store, statusSurface }: {
  appID: string; header: NativeHeader; headerProps: unknown; store: LudusaviStateStore; statusSurface: DetailsStatusSurface;
}) {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [details, setDetails] = useState<unknown>(() => getAppDetailsForAppID(appID));
  const rowYields = useSyncExternalStore(
    statusSurface.subscribeDetailsPresentation,
    () => statusSurface.shouldDetailsRowYield(appID),
    () => statusSurface.shouldDetailsRowYield(appID),
  );
  useEffect(() => {
    const refreshDetails = () => setDetails(getAppDetailsForAppID(appID));
    refreshDetails();
    return subscribeToAppDetails(appID, refreshDetails);
  }, [appID]);
  const overview = getAppOverviewForAppID(appID);
  const gameName = sessionFromAppOverview(overview)?.name ?? "";
  const eligibility = getSteamCloudEligibility(appID, details);
  const model = selectGameDetailsStatus({ snapshot, appID, gameName, canonicalGameName: gameName ? store.resolveCanonicalGameName(gameName, appID) : null, eligibility });
  const nativeHeader = header(headerProps);
  if (!model.showRow || rowYields) return nativeHeader as any;
  return composeInNativeStatusSlot(nativeHeader, createElement(GameDetailsStatusRow, { appID, model, statusSurface })) as any;
}

// The AppDetails header exposes the deferred Cloud component as child one. It
// can render null for an eligible shortcut, but it must remain mounted so Steam
// retains ownership whenever it renders a real native status band.
export function composeInNativeStatusSlot(nativeHeader: unknown, row: ReactElement): unknown {
  if (!isValidElement(nativeHeader)) return nativeHeader;
  const props = asRecord(nativeHeader.props);
  const children = props?.children;
  if (!Array.isArray(children) || children.length < 4) return nativeHeader;
  const nativeStatus = children[1];
  if (!isValidElement(nativeStatus)) return nativeHeader;
  const nextChildren = [...children];
  nextChildren[1] = createElement(NativeStatusSlot, { nativeStatus, row });
  return cloneElement(nativeHeader as ReactElement<any>, { ...props, children: nextChildren } as any);
}

function NativeStatusSlot({ nativeStatus, row }: { nativeStatus: ReactElement; row: ReactElement }) {
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const [nativeVisible, setNativeVisible] = useState(true);
  useEffect(() => {
    if (!slot) return;
    const update = () => {
      const occupied = Array.from(slot.children).some((child) =>
        child.getAttribute("data-sdh-ludusavi-fallback") !== "true" && child.getClientRects().length > 0,
      );
      setNativeVisible(occupied);
    };
    update();
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(update);
    observer?.observe(slot, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "hidden"] });
    return () => observer?.disconnect();
  }, [slot, nativeStatus]);
  return createElement("div", { ref: setSlot, style: { display: "contents" } },
    nativeStatus,
    createElement("div", { "data-sdh-ludusavi-fallback": "true", style: { display: nativeVisible ? "none" : "contents" } }, row),
  );
}

function GameDetailsStatusRow({ appID, model, statusSurface }: {
  appID: string; model: ReturnType<typeof selectGameDetailsStatus>; statusSurface: DetailsStatusSurface;
}) {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const visible = useVisibleLayout(element);
  useEffect(() => {
    if (!model.canOwnStatusArea || !visible) return;
    return statusSurface.registerDetailsOwner({ appID, visible: true, layoutValid: true });
  }, [appID, model.canOwnStatusArea, statusSurface, visible]);
  const status = model.status ?? "unknown";
  return createElement("div", { style: { display: "contents" } },
    createElement("style", null, "@keyframes sdh-ludusavi-status-spin { to { transform: rotate(360deg); } }"),
    createElement("div", {
      ref: setElement, role: "status", "aria-label": model.description,
      style: { width: "100%", minHeight: 30, boxSizing: "border-box", display: "flex", alignItems: "center", gap: 8, padding: "4px 12px", color: toneColor(model.tone), background: "rgba(0, 0, 0, 0.18)", fontFamily: "Motiva Sans, Arial, sans-serif", fontSize: 13, fontWeight: 700, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" },
    }, createElement("span", {
      "aria-hidden": true,
      style: { width: 18, height: 18, flex: "0 0 18px", display: "inline-flex", alignItems: "center", justifyContent: "center", animation: model.active ? "sdh-ludusavi-status-spin 1s linear infinite" : undefined },
      dangerouslySetInnerHTML: { __html: iconSvgForAutoSyncStatus(status) },
    }), createElement("span", { style: { overflow: "hidden", textOverflow: "ellipsis" } }, model.label)));
}

export const DETAILS_STATUS_VISIBILITY_THRESHOLDS = [0, 0.99, 1];

type StatusIntersection = Pick<IntersectionObserverEntry, "isIntersecting" | "intersectionRatio"> & {
  intersectionRect: Pick<DOMRectReadOnly, "width" | "height">;
  boundingClientRect: Pick<DOMRectReadOnly, "width" | "height">;
};

export function isFullyIntersecting(entry: StatusIntersection | undefined): boolean {
  return Boolean(entry && entry.isIntersecting && entry.intersectionRatio >= 0.99
    && entry.intersectionRect.width >= entry.boundingClientRect.width - 1
    && entry.intersectionRect.height >= entry.boundingClientRect.height - 1);
}

function useVisibleLayout(element: HTMLDivElement | null): boolean {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!element) return;
    let fullyIntersecting = typeof IntersectionObserver === "undefined";
    const update = () => setVisible(isVisibleStatusBand(element, fullyIntersecting));
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((entries) => {
      const entry = entries.find((candidate) => candidate.target === element);
      fullyIntersecting = isFullyIntersecting(entry);
      update();
    }, { threshold: DETAILS_STATUS_VISIBILITY_THRESHOLDS });
    observer?.observe(element);
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    resizeObserver?.observe(element);
    const mutationObserver = typeof MutationObserver === "undefined" ? null : new MutationObserver(update);
    for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
      mutationObserver?.observe(ancestor, { attributes: true, attributeFilter: ["class", "style", "hidden"] });
    }
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    update();
    return () => {
      observer?.disconnect(); resizeObserver?.disconnect(); mutationObserver?.disconnect();
      window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true);
    };
  }, [element]);
  return visible;
}

export function isVisibleStatusBand(element: HTMLDivElement, intersecting: boolean): boolean {
  if (!intersecting) return false;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height < 20) return false;
  for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
    if (ancestor.hidden) return false;
    const style = window.getComputedStyle?.(ancestor);
    if (style?.display === "none" || style?.visibility === "hidden" || style?.visibility === "collapse") return false;
    if (ancestor !== element && typeof ancestor.getBoundingClientRect === "function") {
      const bounds = ancestor.getBoundingClientRect();
      const clipsX = clipsOverflow(style?.overflowX ?? style?.overflow);
      const clipsY = clipsOverflow(style?.overflowY ?? style?.overflow);
      const hasLayoutBox = bounds.width > 0 && bounds.height > 0;
      if (hasLayoutBox && ((clipsX && (rect.left < bounds.left || rect.right > bounds.right))
        || (clipsY && (rect.top < bounds.top || rect.bottom > bounds.bottom)))) return false;
    }
  }
  const root = document.documentElement;
  if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= root.clientHeight || rect.left >= root.clientWidth) return false;
  if (typeof document.elementFromPoint === "function") {
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (top && !element.contains(top)) return false;

  }
  return true;
}
function clipsOverflow(value: string | undefined): boolean {
  return ["hidden", "clip", "auto", "scroll"].includes(value ?? "visible");
}

function toneColor(tone: ReturnType<typeof selectGameDetailsStatus>["tone"]) {
  if (tone === "error") return "#ef4444";
  if (tone === "warning") return "#f59e0b";
  if (tone === "success") return "#1a9fff";
  return "#d6e6f5";
}
function routeAppID(values: unknown[]): string | null {
  for (const value of values) {
    const record = asRecord(value); const params = asRecord(record?.params); const candidate = params?.appid ?? record?.appid;
    if (typeof candidate === "string" || typeof candidate === "number") return String(candidate);
  }
  return null;
}
function asRecord(value: unknown): RouteRecord | null { return typeof value === "object" && value !== null ? value as RouteRecord : null; }
