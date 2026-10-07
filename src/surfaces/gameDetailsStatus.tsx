import { routerHook, type RoutePatch } from "@decky/api";
import { Fragment, cloneElement, createElement, isValidElement, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactElement, type ReactNode } from "react";

import type { LudusaviStateStore } from "../state/ludusaviState";
import { sessionFromAppOverview } from "../utils/steam";
import { getAppDetailsForAppID, getAppOverviewForAppID, getGamepadMainWindow, subscribeToAppDetails } from "../utils/steamRuntime";
import { selectGameDetailsStatus, getSteamCloudEligibility, type GameDetailsStatusViewModel } from "./gameDetailsStatusModel";
import { isStatusPaintMeasurement, measureStatusBandPaint, mountGameDetailsArtworkBackdrop } from "./gameDetailsArtworkBackdrop";
import { nativeIconSvgForAutoSyncStatus } from "./nativeGameDetailsStatusIcon";
import type { DetailsStatusPresentationSurface } from "./autoSyncStatusSurface";
import { getNativeGameDetailsStatusClasses, type NativeGameDetailsStatusClasses } from "./gameDetailsStatusClasses";

const GAME_DETAILS_ROUTE = "/library/app/:appid";
// Runtime disposal can follow the launch-lease cleanup ceiling. Retain only
// the inert route wrapper through that handoff so a replacement plugin can
// update an already-mounted details page without a navigation.
const GAME_DETAILS_ROUTE_REPLACEMENT_GRACE_MS = 2_500;
// Bump when an existing route wrapper cannot render the newest status-row contract.
const GAME_DETAILS_ROUTE_RENDER_VERSION = 22;
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
  version?: number;
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
    if (retainedPatch.version === GAME_DETAILS_ROUTE_RENDER_VERSION) return;
    // An older wrapper closes over older row JSX. Keep the shared contribution
    // registry, but replace only our patch so subsequent native route renders
    // use the current row without removing other plugins' route patches.
    routerHook.removePatch(GAME_DETAILS_ROUTE, retainedPatch.installedPatch);
    globalThis.__sdhLudusaviGameDetailsStatusRoutePatch = undefined;
  }

  const wrappedHeaders = new WeakMap<NativeHeader, Map<string, NativeHeader>>();
  const patch: RoutePatch = (route) => {
    const record = asRecord(route);
    const child = asNativeRouteChild(record?.children);
    if (!record || !child) return route;
    const renderFunc = child.props.renderFunc;
    const wrappedRenderFunc = (...args: unknown[]) => {
      const rendered = renderFunc(...args);
      const appID = routeAppID(args) ?? routeAppID([record]);
      if (!appID) return rendered;
      const withDetailsPagePresence = wrapRouteResultWithDetailsPagePresence(
        rendered,
        appID,
        contributionRegistry,
      );
      const provider = asNativeProviderElement(withDetailsPagePresence);
      if (!provider) return withDetailsPagePresence;
      const nativeHeader = asNativeHeader(provider.props.value);
      if (!nativeHeader) return provider;
      let wrappersForHeader = wrappedHeaders.get(nativeHeader);
      if (!wrappersForHeader) {
        wrappersForHeader = new Map();
        wrappedHeaders.set(nativeHeader, wrappersForHeader);
      }
      let wrappedHeader = wrappersForHeader.get(appID);
      if (!wrappedHeader) {
        wrappedHeader = (headerProps: unknown) => {
          const contribution = contributionRegistry.getSnapshot();
          // Keep the native Provider and its direct route child intact for
          // downstream route patches. The independently mounted child
          // boundary reports page presence even when this header is absent.
          return createElement(Fragment, null,
            createElement(GameDetailsStatusHeader, {
              appID,
              header: nativeHeader,
              headerProps,
              contributionSource: contributionRegistry,
              store: contribution?.store ?? null,
              statusSurface: contribution?.statusSurface ?? null,
            }),
          );
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
  globalThis.__sdhLudusaviGameDetailsStatusRoutePatch = {
    version: GAME_DETAILS_ROUTE_RENDER_VERSION,
    patch,
    installedPatch,
    removalTimer: null,
  };
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

function DetailsPagePresence({ appID, contributionSource }: Pick<GameDetailsStatusHeaderProps, "appID" | "contributionSource">): null {
  const contribution = useSyncExternalStore(
    contributionSource.subscribe,
    contributionSource.getSnapshot,
    contributionSource.getSnapshot,
  );
  useLayoutEffect(() => contribution?.statusSurface.registerDetailsPage(appID), [appID, contribution?.statusSurface]);
  return null;
}

type DetailsPageRouteChildProps = RouteRecord & Readonly<{
  appID: string;
  contributionSource: GameDetailsStatusContributionSource;
  routeChild: ReactElement<RouteRecord>;
}>;

// This boundary is the mounted route lifecycle owner. It forwards the native
// route child's real props to the real child, while its outer element keeps
// those props directly available to peer route patches.
function DetailsPageRouteChild({
  appID,
  contributionSource,
  routeChild,
  ...routeChildProps
}: DetailsPageRouteChildProps): ReactNode {
  return createElement(Fragment, null,
    createElement(DetailsPagePresence, { appID, contributionSource }),
    cloneElement(routeChild, routeChildProps),
  );
}

function wrapRouteResultWithDetailsPagePresence(
  rendered: unknown,
  appID: string,
  contributionSource: GameDetailsStatusContributionSource,
): unknown {
  const routeResult = asRouteResultElement(rendered);
  if (!routeResult) return rendered;
  const routeChild = asRouteResultElement(routeResult.props.children);
  const routeChildProps = routeChild && asRecord(routeChild.props);
  if (routeChild && routeChildProps) {
    const pageBoundary = createElement(DetailsPageRouteChild, {
      ...routeChildProps,
      appID,
      contributionSource,
      routeChild,
      key: routeChild.key,
    });
    return cloneElement(routeResult, { ...routeResult.props, children: pageBoundary });
  }
  const routeChildren = routeResult.props.children;
  if (!isRenderableRouteChildren(routeChildren)) return rendered;
  // Loading, empty, and multi-child route roots have no direct element whose
  // props peers can consume. Keep those native children in order and append
  // only the lifecycle owner so page presence stays independent of row/header.
  return cloneElement(
    routeResult,
    { ...routeResult.props },
    routeChildren,
    createElement(DetailsPagePresence, {
      appID,
      contributionSource,
      key: "sdh-ludusavi-details-page-presence",
    }),
  );
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
  useLayoutEffect(() => {
    const hostWindow = getGamepadMainWindow();
    if (!hostWindow) return;
    return mountGameDetailsArtworkBackdrop(hostWindow, appID);
  }, [appID]);
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
  const classes = getNativeGameDetailsStatusClasses();
  if (!header || !classes) return nativeHeader;
  const children = header.props.children;
  if (!Array.isArray(children) || children.length < 4) return nativeHeader;
  const nativeStatus = children[1];
  if (!isValidElement(nativeStatus)) return nativeHeader;
  const nextChildren: unknown[] = [...children];
  nextChildren[1] = createElement(NativeStatusSlot, { key: nativeStatus.key, nativeStatus, row: row as ReactElement<GameDetailsStatusRowProps>, classes });
  return cloneElement(header, { ...header.props, children: nextChildren });
}

type NativeStatusSlotProps = Readonly<{
  nativeStatus: ReactElement;
  row: ReactElement<GameDetailsStatusRowProps>;
  classes: NativeGameDetailsStatusClasses;
}>;

function NativeStatusSlot({ nativeStatus, row, classes }: NativeStatusSlotProps): ReactNode {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [nativeOccupied, setNativeOccupied] = useState(true);
  useLayoutEffect(() => {
    const parent = element?.parentElement;
    if (!element || !parent) return;
    const update = () => {
      let occupied = false;
      for (let sibling = element.previousElementSibling; sibling; sibling = sibling.previousElementSibling) {
        if (sibling.classList.contains(classes.playSection)) break;
        if (sibling.classList.contains(classes.row) || sibling.getClientRects().length > 0) {
          occupied = true;
          break;
        }
      }
      setNativeOccupied(occupied);
    };
    update();
    const HostMutationObserver = getStatusHostWindow(element)?.MutationObserver;
    const observer = HostMutationObserver ? new HostMutationObserver((records) => {
      if (records.some((record) => !isStatusPaintMeasurement(record))) update();
    }) : null;
    observer?.observe(parent, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "hidden"] });
    return () => observer?.disconnect();
  }, [element, classes]);
  return createElement(Fragment, null,
    nativeStatus,
    cloneElement(row, { classes, nativeOccupied, onElement: setElement }),
  );
}

type GameDetailsStatusRowProps = Readonly<{
  appID: string;
  model: GameDetailsStatusViewModel;
  statusSurface: DetailsStatusPresentationSurface;
  suppressed: boolean;
  classes?: NativeGameDetailsStatusClasses;
  nativeOccupied?: boolean;
  onElement?: (element: HTMLDivElement | null) => void;
}>;

export function detailsRowPaintStyle(suppressed: boolean): Pick<CSSProperties, "opacity"> {
  return suppressed ? { opacity: 0 } : {};
}


export function GameDetailsStatusRow({ appID, model, statusSurface, suppressed, classes: providedClasses, nativeOccupied = false, onElement }: GameDetailsStatusRowProps): ReactNode {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const visible = useVisibleLayout(element, model.label);
  const classes = providedClasses ?? getNativeGameDetailsStatusClasses();
  useLayoutEffect(() => {
    if (!model.canOwnStatusArea || !visible || nativeOccupied) return;
    return statusSurface.registerDetailsOwner({ appID, visible: true, layoutValid: true });
  }, [appID, model.canOwnStatusArea, statusSurface, visible, nativeOccupied]);
  useLayoutEffect(() => {
    onElement?.(element);
    return () => onElement?.(null);
  }, [element, onElement]);
  if (!classes) return null;
  const status = model.status ?? "unknown";
  const value = model.label.startsWith("Ludusavi: ") ? model.label.slice("Ludusavi: ".length) : model.label;
  const problem = model.tone === "warning" || model.tone === "error";
  const svg = nativeIconSvgForAutoSyncStatus(status, classes.iconSvg);
  return createElement("div", {
    ref: setElement,
    className: `${classes.row} Panel${problem ? ` ${classes.problem}` : ""}`,
    role: suppressed || nativeOccupied ? undefined : "status",
    "aria-hidden": suppressed || nativeOccupied || undefined,
    "aria-label": suppressed || nativeOccupied ? undefined : `${model.label}. ${model.description}`,
    "data-sdh-ludusavi-status-row": "true",
    "data-sdh-ludusavi-status-appid": appID,
    "data-sdh-ludusavi-tone": model.tone,
    "data-sdh-ludusavi-active": String(model.active),
    "data-sdh-ludusavi-paint-suppressed": String(suppressed),
    style: nativeOccupied ? { display: "none" } : detailsRowPaintStyle(suppressed),
  },
  createElement("span", {
    "aria-hidden": true,
    className: `${classes.icon}${model.active ? ` ${classes.syncing}` : ""}`,
    "data-sdh-ludusavi-status-icon": "true",
    dangerouslySetInnerHTML: { __html: svg },
  }),
  createElement("span", { className: classes.label, "data-sdh-ludusavi-status-label": "true" },
    "Ludusavi: ",
    createElement("span", { className: model.active && !problem ? classes.activeValue : undefined }, value),
  ));
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

function useVisibleLayout(element: HTMLDivElement | null, label: string): boolean {
  const [visible, setVisible] = useState(false);
  const scheduleVisibilityCheck = useRef<(() => void) | null>(null);
  useLayoutEffect(() => {
    if (!element) return;
    const hostWindow = getStatusHostWindow(element);
    if (!hostWindow) return;
    let frame: number | null = null;
    let fullyIntersecting = hostWindow.IntersectionObserver === undefined;
    const watchStyles = () => {
      mutationObserver?.observe(element, {
        attributes: true,
        attributeFilter: ["class", "style", "hidden"],
        childList: true,
        characterData: true,
        subtree: true,
      });
      for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
        mutationObserver?.observe(ancestor, { attributes: true, attributeFilter: ["class", "style", "hidden"] });
      }
      if (element.ownerDocument.head) mutationObserver?.observe(element.ownerDocument.head, { childList: true, characterData: true, subtree: true, attributes: true });
    };
    const update = () => {
      frame = null;
      // Measuring our own paint-suppressed row briefly removes its inline opacity.
      // Ignore those synchronous measurement writes in the existing observer.
      const nextVisible = isVisibleStatusBand(element, fullyIntersecting)
        && isStatusLabelFullyVisible(element);
      setVisible(nextVisible);
    };
    const schedule = () => {
      if (frame !== null) return;
      frame = hostWindow.requestAnimationFrame(update);
    };
    scheduleVisibilityCheck.current = schedule;
    const HostMutationObserver = hostWindow.MutationObserver;
    const mutationObserver = HostMutationObserver ? new HostMutationObserver((records) => {
      if (records.some((record) => !isStatusPaintMeasurement(record))) schedule();
    }) : null;
    const HostIntersectionObserver = hostWindow.IntersectionObserver;
    const observer = HostIntersectionObserver ? new HostIntersectionObserver((entries) => {
      const entry = entries.find((candidate) => candidate.target === element);
      fullyIntersecting = isFullyIntersecting(entry);
      schedule();
    }, { threshold: DETAILS_STATUS_VISIBILITY_THRESHOLDS }) : null;
    observer?.observe(element);
    const HostResizeObserver = hostWindow.ResizeObserver;
    const resizeObserver = HostResizeObserver ? new HostResizeObserver(schedule) : null;
    resizeObserver?.observe(element);
    hostWindow.addEventListener("resize", schedule);
    hostWindow.addEventListener("scroll", schedule, true);
    watchStyles();
    update();
    return () => {
      scheduleVisibilityCheck.current = null;
      observer?.disconnect(); resizeObserver?.disconnect(); mutationObserver?.disconnect();
      if (frame !== null) hostWindow.cancelAnimationFrame(frame);
      hostWindow.removeEventListener("resize", schedule); hostWindow.removeEventListener("scroll", schedule, true);
    };
  }, [element]);
  useLayoutEffect(() => { scheduleVisibilityCheck.current?.(); }, [label]);
  return visible;
}

export function isStatusLabelFullyVisible(element: HTMLDivElement): boolean {
  const label = element.querySelector<HTMLElement>("[data-sdh-ludusavi-status-label=\"true\"]");
  if (!label) return false;
  const rowBounds = element.getBoundingClientRect();
  const labelBounds = label.getBoundingClientRect();
  if (rowBounds.width <= 0 || rowBounds.height <= 0 || labelBounds.width <= 0 || labelBounds.height <= 0) {
    return false;
  }
  const hostWindow = getStatusHostWindow(label);
  for (const textElement of [label, ...label.querySelectorAll<HTMLElement>("*")]) {
    if (textElement.hidden) return false;
    const style = hostWindow?.getComputedStyle?.(textElement);
    if (style?.display === "none" || style?.visibility === "hidden" || style?.visibility === "collapse"
      || (style?.opacity !== undefined && Number(style.opacity) <= 0)) return false;
  }
  if (labelBounds.left < rowBounds.left - 1 || labelBounds.right > rowBounds.right + 1
    || labelBounds.top < rowBounds.top - 1 || labelBounds.bottom > rowBounds.bottom + 1) {
    return false;
  }
  if (label.clientWidth > 0 && label.scrollWidth > label.clientWidth + 1) return false;
  if (label.clientHeight > 0 && label.scrollHeight > label.clientHeight + 1) return false;
  return true;
}

export function isVisibleStatusBand(element: HTMLDivElement, intersecting: boolean): boolean {
  if (!intersecting) return false;
  return measureStatusBandPaint(element, () => isThemedStatusBandVisible(element));
}

function isThemedStatusBandVisible(element: HTMLDivElement): boolean {
  const ownerDocument = element.ownerDocument;
  const hostDocument = ownerDocument ?? document;
  const hostWindow = ownerDocument?.defaultView ?? (ownerDocument ? null : window);
  if (!hostWindow) return false;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
    if (ancestor.hidden) return false;
    const style = hostWindow.getComputedStyle?.(ancestor);
    if (style?.display === "none" || style?.visibility === "hidden" || style?.visibility === "collapse"
      || (style?.opacity !== undefined && Number(style.opacity) <= 0)) return false;
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

function asRouteResultElement(value: unknown): ReactElement<RouteRecord> | null {
  if (!isValidElement(value)) return null;
  const props = asRecord(value.props);
  if (!props) return null;
  return value as ReactElement<RouteRecord>;
}

function isRenderableRouteChildren(value: unknown): value is ReactNode {
  if (value === null || value === undefined || isValidElement(value)) return true;
  if (["string", "number", "bigint", "boolean"].includes(typeof value)) return true;
  return Array.isArray(value) && value.every(isRenderableRouteChildren);
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
