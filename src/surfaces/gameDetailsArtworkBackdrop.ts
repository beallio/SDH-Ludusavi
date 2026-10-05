import { getNativeGameDetailsStatusClasses } from "./gameDetailsStatusClasses";
import { appDetailsHeaderClasses } from "@decky/ui";

type HostWindow = Window & {
  MutationObserver?: typeof MutationObserver;
  ResizeObserver?: typeof ResizeObserver;
};
type ArtworkStyleSnapshot = Readonly<{
  element: HTMLElement;
  marker: string | null;
}>;
type ExtendedArtwork = {
  image: HTMLImageElement;
  owner: object;
  naturalHeight: number;
  bandHeight: number;
  inlineHeight: string;
  priority: string;
  managedStyles: ArtworkStyleSnapshot[];
};

const ARTWORK_MARKER = "data-sdh-ludusavi-artwork-band";
const STATUS_ROW_MARKER = "data-sdh-ludusavi-status-row";
const STATUS_ROW_APP_ID = "data-sdh-ludusavi-status-appid";
const PAINT_SUPPRESSED_MARKER = "data-sdh-ludusavi-paint-suppressed";
const BAND_HEIGHT_PROPERTY = "--sdh-status-band-height";
const CLIPPING_OVERFLOW: Record<string, true> = {
  hidden: true,
  clip: true,
  auto: true,
  scroll: true,
};

type SharedBandReservation = {
  original: string;
  priority: string;
  owner: object;
  reservedValue?: string;
  reservedPriority?: string;
  reservedBaseDeduction?: number;
};
type ReservationWindow = Window & {
  __sdhStatusBandReservations?: WeakMap<HTMLElement, SharedBandReservation>;
  __sdhCgvBudgetReservations?: WeakMap<HTMLElement, Map<string, SharedBandReservation>>;
  __sdhArtworkExtensions?: WeakMap<HTMLImageElement, ExtendedArtwork>;
  __sdhNativeArtworkMinHeightReservations?: WeakMap<HTMLElement, SharedBandReservation>;
};

const CGV_TOP_PANEL_HEIGHT = "--CGV-top-panel-height";
const CGV_IMAGE_HEIGHT = "--CGV-image-height";
const CGV_BUDGET_PROPERTIES = [CGV_TOP_PANEL_HEIGHT] as const;
const managedCgvBudgetStyles = new WeakSet<Node>();

function isManagedCgvBudgetStyle(record: MutationRecord): boolean {
  return record.type === "attributes" && record.attributeName === "style" && managedCgvBudgetStyles.has(record.target);
}

function manageCgvBudgetStyle(element: HTMLElement, update: () => void): void {
  managedCgvBudgetStyles.add(element);
  update();
  queueMicrotask(() => managedCgvBudgetStyles.delete(element));
}

function cgvBudgetReservations(element: HTMLElement): Map<string, SharedBandReservation> | null {
  const host = element.ownerDocument.defaultView as ReservationWindow | null;
  if (!host) return null;
  const roots = host.__sdhCgvBudgetReservations ??= new WeakMap();
  let reservations = roots.get(element);
  if (!reservations) {
    reservations = new Map();
    roots.set(element, reservations);
  }
  return reservations;
}

function cgvBudgetValue(bandHeight: number, existingDeduction: number): string {
  const deduction = bandHeight + existingDeduction;
  return `calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height) - ${deduction}px)`;
}

function reserveCgvBudgets(root: HTMLElement, owner: object, bandHeight: number, existingDeduction: number): void {
  const reservations = cgvBudgetReservations(root);
  if (!reservations) return;
  manageCgvBudgetStyle(root, () => {
    const property = CGV_TOP_PANEL_HEIGHT;
    let reservation = reservations.get(property);
    if (!reservation) {
      reservation = {
        original: root.style.getPropertyValue(property),
        priority: root.style.getPropertyPriority(property),
        owner,
      };
      reservations.set(property, reservation);
    }
    const value = cgvBudgetValue(bandHeight, existingDeduction);
    reservation.owner = owner;
    reservation.reservedValue = value;
    reservation.reservedPriority = "important";
    reservation.reservedBaseDeduction = existingDeduction;
    if (root.style.getPropertyValue(property) !== value || root.style.getPropertyPriority(property) !== "important") {
      root.style.setProperty(property, value, "important");
    }
  });
}
function isSupportedCgvGeometry(root: HTMLElement, host: Window): number | null {
  const style = host.getComputedStyle(root);
  const compact = (property: string) => style.getPropertyValue(property).replace(/\s+/g, "");
  const playBar = compact("--CGV-play-bar-height");
  const footer = compact("--CGV-footer-height");
  const image = compact(CGV_IMAGE_HEIGHT);
  if (!/^\d+(?:\.\d+)?px$/.test(playBar) || !/^\d+(?:\.\d+)?px$/.test(footer)) return null;
  const topBases = [
    `calc(100vh-${playBar}-${footer}`,
    "calc(100vh-var(--CGV-play-bar-height)-var(--CGV-footer-height)",
  ];
  const imageBases = [
    `calc(100vh-${footer}`,
    "calc(100vh-var(--CGV-footer-height)",
  ];
  const imageDeduction = knownCgvDeduction(image, imageBases);
  if (imageDeduction === null) return null;
  const reservation = cgvBudgetReservations(root)?.get(CGV_TOP_PANEL_HEIGHT);
  if (reservation) {
    const stillReserved = root.style.getPropertyValue(CGV_TOP_PANEL_HEIGHT) === reservation.reservedValue
      && root.style.getPropertyPriority(CGV_TOP_PANEL_HEIGHT) === reservation.reservedPriority;
    if (!stillReserved || reservation.reservedBaseDeduction !== imageDeduction) return null;
    const originalTop = reservation.original.replace(/\s+/g, "");
    const originalDeduction = originalTop ? knownCgvDeduction(originalTop, topBases) : null;
    return originalDeduction === null || originalDeduction === imageDeduction ? imageDeduction : null;
  }
  const topDeduction = knownCgvDeduction(compact(CGV_TOP_PANEL_HEIGHT), topBases);
  return topDeduction !== null && topDeduction === imageDeduction ? topDeduction : null;
}

function hasCgvBudgetReservation(root: HTMLElement): boolean {
  const reservation = (root.ownerDocument.defaultView as ReservationWindow | null)
    ?.__sdhCgvBudgetReservations?.get(root)?.get(CGV_TOP_PANEL_HEIGHT);
  return Boolean(reservation
    && root.style.getPropertyValue(CGV_TOP_PANEL_HEIGHT) === reservation.reservedValue
    && root.style.getPropertyPriority(CGV_TOP_PANEL_HEIGHT) === reservation.reservedPriority);
}

function releaseCgvBudgets(root: HTMLElement | null, owner: object): boolean {
  if (!root) return false;
  const reservations = (root.ownerDocument.defaultView as ReservationWindow | null)
    ?.__sdhCgvBudgetReservations?.get(root);
  if (!reservations || !CGV_BUDGET_PROPERTIES.some((property) => reservations.get(property)?.owner === owner)) return false;
  manageCgvBudgetStyle(root, () => {
    for (const property of CGV_BUDGET_PROPERTIES) {
      const reservation = reservations.get(property);
      if (!reservation || reservation.owner !== owner) continue;
      const stillOwned = root.style.getPropertyValue(property) === reservation.reservedValue
        && root.style.getPropertyPriority(property) === reservation.reservedPriority;
      if (stillOwned) {
        if (reservation.original) root.style.setProperty(property, reservation.original, reservation.priority);
        else root.style.removeProperty(property);
      }
      reservations.delete(property);
    }
  });
  return true;
}

function ownsCgvBudgets(root: HTMLElement, owner: object): boolean {
  const reservations = (root.ownerDocument.defaultView as ReservationWindow | null)
    ?.__sdhCgvBudgetReservations?.get(root);
  return Boolean(reservations && CGV_BUDGET_PROPERTIES.every((property) => {
    const reservation = reservations.get(property);
    return reservation?.owner === owner
      && root.style.getPropertyValue(property) === reservation.reservedValue
      && root.style.getPropertyPriority(property) === reservation.reservedPriority;
  }));
}

function knownCgvDeduction(value: string, bases: readonly string[]): number | null {
  for (const base of bases) {
    if (value === `${base})`) return 0;
    const suffix = value.slice(base.length);
    const match = suffix.match(/^-(\d+(?:\.\d+)?)px\)$/);
    if (value.startsWith(base) && match) return Number(match[1]);
  }
  return null;
}


function reservedBandHeight(element: HTMLElement, host: Window): number {
  const style = host.getComputedStyle(element);
  if (style.getPropertyValue?.("--sdh-status-band-reserved") !== "1"
    || !style.getPropertyValue("--CGV-image-height")) return 0;
  const value = Number.parseFloat(style.getPropertyValue(BAND_HEIGHT_PROPERTY) || "30");
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

function reserveBand(background: HTMLElement, owner: object, height: number): void {
  const host = background.ownerDocument.defaultView as ReservationWindow | null;
  if (!host) return;
  const reservations = host.__sdhStatusBandReservations ??= new WeakMap();
  let reservation = reservations.get(background);
  if (!reservation) {
    reservation = { original: background.style.getPropertyValue(BAND_HEIGHT_PROPERTY),
      priority: background.style.getPropertyPriority(BAND_HEIGHT_PROPERTY), owner };
    reservations.set(background, reservation);
  } else if (background.style.getPropertyValue(BAND_HEIGHT_PROPERTY) !== reservation.reservedValue
    || background.style.getPropertyPriority(BAND_HEIGHT_PROPERTY) !== reservation.reservedPriority) {
    return;
  }
  reservation.owner = owner;
  const value = `${height}px`;
  reservation.reservedValue = value;
  reservation.reservedPriority = "";
  if (background.style.getPropertyValue(BAND_HEIGHT_PROPERTY) !== value
    || background.style.getPropertyPriority(BAND_HEIGHT_PROPERTY) !== "") {
    background.style.setProperty(BAND_HEIGHT_PROPERTY, value);
  }
}

function releaseBand(background: HTMLElement | null, owner: object): void {
  if (!background) return;
  const reservations = (background.ownerDocument.defaultView as ReservationWindow | null)?.__sdhStatusBandReservations;
  const reservation = reservations?.get(background);
  if (!reservation || reservation.owner !== owner) return;
  const stillOwned = background.style.getPropertyValue(BAND_HEIGHT_PROPERTY) === reservation.reservedValue
    && background.style.getPropertyPriority(BAND_HEIGHT_PROPERTY) === reservation.reservedPriority;
  if (stillOwned) {
    if (reservation.original) background.style.setProperty(BAND_HEIGHT_PROPERTY, reservation.original, reservation.priority);
    else background.style.removeProperty(BAND_HEIGHT_PROPERTY);
  }
  reservations?.delete(background);
}

const paintMeasurements = new WeakSet<Node>();

export function isStatusPaintMeasurement(record: MutationRecord): boolean {
  return record.type === "attributes" && record.attributeName === "style" && paintMeasurements.has(record.target);
}

export function measureStatusBandPaint<T>(element: HTMLElement, measure: () => T): T {
  const style = element.style;
  if (element.getAttribute?.(PAINT_SUPPRESSED_MARKER) !== "true" || style?.getPropertyValue("opacity") !== "0") return measure();
  const priority = style.getPropertyPriority?.("opacity") ?? "";
  paintMeasurements.add(element);
  style.removeProperty("opacity");
  try {
    return measure();
  } finally {
    style.setProperty("opacity", "0", priority);
    // All status observers ignore these writes until this mutation batch is delivered.
    queueMicrotask(() => paintMeasurements.delete(element));
  }
}

export function mountGameDetailsArtworkBackdrop(hostWindow: Window, appID: string): () => void {
  const initialDocument = hostWindow.document;
  if (!initialDocument.body) return () => {};
  const steamPrefix = `/assets/${appID}/`;
  const shortcutPrefix = `/customimages/${appID}_hero.`;
  const nativeClasses = getNativeGameDetailsStatusClasses();
  let currentDocument: Document | null = null;
  let currentWindow = hostWindow as HostWindow;
  let mutationObserver: MutationObserver | null = null;
  let resizeObserver: ResizeObserver | null = null;
  let observedBand: Element | null = null;
  let extended: ExtendedArtwork | null = null;
  let frame: number | null = null;
  let frameWindow: HostWindow | null = null;
  let restoreBeforeSync = false;
  let revalidateCgvGeometry = false;
  const artworkOwner = {};
  const reservationOwner = {};
  let reservationBackground: HTMLElement | null = null;
  let coverageBackground: HTMLElement | null = null;
  let coverageImage: HTMLImageElement | null = null;
  const cgvBudgetOwner = {};
  let cgvBudgetRoot: HTMLElement | null = null;
  let cgvLayoutRoot: HTMLElement | null = null;
  let cgvLayoutRow: HTMLElement | null = null;
  let cgvLayoutBandHeight = 0;
  const backgroundClass = (appDetailsHeaderClasses as Record<string, string | undefined> | undefined)?.HeaderBackgroundImage;

  function cancelFrame(): void {
    if (frame === null) return;
    frameWindow?.cancelAnimationFrame(frame);
    frame = null;
    frameWindow = null;
  }

  function schedule(): void {
    if (frame !== null) return;
    frameWindow = currentWindow;
    frame = currentWindow.requestAnimationFrame(() => {
      frame = null;
      frameWindow = null;
      if (revalidateCgvGeometry) {
        revalidateCgvGeometry = false;
        releaseCgvBudgetCompensation();
      }
      if (restoreBeforeSync) {
        restoreBeforeSync = false;
        restore();
      }
      sync();
    });
  }

  function resize(): void {
    // Coalesce resize restoration and measurement into the same animation frame.
    restoreBeforeSync = true;
    schedule();
  }

  function bindDocument(document: Document): void {
    if (currentDocument === document) return;
    mutationObserver?.disconnect();
    resizeObserver?.disconnect();
    observedBand = null;
    if (currentDocument) {
      currentWindow.removeEventListener("scroll", schedule, true);
      currentWindow.removeEventListener("resize", resize);
      currentDocument.removeEventListener("animationend", schedule, true);
      currentDocument.removeEventListener("transitionend", schedule, true);
      releaseCgvBudgetCompensation();
    }
    if (restoreBeforeSync) {
      restoreBeforeSync = false;
      restore();
    }
    cancelFrame();
    currentDocument = document;
    currentWindow = (document.defaultView as HostWindow | null) ?? (hostWindow as HostWindow);
    const HostMutationObserver = currentWindow.MutationObserver;
    mutationObserver = HostMutationObserver ? new HostMutationObserver((records) => {
      const managedStyles = extended?.managedStyles;
      const isOwnedMutation = (record: MutationRecord) => isStatusPaintMeasurement(record)
        || isManagedCgvBudgetStyle(record)
        || Boolean(managedStyles && record.type === "attributes"
          && (record.attributeName === "style" || record.attributeName === ARTWORK_MARKER)
          && managedStyles.some(({ element }) => element === record.target));
      if (records.length > 0 && records.every(isOwnedMutation)) return;
      if (records.some((record) => !isOwnedMutation(record) && (
        record.target === document.head || document.head?.contains?.(record.target)
        || (record.type === "attributes" && (record.attributeName === "class" || record.attributeName === "style")
          && (record.target === document.body || record.target === document.documentElement
            || record.target === cgvBudgetRoot || (cgvBudgetRoot !== null && record.target.contains?.(cgvBudgetRoot))))
      ))) revalidateCgvGeometry = true;
      schedule();
    }) : null;
    const HostResizeObserver = currentWindow.ResizeObserver;
    resizeObserver = HostResizeObserver ? new HostResizeObserver(schedule) : null;
    if (document.body) mutationObserver?.observe(document.body, {
      attributes: true,
      attributeFilter: ["src", "class", "style", "hidden", "aria-hidden", STATUS_ROW_MARKER, PAINT_SUPPRESSED_MARKER],
      childList: true,
      characterData: true,
      subtree: true,
    });
    if (document.documentElement) mutationObserver?.observe(document.documentElement, {
      attributes: true, attributeFilter: ["class", "style", "hidden"],
    });
    if (document.head) mutationObserver?.observe(document.head, {
      attributes: true, childList: true, characterData: true, subtree: true,
    });
    currentWindow.addEventListener("scroll", schedule, true);
    currentWindow.addEventListener("resize", resize);
    // Steam's entry animation changes geometry without a DOM mutation. A final
    // animation or transition event retries a temporarily rejected native band
    // once without polling, scrolling, or weakening its ownership checks.
    document.addEventListener("animationend", schedule, true);
    document.addEventListener("transitionend", schedule, true);
  }

  function observeBand(element: Element | null): void {
    if (observedBand === element) return;
    resizeObserver?.disconnect();
    observedBand = element;
    if (element) resizeObserver?.observe(element);
  }

  function restore(): void {
    if (!extended) return;
    const previous = extended;
    extended = null;
    const { image, inlineHeight, priority } = previous;
    const reservations = ((image.ownerDocument.defaultView ?? currentWindow) as ReservationWindow).__sdhArtworkExtensions;
    if (previous.owner !== artworkOwner || reservations?.get(image) !== previous) return;
    reservations.delete(image);
    if (inlineHeight) image.style.setProperty("height", inlineHeight, priority);
    else image.style.removeProperty("height");
    for (const snapshot of previous.managedStyles) {
      if (snapshot.marker === null) snapshot.element.removeAttribute(ARTWORK_MARKER);
      else snapshot.element.setAttribute(ARTWORK_MARKER, snapshot.marker);
    }
  }

  function releaseMinimumCoverage(element: HTMLElement | null): void {
    if (!element) return;
    const leases = ((element.ownerDocument.defaultView ?? currentWindow) as ReservationWindow).__sdhNativeArtworkMinHeightReservations;
    const lease = leases?.get(element);
    if (!lease || lease.owner !== cgvBudgetOwner) return;
    if (element.style.getPropertyValue("min-height") === lease.reservedValue
      && element.style.getPropertyPriority("min-height") === "important") {
      manageCgvBudgetStyle(element, () => {
        if (lease.original) element.style.setProperty("min-height", lease.original, lease.priority);
        else element.style.removeProperty("min-height");
      });
    }
    leases?.delete(element);
  }

  function releaseNativeCoverage(): void {
    releaseMinimumCoverage(coverageImage);
    releaseMinimumCoverage(coverageBackground);
    coverageImage = null;
    coverageBackground = null;
  }

  function reserveMinimumCoverage(element: HTMLElement, bandHeight: number): void {
    const host = (element.ownerDocument.defaultView ?? currentWindow) as ReservationWindow;
    const leases = host.__sdhNativeArtworkMinHeightReservations ??= new WeakMap();
    let lease = leases.get(element);
    if (!lease) {
      lease = { original: element.style.getPropertyValue("min-height"),
        priority: element.style.getPropertyPriority("min-height"), owner: cgvBudgetOwner };
      leases.set(element, lease);
    }
    lease.owner = cgvBudgetOwner;
    const value = `calc(var(--CGV-image-height) + ${bandHeight}px)`;
    lease.reservedValue = value;
    if (element.style.getPropertyValue("min-height") !== value
      || element.style.getPropertyPriority("min-height") !== "important") {
      manageCgvBudgetStyle(element, () => element.style.setProperty("min-height", value, "important"));
    }
  }

  function reserveNativeCoverage(background: HTMLElement | null, image: HTMLImageElement | null, bandHeight: number): void {
    if (coverageBackground !== background || coverageImage !== image) releaseNativeCoverage();
    coverageBackground = background;
    coverageImage = image;
    if (background) reserveMinimumCoverage(background, bandHeight);
    if (image) reserveMinimumCoverage(image, bandHeight);
  }

  function releaseCgvBudgetCompensation(): void {
    const root = cgvBudgetRoot;
    if (!releaseCgvBudgets(root, cgvBudgetOwner)) return;
    releaseNativeCoverage();
    cgvBudgetRoot = null;
    if (cgvLayoutRoot === root) {
      cgvLayoutRoot = null;
      cgvLayoutRow = null;
      cgvLayoutBandHeight = 0;
    }
    restore();
  }

  function applyCgvBudgetCompensation(root: HTMLElement, bandHeight: number): boolean {
    const alreadyOwnsRoot = cgvBudgetRoot === root && ownsCgvBudgets(root, cgvBudgetOwner);
    if (cgvBudgetRoot === root && !alreadyOwnsRoot) return false;
    const existingDeduction = isSupportedCgvGeometry(root, currentWindow);
    if (existingDeduction === null) {
      releaseCgvBudgetCompensation();
      return false;
    }
    if (cgvBudgetRoot !== root) {
      releaseCgvBudgetCompensation();
      cgvBudgetRoot = root;
    }
    reserveCgvBudgets(root, cgvBudgetOwner, bandHeight, existingDeduction);
    return true;
  }

  function stableLayoutBandHeight(root: HTMLElement, row: HTMLElement, image?: HTMLElement): number {
    if (cgvLayoutRoot !== root) {
      cgvLayoutRoot = root;
      cgvLayoutRow = null;
      cgvLayoutBandHeight = 0;
    }
    if (row.offsetHeight > 0) {
      cgvLayoutRow = row;
      cgvLayoutBandHeight = row.offsetHeight;
    }
    if (cgvLayoutRow === row && cgvLayoutBandHeight > 0) return cgvLayoutBandHeight;
    return image ? reservedBandHeight(image, currentWindow) : 0;
  }

  function findArtwork(): HTMLImageElement | null {
    if (!currentDocument) return null;
    for (const image of currentDocument.images) {
      const source = image.getAttribute("src") ?? "";
      if (!(source.includes(steamPrefix) && source.includes("/library_hero."))
        && !source.includes(shortcutPrefix)) continue;
      if (!routeContentAncestor(image)) continue;
      const rect = image.getBoundingClientRect();
      if (rect.width >= 420 && rect.height >= 180) return image;
    }
    return null;
  }

  function isStatusBand(element: HTMLElement): boolean {
    if (element.getAttribute?.(STATUS_ROW_MARKER) === "true") return true;
    return nativeClasses !== null && element.classList?.contains(nativeClasses.row) === true;
  }

  function routeStatusRows(document: Document, root: HTMLElement): HTMLElement[] {
    return [...document.querySelectorAll<HTMLElement>(
      `[${STATUS_ROW_MARKER}="true"]${nativeClasses ? `,.${nativeClasses.row}` : ""}`,
    )].filter((row) => {
      if (!isStatusBand(row) || routeContentAncestor(row) !== root) return false;
      const rowAppID = row.getAttribute(STATUS_ROW_APP_ID);
      return rowAppID === null || rowAppID === appID;
    });
  }

  function findRouteStatusRow(document: Document, root: HTMLElement): HTMLElement | null {
    const candidates = routeStatusRows(document, root);
    const rootWidth = root.getBoundingClientRect().width;
    const visible = candidates.find((row) => visibleBandHeight(row, document, { width: rootWidth }) !== null);
    return visible ?? candidates.find((row) => row === observedBand) ?? candidates[0] ?? null;
  }


  function reserveLayoutBand(
    background: HTMLElement | null,
    root: HTMLElement | null,
    artwork: DOMRect,
    edge: number,
  ): void {
    if (!background || !root
      || currentWindow.getComputedStyle(background).getPropertyValue?.("--sdh-status-band-reserved") !== "1") return;
    const row = findRouteStatusRow(currentDocument!, root);
    if (!row) {
      releaseBand(reservationBackground, reservationOwner);
      reservationBackground = null;
      return;
    }
    const rect = row.getBoundingClientRect();
    const height = row.offsetHeight > 0 ? row.offsetHeight
      : cgvLayoutRoot === root && cgvLayoutRow === row ? cgvLayoutBandHeight : 0;
    const hasExpectedGeometry = Math.abs(rect.width - artwork.width) <= 2
      && (cgvBudgetRoot === root || Math.abs(rect.top - edge) <= 1);
    reservationBackground = background;
    reserveBand(background, reservationOwner, hasExpectedGeometry ? height : 0);
  }

  function visibleBandHeight(
    element: HTMLElement,
    document: Document,
    expectedGeometry: Readonly<{ width: number; edge?: number }> | null,
  ): number | null {
    const ownSuppression = element.getAttribute(PAINT_SUPPRESSED_MARKER) === "true"
      && element.style.getPropertyValue("opacity") === "0";
    return measureStatusBandPaint(element, () => {
      const band = element.getBoundingClientRect();
      const bandHeight = element.offsetHeight;
      const root = document.documentElement;
      if (bandHeight <= 0 || band.height <= 0 || band.width <= 0
        || (expectedGeometry !== null && (Math.abs(band.width - expectedGeometry.width) > 2
          || (expectedGeometry.edge !== undefined && Math.abs(band.top - expectedGeometry.edge) > 1)))
        || (expectedGeometry === null && root.clientWidth > 0 && Math.abs(band.width - root.clientWidth) > 2)) return null;

      for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
        if (ancestor.hidden || (ancestor.getAttribute("aria-hidden") === "true" && !(ancestor === element && ownSuppression))) return null;
        const style = currentWindow.getComputedStyle(ancestor);
        if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse"
          || (style.opacity !== "" && Number(style.opacity) <= 0)) return null;
        if (ancestor === element && (style.position === "absolute" || style.position === "fixed" || style.position === "sticky")) return null;
        if (ancestor !== element) {
          const bounds = ancestor.getBoundingClientRect();
          const clipsX = CLIPPING_OVERFLOW[style.overflowX || style.overflow || "visible"] === true;
          const clipsY = CLIPPING_OVERFLOW[style.overflowY || style.overflow || "visible"] === true;
          if ((clipsX && (band.left < bounds.left || band.right > bounds.right))
            || (clipsY && (band.top < bounds.top || band.bottom > bounds.bottom))) return null;
        }
      }

      if ((root.clientWidth > 0 && (band.left < 0 || band.right > root.clientWidth))
        || (root.clientHeight > 0 && (band.bottom <= 0 || band.top >= root.clientHeight))) return null;
      if (typeof document.elementFromPoint === "function") {
        const hit = document.elementFromPoint(band.left + band.width / 2, band.top + Math.min(4, band.height / 2));
        if (!hit || (hit !== element && !element.contains(hit))) return null;
      }
      return bandHeight;
    });
  }

  function routeContentAncestor(element: HTMLElement): HTMLElement | null {
    const innerContainerClass = nativeClasses?.appDetailsInnerContainer;
    if (!innerContainerClass) return null;
    return element.closest(`.${innerContainerClass}`) as HTMLElement | null;
  }

  function visibleRouteBand(document: Document): Readonly<{
    element: HTMLElement;
    contentRoot: HTMLElement;
    visible: boolean;
  }> | null {
    const candidates = [...document.querySelectorAll<HTMLElement>(
      `[${STATUS_ROW_MARKER}="true"]${nativeClasses ? `,.${nativeClasses.row}` : ""}`,
    )].flatMap((element) => {
      if (element.getAttribute(STATUS_ROW_APP_ID) !== appID || !isStatusBand(element)) return [];
      const contentRoot = routeContentAncestor(element);
      if (!contentRoot || contentRoot.getBoundingClientRect().width <= 0) return [];
      return [{ element, contentRoot }];
    });
    const visible = candidates.find(({ element, contentRoot }) =>
      visibleBandHeight(element, document, { width: contentRoot.getBoundingClientRect().width }) !== null);
    const reserved = candidates.find(({ contentRoot }) =>
      contentRoot === cgvBudgetRoot || hasCgvBudgetReservation(contentRoot));
    const selected = visible ?? reserved ?? (candidates.length === 1 ? candidates[0] : null);
    return selected ? {
      ...selected,
      visible: selected === visible,
    } : null;
  }

  function applyExtension(bandHeight: number, image: HTMLImageElement, naturalHeight: number): void {
    const host = (image.ownerDocument.defaultView ?? currentWindow) as ReservationWindow;
    const reservations = host.__sdhArtworkExtensions ??= new WeakMap();
    let reservation = reservations.get(image);
    if (!reservation) {
      const background = image.parentElement;
      const elements = background && background !== image ? [background, image] : [image];
      reservation = {
        owner: artworkOwner, image, naturalHeight, bandHeight,
        inlineHeight: image.style.getPropertyValue("height"),
        priority: image.style.getPropertyPriority("height"),
        managedStyles: elements.map((element) => ({
          element, marker: element.getAttribute(ARTWORK_MARKER),
        })),
      };
      reservations.set(image, reservation);
    }
    reservation.owner = artworkOwner;
    reservation.bandHeight = bandHeight;
    extended = reservation;
    for (const snapshot of reservation.managedStyles) {
      if (snapshot.element.getAttribute(ARTWORK_MARKER) !== "true") snapshot.element.setAttribute(ARTWORK_MARKER, "true");
    }
    const height = `${reservation.naturalHeight + bandHeight}px`;
    if (image.style.getPropertyValue("height") !== height || image.style.getPropertyPriority("height") !== "important") {
      image.style.setProperty("height", height, "important");
    }
  }

  function sync(): void {
    if (!currentDocument) return;
    const image = findArtwork();
    if (extended && extended.image !== image) restore();
    const background = image && backgroundClass ? image.closest(`.${backgroundClass}`) as HTMLElement | null : null;
    if (reservationBackground !== background) {
      releaseBand(reservationBackground, reservationOwner);
      reservationBackground = null;
    }
    if (!image) {
      const routeBand = visibleRouteBand(currentDocument);
      if (!routeBand) {
        releaseCgvBudgetCompensation();
        observeBand(null);
        restore();
        releaseBand(reservationBackground, reservationOwner);
        reservationBackground = null;
        return;
      }
      const hasExistingReservation = routeBand.contentRoot === cgvBudgetRoot
        || hasCgvBudgetReservation(routeBand.contentRoot);
      if (!routeBand.visible && !hasExistingReservation) {
        releaseCgvBudgetCompensation();
        observeBand(routeBand.element);
        restore();
        return;
      }
      const layoutHeight = stableLayoutBandHeight(routeBand.contentRoot, routeBand.element);
      if (layoutHeight > 0 && applyCgvBudgetCompensation(routeBand.contentRoot, layoutHeight)) {
        const routeBackground = backgroundClass
          ? routeBand.contentRoot.querySelector?.<HTMLElement>(`.${backgroundClass}`) ?? null : null;
        reserveNativeCoverage(routeBackground, null, layoutHeight);
      } else releaseCgvBudgetCompensation();
      const currentBand = visibleRouteBand(currentDocument) ?? routeBand;
      observeBand(currentBand.element);
      restore();
      releaseBand(reservationBackground, reservationOwner);
      reservationBackground = null;
      return;
    }
    const ownerDocument = image.ownerDocument ?? currentDocument;
    if (ownerDocument !== currentDocument) bindDocument(ownerDocument);
    const contentRoot = routeContentAncestor(image);
    const trailerOwnsArtwork = image.closest(".decky-metadata-trailer-target") !== null;
    const measureGeometry = () => {
      const artwork = image.getBoundingClientRect();
      const imageHeight = image.offsetHeight;
      if (imageHeight <= 0) return null;
      const scaleY = artwork.height / imageHeight;
      const reservation = ((ownerDocument.defaultView ?? currentWindow) as ReservationWindow).__sdhArtworkExtensions?.get(image);
      const naturalHeight = reservation?.naturalHeight ?? imageHeight - reservedBandHeight(image, currentWindow);
      return { artwork, naturalHeight, edge: artwork.top + naturalHeight * scaleY };
    };
    let geometry = measureGeometry();
    if (!contentRoot || !geometry) {
      releaseCgvBudgetCompensation();
      observeBand(null);
      restore();
      return;
    }
    const statusRow = findRouteStatusRow(ownerDocument, contentRoot);
    if (!statusRow) {
      releaseCgvBudgetCompensation();
      observeBand(null);
      restore();
      reserveLayoutBand(background, contentRoot, geometry.artwork, geometry.edge);
      return;
    }
    const alreadyReserved = hasCgvBudgetReservation(contentRoot);
    const initiallyVisible = visibleBandHeight(statusRow, ownerDocument, {
      width: geometry.artwork.width,
      edge: geometry.edge,
    }) !== null;
    const layoutHeight = stableLayoutBandHeight(contentRoot, statusRow, image);
    const compensated = layoutHeight > 0 && (initiallyVisible || alreadyReserved)
      && applyCgvBudgetCompensation(contentRoot, layoutHeight);
    if (!compensated && !alreadyReserved) releaseCgvBudgetCompensation();
    if (compensated && trailerOwnsArtwork) reserveNativeCoverage(background, image, layoutHeight);
    else releaseNativeCoverage();
    geometry = measureGeometry();
    if (!geometry) {
      observeBand(statusRow);
      restore();
      return;
    }
    const bandHeight = visibleBandHeight(statusRow, ownerDocument, {
      width: geometry.artwork.width,
      ...(compensated ? {} : { edge: geometry.edge }),
    });
    observeBand(statusRow);
    if (bandHeight === null) {
      if (compensated && !trailerOwnsArtwork) applyExtension(layoutHeight, image, geometry.naturalHeight);
      else restore();
      reserveLayoutBand(background, contentRoot, geometry.artwork, geometry.edge);
      return;
    }
    if (!trailerOwnsArtwork && background
      && currentWindow.getComputedStyle(image).getPropertyValue?.("--sdh-status-band-reserved") === "1") {
      reservationBackground = background;
      reserveBand(background, reservationOwner, bandHeight);
    }
    if (trailerOwnsArtwork) {
      restore();
      releaseBand(reservationBackground, reservationOwner);
      reservationBackground = null;
      return;
    }
    if (extended?.bandHeight === bandHeight) return;
    applyExtension(bandHeight, image, extended?.naturalHeight ?? geometry.naturalHeight);
  }

  bindDocument(initialDocument);
  // NativeStatusSlot resolves its occupied state in layout effects. Measure after
  // those commits, before paint, rather than collapsing their temporary hidden row.
  schedule();
  return () => {
    mutationObserver?.disconnect();
    resizeObserver?.disconnect();
    currentWindow.removeEventListener("scroll", schedule, true);
    currentWindow.removeEventListener("resize", resize);
    currentDocument?.removeEventListener("animationend", schedule, true);
    currentDocument?.removeEventListener("transitionend", schedule, true);
    cancelFrame();
    observeBand(null);
    restore();
    releaseBand(reservationBackground, reservationOwner);
    releaseNativeCoverage();
    releaseCgvBudgets(cgvBudgetRoot, cgvBudgetOwner);
  };
}
