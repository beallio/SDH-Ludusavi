import { routerHook, type RoutePatch } from "@decky/api";
import { cloneElement, createElement, isValidElement, useEffect, useState, useSyncExternalStore, type CSSProperties, type ReactElement, type ReactNode } from "react";

import type { LudusaviStateStore } from "../state/ludusaviState";
import { sessionFromAppOverview } from "../utils/steam";
import { getAppDetailsForAppID, getAppOverviewForAppID, subscribeToAppDetails } from "../utils/steamRuntime";
import { selectGameDetailsStatus, getSteamCloudEligibility, type GameDetailsStatusViewModel } from "./gameDetailsStatusModel";
import { iconSvgForAutoSyncStatus } from "./autoSyncStatusRenderer";
import type { DetailsStatusPresentationSurface } from "./autoSyncStatusSurface";

const GAME_DETAILS_ROUTE = "/library/app/:appid";
// Runtime disposal can follow the launch-lease cleanup ceiling. Retain only
// the inert route wrapper through that handoff so a replacement plugin can
// update an already-mounted details page without a navigation.
const GAME_DETAILS_ROUTE_REPLACEMENT_GRACE_MS = 2_500;
export type GameDetailsStatusSurface = Readonly<{
  dispose(): void;
}>;

export type GameDetailsStatusContribution = Readonly<{
  token: number;
  store: LudusaviStateStore;
  statusSurface: DetailsStatusPresentationSurface;
}>;

export type GameDetailsStatusContributionSource = Readonly<{
  getSnapshot(): GameDetailsStatusContribution | null;
  subscribe(listener: () => void): () => void;
}>;

type RouteRecord = Record<string, unknown>;
type GameDetailsStatusContributionRegistry = GameDetailsStatusContributionSource & Readonly<{
  activate(store: LudusaviStateStore, statusSurface: DetailsStatusPresentationSurface): number;
  retire(token: number): void;
}>;

type NativeHeader = (props: unknown) => ReactNode;
type NativeRouteRenderFunction = (...args: unknown[]) => unknown;
type NativeRouteChildProps = RouteRecord & { renderFunc: NativeRouteRenderFunction };
type NativeProviderProps = RouteRecord & { value: unknown };
type NativeHeaderElementProps = RouteRecord & { children?: unknown };
type ManagedGameDetailsRoutePatch = {
  patch: RoutePatch;
  installedPatch: RoutePatch;
  removalTimer: ReturnType<typeof globalThis.setTimeout> | null;
};
declare global {
  var __sdhLudusaviGameDetailsStatusRegistry: GameDetailsStatusContributionRegistry | undefined;
  var __sdhLudusaviGameDetailsStatusRoutePatch: ManagedGameDetailsRoutePatch | undefined;
}

function getGameDetailsStatusContributionRegistry(): GameDetailsStatusContributionRegistry {
  const existing = globalThis.__sdhLudusaviGameDetailsStatusRegistry;
  if (existing) return existing;
  let current: GameDetailsStatusContribution | null = null;
  let nextToken = 0;
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((listener) => listener());
  const registry: GameDetailsStatusContributionRegistry = Object.freeze({
    getSnapshot: () => current,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    activate(store: LudusaviStateStore, statusSurface: DetailsStatusPresentationSurface) {
      const token = ++nextToken;
      current = { token, store, statusSurface };
      notify();
      return token;
    },
    retire(token: number) {
      if (current?.token !== token) return;
      current = null;
      notify();
    },
  });
  globalThis.__sdhLudusaviGameDetailsStatusRegistry = registry;
  return registry;
}

export function createGameDetailsStatusSurface(
  store: LudusaviStateStore,
  statusSurface: DetailsStatusPresentationSurface,
): GameDetailsStatusSurface {
  const contributionRegistry = getGameDetailsStatusContributionRegistry();
  const contributionToken = contributionRegistry.activate(store, statusSurface);
  retainGameDetailsRoutePatch(contributionRegistry);
  let disposed = false;
  return Object.freeze({
    dispose() {
      if (disposed) return;
      disposed = true;
      contributionRegistry.retire(contributionToken);
      releaseGameDetailsRoutePatchWhenIdle(contributionRegistry);
    },
  });
}

function retainGameDetailsRoutePatch(contributionRegistry: GameDetailsStatusContributionRegistry): void {
  const retainedPatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
  if (retainedPatch) {
    if (retainedPatch.removalTimer !== null) {
      globalThis.clearTimeout(retainedPatch.removalTimer);
      retainedPatch.removalTimer = null;
    }
    return;
  }

  const wrappedHeaders = new WeakMap<NativeHeader, Map<string, NativeHeader>>();
  const patch: RoutePatch = (route) => {
    const record = asRecord(route);
    const child = asNativeRouteChild(record?.children);
    if (!record || !child) return route;
    const renderFunc = child.props.renderFunc;
    const wrappedRenderFunc = (...args: unknown[]) => {
      const rendered = renderFunc(...args);
      const provider = asNativeProviderElement(rendered);
      if (!provider) return rendered;
      const nativeHeader = asNativeHeader(provider.props.value);
      const appID = routeAppID(args) ?? routeAppID([record]);
      if (!nativeHeader || !appID) return rendered;
      let wrappersForHeader = wrappedHeaders.get(nativeHeader);
      if (!wrappersForHeader) {
        wrappersForHeader = new Map();
        wrappedHeaders.set(nativeHeader, wrappersForHeader);
      }
      let wrappedHeader = wrappersForHeader.get(appID);
      if (!wrappedHeader) {
        wrappedHeader = (headerProps: unknown) => {
          const contribution = contributionRegistry.getSnapshot();
          return createElement(GameDetailsStatusHeader, {
            appID,
            header: nativeHeader,
            headerProps,
            contributionSource: contributionRegistry,
            store: contribution?.store ?? null,
            statusSurface: contribution?.statusSurface ?? null,
          });
        };
        wrappersForHeader.set(appID, wrappedHeader);
      }
      return cloneElement(provider, { ...provider.props, value: wrappedHeader });
    };
    // Decky's dispatcher consumes the React child's props. Preserve every native
    // prop and replace only the route callback.
    return { ...route, children: cloneElement(child, { ...child.props, renderFunc: wrappedRenderFunc }) };
  };
  const installedPatch = routerHook.addPatch(GAME_DETAILS_ROUTE, patch);
  globalThis.__sdhLudusaviGameDetailsStatusRoutePatch = { patch, installedPatch, removalTimer: null };
}

function releaseGameDetailsRoutePatchWhenIdle(contributionRegistry: GameDetailsStatusContributionRegistry): void {
  const retainedPatch = globalThis.__sdhLudusaviGameDetailsStatusRoutePatch;
  if (!retainedPatch || contributionRegistry.getSnapshot() !== null || retainedPatch.removalTimer !== null) return;
  retainedPatch.removalTimer = globalThis.setTimeout(() => {
    if (globalThis.__sdhLudusaviGameDetailsStatusRoutePatch !== retainedPatch
      || contributionRegistry.getSnapshot() !== null) return;
    routerHook.removePatch(GAME_DETAILS_ROUTE, retainedPatch.installedPatch);
    globalThis.__sdhLudusaviGameDetailsStatusRoutePatch = undefined;
  }, GAME_DETAILS_ROUTE_REPLACEMENT_GRACE_MS);
}

type GameDetailsStatusHeaderProps = Readonly<{
  appID: string;
  header: NativeHeader;
  headerProps: unknown;
  contributionSource: GameDetailsStatusContributionSource;
  store: LudusaviStateStore | null;
  statusSurface: DetailsStatusPresentationSurface | null;
}>;

function GameDetailsStatusHeader({
  appID,
  header,
  headerProps,
  contributionSource,
  store,
  statusSurface,
}: GameDetailsStatusHeaderProps): ReactNode {
  const fallbackContribution = store && statusSurface
    ? { token: 0, store, statusSurface }
    : null;
  const contribution = useSyncExternalStore(
    contributionSource.subscribe,
    contributionSource.getSnapshot,
    () => fallbackContribution,
  );
  const nativeHeader = header(headerProps);
  if (!contribution) return nativeHeader;
  return createElement(ActiveGameDetailsStatusHeader, {
    appID,
    header,
    headerProps,
    store: contribution.store,
    statusSurface: contribution.statusSurface,
  });
}

type ActiveGameDetailsStatusHeaderProps = Pick<
  GameDetailsStatusHeaderProps,
  "appID" | "header" | "headerProps"
> & Readonly<{
  store: LudusaviStateStore;
  statusSurface: DetailsStatusPresentationSurface;
}>;

function ActiveGameDetailsStatusHeader({ appID, header, headerProps, store, statusSurface }: ActiveGameDetailsStatusHeaderProps): ReactNode {
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
  if (!model.showRow) return nativeHeader;
  return composeInNativeStatusSlot(nativeHeader, createElement(GameDetailsStatusRow, {
    appID,
    model,
    statusSurface,
    suppressed: rowYields,
  }));
}

// The AppDetails header exposes the deferred Cloud component as child one. It
// can render null for an eligible shortcut, but it must remain mounted so Steam
// retains ownership whenever it renders a real native status band.
export function composeInNativeStatusSlot(nativeHeader: ReactNode, row: ReactElement): ReactNode {
  const header = asNativeHeaderElement(nativeHeader);
  if (!header) return nativeHeader;
  const children = header.props.children;
  if (!Array.isArray(children) || children.length < 4) return nativeHeader;
  const nativeStatus = children[1];
  if (!isValidElement(nativeStatus)) return nativeHeader;
  const nextChildren: unknown[] = [...children];
  nextChildren[1] = createElement(NativeStatusSlot, { nativeStatus, row });
  return cloneElement(header, { ...header.props, children: nextChildren });
}

type NativeStatusSlotProps = Readonly<{ nativeStatus: ReactElement; row: ReactElement }>;

function NativeStatusSlot({ nativeStatus, row }: NativeStatusSlotProps): ReactNode {
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
    const HostMutationObserver = getStatusHostWindow(slot)?.MutationObserver;
    const observer = HostMutationObserver ? new HostMutationObserver(update) : null;
    observer?.observe(slot, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "hidden"] });
    return () => observer?.disconnect();
  }, [slot, nativeStatus]);
  return createElement("div", { ref: setSlot, style: { display: "contents" } },
    nativeStatus,
    createElement("div", { "data-sdh-ludusavi-fallback": "true", style: { display: nativeVisible ? "none" : "contents" } }, row),
  );
}

type GameDetailsStatusRowProps = Readonly<{
  appID: string;
  model: GameDetailsStatusViewModel;
  statusSurface: DetailsStatusPresentationSurface;
  suppressed: boolean;
}>;

export function detailsRowPaintStyle(suppressed: boolean): Pick<CSSProperties, "opacity" | "pointerEvents"> {
  // The hidden row must still receive the host document's hit test. That is
  // how it detects that a previously clipped native band became usable and
  // can replace the fallback strip. It has no handlers or focus stop, and is
  // aria-hidden while suppressed, so retaining pointer participation exposes
  // no interactive surface.
  return suppressed ? { opacity: 0 } : {};
}


const DETAILS_ROW_BASE_STYLE: CSSProperties = {
  width: "100%",
  height: 30,
  minHeight: 30,
  boxSizing: "border-box",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "4px 0",
  textAlign: "center",
  overflow: "hidden",
  whiteSpace: "nowrap",
};
const DETAILS_ROW_STYLE: CSSProperties = { ...DETAILS_ROW_BASE_STYLE, background: "transparent" };
const DETAILS_ROW_PROBLEM_STYLE: CSSProperties = {
  ...DETAILS_ROW_BASE_STYLE,
  background: "rgba(255, 255, 255, 0.16)",
};
const DETAILS_DIVIDER_STYLE: CSSProperties = {
  flex: "1 1 0",
  minWidth: 0,
  height: 2,
  marginInline: 12,
  backgroundColor: "rgba(61, 68, 80, 0.54)",
};
const DETAILS_CONTENT_STYLE: CSSProperties = {
  minWidth: 0,
  flex: "0 1 auto",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};
const DETAILS_ICON_STYLE: CSSProperties = {
  width: 16,
  height: 16,
  flex: "0 0 16px",
  marginInline: 8,
  color: "#dcdedf",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};
const DETAILS_ACTIVE_ICON_STYLE: CSSProperties = {
  ...DETAILS_ICON_STYLE,
  animation: "sdh-ludusavi-status-pulse 1.5s infinite",
};
const DETAILS_LABEL_STYLE: CSSProperties = {
  minWidth: 0,
  overflow: "hidden",
  textOverflow: "ellipsis",
  fontFamily: "\"Motiva Sans\", Helvetica, sans-serif",
  fontSize: 12,
  fontWeight: 700,
  lineHeight: "22px",
  letterSpacing: "0.5px",
  textTransform: "uppercase",
  color: "rgba(255, 255, 255, 0.7)",
};
const DETAILS_VALUE_STYLE: CSSProperties = { color: "rgba(255, 255, 255, 0.7)" };
const DETAILS_ACTIVE_VALUE_STYLE: CSSProperties = { color: "#1a9fff" };


function GameDetailsStatusRow({ appID, model, statusSurface, suppressed }: GameDetailsStatusRowProps): ReactNode {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const visible = useVisibleLayout(element);
  useEffect(() => {
    if (!model.canOwnStatusArea || !visible) return;
    return statusSurface.registerDetailsOwner({ appID, visible: true, layoutValid: true });
  }, [appID, model.canOwnStatusArea, statusSurface, visible]);
  const status = model.status ?? "unknown";
  const value = model.label.startsWith("Ludusavi: ") ? model.label.slice("Ludusavi: ".length) : model.label;
  const problem = model.tone === "warning" || model.tone === "error";
  const rowStyle = problem ? DETAILS_ROW_PROBLEM_STYLE : DETAILS_ROW_STYLE;
  const dividerStyle = problem ? null : DETAILS_DIVIDER_STYLE;
  const iconStyle = model.active ? DETAILS_ACTIVE_ICON_STYLE : DETAILS_ICON_STYLE;
  const valueStyle = model.active && !problem ? DETAILS_ACTIVE_VALUE_STYLE : DETAILS_VALUE_STYLE;
  const divider = dividerStyle
    ? createElement("span", { "aria-hidden": true, style: dividerStyle })
    : null;
  return createElement("div", { style: { display: "contents" } },
    createElement("style", null,
      "@keyframes sdh-ludusavi-status-pulse { 0%, 100% { color: #dcdedf; } 50% { color: #3d4450; } } "
      + "[data-sdh-ludusavi-status-icon=\"true\"] svg { display: block; width: 16px; height: 16px; }",
    ),
    createElement("div", {
      ref: setElement,
      role: suppressed ? undefined : "status",
      "aria-hidden": suppressed || undefined,
      "aria-label": suppressed ? undefined : `${model.label}. ${model.description}`,
      "data-sdh-ludusavi-status-row": "true",
      style: { ...rowStyle, ...detailsRowPaintStyle(suppressed) },
    },
    divider,
    createElement("span", { style: DETAILS_CONTENT_STYLE },
      createElement("span", {
        "aria-hidden": true,
        "data-sdh-ludusavi-status-icon": "true",
        style: iconStyle,
        dangerouslySetInnerHTML: { __html: iconSvgForAutoSyncStatus(status) },
      }),
      createElement("span", { style: DETAILS_LABEL_STYLE },
        "Ludusavi: ",
        createElement("span", { style: valueStyle }, value),
      ),
    ),
    dividerStyle ? createElement("span", { "aria-hidden": true, style: dividerStyle }) : null,
    ),
  );
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

type StatusHostWindow = Window & {
  IntersectionObserver?: typeof IntersectionObserver;
  ResizeObserver?: typeof ResizeObserver;
  MutationObserver?: typeof MutationObserver;
};

function getStatusHostWindow(element: Element): StatusHostWindow | null {
  return element.ownerDocument?.defaultView ?? null;
}

function useVisibleLayout(element: HTMLDivElement | null): boolean {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!element) return;
    const hostWindow = getStatusHostWindow(element);
    if (!hostWindow) return;
    const HostIntersectionObserver = hostWindow.IntersectionObserver;
    let fullyIntersecting = HostIntersectionObserver === undefined;
    const update = () => setVisible(isVisibleStatusBand(element, fullyIntersecting));
    const observer = HostIntersectionObserver ? new HostIntersectionObserver((entries) => {
      const entry = entries.find((candidate) => candidate.target === element);
      fullyIntersecting = isFullyIntersecting(entry);
      update();
    }, { threshold: DETAILS_STATUS_VISIBILITY_THRESHOLDS }) : null;
    observer?.observe(element);
    const HostResizeObserver = hostWindow.ResizeObserver;
    const resizeObserver = HostResizeObserver ? new HostResizeObserver(update) : null;
    resizeObserver?.observe(element);
    const HostMutationObserver = hostWindow.MutationObserver;
    const mutationObserver = HostMutationObserver ? new HostMutationObserver(update) : null;
    for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
      mutationObserver?.observe(ancestor, { attributes: true, attributeFilter: ["class", "style", "hidden"] });
    }
    hostWindow.addEventListener("resize", update);
    hostWindow.addEventListener("scroll", update, true);
    update();
    return () => {
      observer?.disconnect(); resizeObserver?.disconnect(); mutationObserver?.disconnect();
      hostWindow.removeEventListener("resize", update); hostWindow.removeEventListener("scroll", update, true);
    };
  }, [element]);
  return visible;
}

export function isVisibleStatusBand(element: HTMLDivElement, intersecting: boolean): boolean {
  if (!intersecting) return false;
  const ownerDocument = element.ownerDocument;
  const hostDocument = ownerDocument ?? document;
  const hostWindow = ownerDocument?.defaultView ?? (ownerDocument ? null : window);
  if (!hostWindow) return false;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height < 20) return false;
  for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
    if (ancestor.hidden) return false;
    const style = hostWindow.getComputedStyle?.(ancestor);
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
  const root = hostDocument.documentElement;
  if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= root.clientHeight || rect.left >= root.clientWidth) return false;
  if (typeof hostDocument.elementFromPoint === "function") {
    const top = hostDocument.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (top && !element.contains(top)) return false;
  }
  return true;
}
function clipsOverflow(value: string | undefined): boolean {
  return ["hidden", "clip", "auto", "scroll"].includes(value ?? "visible");
}

function routeAppID(values: readonly unknown[]): string | null {
  for (const value of values) {
    const record = asRecord(value); const params = asRecord(record?.params); const candidate = params?.appid ?? record?.appid;
    if (typeof candidate === "string" || typeof candidate === "number") return String(candidate);
  }
  return null;
}
function asRecord(value: unknown): RouteRecord | null { return typeof value === "object" && value !== null ? value as RouteRecord : null; }

function asNativeRouteChild(value: unknown): ReactElement<NativeRouteChildProps> | null {
  if (!isValidElement(value)) return null;
  const props = asRecord(value.props);
  if (!props || typeof props.renderFunc !== "function") return null;
  return value as ReactElement<NativeRouteChildProps>;
}

function asNativeProviderElement(value: unknown): ReactElement<NativeProviderProps> | null {
  if (!isValidElement(value)) return null;
  const props = asRecord(value.props);
  if (!props || !("value" in props)) return null;
  return value as ReactElement<NativeProviderProps>;
}

function asNativeHeader(value: unknown): NativeHeader | null {
  return typeof value === "function" ? value as NativeHeader : null;
}

function asNativeHeaderElement(value: unknown): ReactElement<NativeHeaderElementProps> | null {
  if (!isValidElement(value)) return null;
  const props = asRecord(value.props);
  if (!props) return null;
  return value as ReactElement<NativeHeaderElementProps>;
}
