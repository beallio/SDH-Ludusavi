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

type SharedBandReservation = { original: string; priority: string; owner: object };
type ReservationWindow = Window & {
  __sdhStatusBandReservations?: WeakMap<HTMLElement, SharedBandReservation>;
  __sdhCgvBudgetReservations?: WeakMap<HTMLElement, Map<string, SharedBandReservation>>;
};

const CGV_TOP_PANEL_HEIGHT = "--CGV-top-panel-height";
const CGV_IMAGE_HEIGHT = "--CGV-image-height";
const CGV_BUDGET_PROPERTIES = [CGV_TOP_PANEL_HEIGHT, CGV_IMAGE_HEIGHT] as const;
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

function cgvBudgetValue(
  property: typeof CGV_TOP_PANEL_HEIGHT | typeof CGV_IMAGE_HEIGHT,
  bandHeight: number,
  existingDeduction: number,
): string {
  const deduction = bandHeight + existingDeduction;
  return property === CGV_TOP_PANEL_HEIGHT
    ? `calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height) - ${deduction}px)`
    : `calc(100vh - var(--CGV-footer-height) - ${deduction}px)`;
}

function reserveCgvBudgets(root: HTMLElement, owner: object, bandHeight: number, existingDeduction: number): void {
  const reservations = cgvBudgetReservations(root);
  if (!reservations) return;
  manageCgvBudgetStyle(root, () => {
    for (const property of CGV_BUDGET_PROPERTIES) {
      let reservation = reservations.get(property);
      if (!reservation) {
        reservation = {
          original: root.style.getPropertyValue(property),
          priority: root.style.getPropertyPriority(property),
          owner,
        };
        reservations.set(property, reservation);
      }
      reservation.owner = owner;
      const value = cgvBudgetValue(property, bandHeight, existingDeduction);
      if (root.style.getPropertyValue(property) !== value || root.style.getPropertyPriority(property) !== "important") {
        root.style.setProperty(property, value, "important");
      }
    }
  });
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
      if (reservation.original) root.style.setProperty(property, reservation.original, reservation.priority);
      else root.style.removeProperty(property);
      reservations.delete(property);
    }
  });
  return true;
}

function ownsCgvBudgets(root: HTMLElement, owner: object): boolean {
  const reservations = (root.ownerDocument.defaultView as ReservationWindow | null)
    ?.__sdhCgvBudgetReservations?.get(root);
  return Boolean(reservations && CGV_BUDGET_PROPERTIES.every((property) => reservations.get(property)?.owner === owner));
}

function measureCgvBaseGeometry<T>(root: HTMLElement, measure: () => T): T {
  const reservations = (root.ownerDocument.defaultView as ReservationWindow | null)
    ?.__sdhCgvBudgetReservations?.get(root);
  const managed = reservations && CGV_BUDGET_PROPERTIES.every((property) => reservations.has(property));
  if (!managed) return measure();
  const current = CGV_BUDGET_PROPERTIES.map((property) => ({
    property,
    value: root.style.getPropertyValue(property),
    priority: root.style.getPropertyPriority(property),
    reservation: reservations.get(property)!,
  }));
  manageCgvBudgetStyle(root, () => {
    for (const entry of current) {
      if (entry.reservation.original) root.style.setProperty(entry.property, entry.reservation.original, entry.reservation.priority);
      else root.style.removeProperty(entry.property);
    }
  });
  try {
    return measure();
  } finally {
    manageCgvBudgetStyle(root, () => {
      for (const entry of current) root.style.setProperty(entry.property, entry.value, entry.priority);
    });
  }
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

function isSupportedCgvGeometry(root: HTMLElement, host: Window): number | null {
  return measureCgvBaseGeometry(root, () => {
    const style = host.getComputedStyle(root);
    const compact = (property: string) => style.getPropertyValue(property).replace(/\s+/g, "");
    const playBar = compact("--CGV-play-bar-height");
    const footer = compact("--CGV-footer-height");
    const top = compact(CGV_TOP_PANEL_HEIGHT);
    const image = compact(CGV_IMAGE_HEIGHT);
    if (!/^\d+(?:\.\d+)?px$/.test(playBar) || !/^\d+(?:\.\d+)?px$/.test(footer)) return null;
    const topDeduction = knownCgvDeduction(top, [
      `calc(100vh-${playBar}-${footer}`,
      "calc(100vh-var(--CGV-play-bar-height)-var(--CGV-footer-height)",
    ]);
    const imageDeduction = knownCgvDeduction(image, [
      `calc(100vh-${footer}`,
      "calc(100vh-var(--CGV-footer-height)",
    ]);
    return topDeduction !== null && topDeduction === imageDeduction ? topDeduction : null;
  });
}

function commonContentAncestor(first: HTMLElement, second: HTMLElement, document: Document): HTMLElement | null {
  const firstAncestors = new Set<HTMLElement>();
  for (let ancestor: HTMLElement | null = first.parentElement; ancestor; ancestor = ancestor.parentElement) {
    firstAncestors.add(ancestor);
  }
  let ancestor = second.parentElement;
  while (ancestor !== null) {
    if (firstAncestors.has(ancestor) && ancestor !== document.body && ancestor !== document.documentElement) return ancestor;
    ancestor = ancestor.parentElement;
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
  }
  reservation.owner = owner;
  const value = `${height}px`;
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
  if (reservation.original) background.style.setProperty(BAND_HEIGHT_PROPERTY, reservation.original, reservation.priority);
  else background.style.removeProperty(BAND_HEIGHT_PROPERTY);
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
  const reservationOwner = {};
  let reservationBackground: HTMLElement | null = null;
  const cgvBudgetOwner = {};
  let cgvBudgetRoot: HTMLElement | null = null;
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
    if (inlineHeight) image.style.setProperty("height", inlineHeight, priority);
    else image.style.removeProperty("height");
    for (const snapshot of previous.managedStyles) {
      if (snapshot.marker === null) snapshot.element.removeAttribute(ARTWORK_MARKER);
      else snapshot.element.setAttribute(ARTWORK_MARKER, snapshot.marker);
    }
  }

  function releaseCgvBudgetCompensation(): void {
    const root = cgvBudgetRoot;
    if (!releaseCgvBudgets(root, cgvBudgetOwner)) return;
    cgvBudgetRoot = null;
    // The existing extension is based on the compensated artwork budget.
    // Restore it before measuring the unmodified geometry again.
    restore();
  }

  function applyCgvBudgetCompensation(root: HTMLElement, bandHeight: number): boolean {
    if (cgvBudgetRoot === root && !ownsCgvBudgets(root, cgvBudgetOwner)) return false;
    const existingDeduction = isSupportedCgvGeometry(root, currentWindow);
    if (existingDeduction === null) {
      releaseCgvBudgetCompensation();
      return false;
    }
    const budgetChanged = CGV_BUDGET_PROPERTIES.some((property) => root.style.getPropertyValue(property) !== cgvBudgetValue(property, bandHeight, existingDeduction)
      || root.style.getPropertyPriority(property) !== "important");
    const isNewRoot = cgvBudgetRoot !== root;
    if (isNewRoot) {
      releaseCgvBudgetCompensation();
      cgvBudgetRoot = root;
    }
    if (isNewRoot || budgetChanged) restore();
    reserveCgvBudgets(root, cgvBudgetOwner, bandHeight, existingDeduction);
    return true;
  }

  function findArtwork(): HTMLImageElement | null {
    if (!currentDocument) return null;
    for (const image of currentDocument.images) {
      const source = image.getAttribute("src") ?? "";
      if (!(source.includes(steamPrefix) && source.includes("/library_hero."))
        && !source.includes(shortcutPrefix)) continue;
      const rect = image.getBoundingClientRect();
      if (rect.width >= 420 && rect.height >= 180) return image;
    }
    return null;
  }

  function isStatusBand(element: HTMLElement): boolean {
    if (element.getAttribute?.(STATUS_ROW_MARKER) === "true") return true;
    return nativeClasses !== null && element.classList?.contains(nativeClasses.row) === true;
  }

  function layoutBandHeight(element: HTMLElement | null, artwork: DOMRect, edge: number): number {
    if (!element || !isStatusBand(element)) return 0;
    return measureStatusBandPaint(element, () => {
      const rect = element.getBoundingClientRect();
      const style = currentWindow.getComputedStyle(element);
      if (element.offsetHeight <= 0 || Math.abs(rect.width - artwork.width) > 2
        || Math.abs(rect.top - edge) > 1 || style.display === "none"
        || style.visibility === "hidden" || style.visibility === "collapse"
        || (style.opacity !== "" && Number(style.opacity) <= 0)
        || style.position === "absolute" || style.position === "fixed" || style.position === "sticky") return 0;
      return element.offsetHeight;
    });
  }

  function reserveLayoutBand(background: HTMLElement | null, artwork: DOMRect, edge: number): void {
    if (!background || currentWindow.getComputedStyle(background).getPropertyValue?.("--sdh-status-band-reserved") !== "1") return;
    let found = false;
    let height = 0;
    for (const row of currentDocument!.querySelectorAll<HTMLElement>(
      `[${STATUS_ROW_MARKER}="true"]${nativeClasses ? `,.${nativeClasses.row}` : ""}`,
    )) {
      found = true;
      height = layoutBandHeight(row, artwork, edge);
      if (height) break;
    }
    if (found) {
      reservationBackground = background;
      reserveBand(background, reservationOwner, height);
    } else {
      releaseBand(reservationBackground, reservationOwner);
      reservationBackground = null;
    }
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
    const rootClass = nativeClasses?.appDetailsRoot;
    if (!rootClass) return null;
    return element.closest(`.${rootClass}`) as HTMLElement | null;
  }

  function visibleRouteBand(document: Document): Readonly<{
    element: HTMLElement;
    height: number;
    contentRoot: HTMLElement;
  }> | null {
    for (const element of document.querySelectorAll<HTMLElement>(
      `[${STATUS_ROW_MARKER}="true"]${nativeClasses ? `,.${nativeClasses.row}` : ""}`,
    )) {
      if (element.getAttribute(STATUS_ROW_APP_ID) !== appID) continue;
      const contentRoot = routeContentAncestor(element);
      if (!contentRoot) continue;
      const rootBounds = contentRoot.getBoundingClientRect();
      if (rootBounds.width <= 0) continue;
      const height = visibleBandHeight(element, document, { width: rootBounds.width });
      if (height !== null) return { element, height, contentRoot };
    }
    return null;
  }

  function applyExtension(bandHeight: number, image: HTMLImageElement, naturalHeight: number): void {
    const originalHeight = extended?.inlineHeight ?? image.style.getPropertyValue("height");
    const originalPriority = extended?.priority ?? image.style.getPropertyPriority("height");
    const managedStyles = extended?.managedStyles ?? (() => {
      const background = image.parentElement;
      const elements = background && background !== image ? [background, image] : [image];
      return elements.map((element) => ({
        element,
        marker: element.getAttribute(ARTWORK_MARKER),
      }));
    })();
    for (const snapshot of managedStyles) {
      snapshot.element.setAttribute(ARTWORK_MARKER, "true");
    }
    image.style.setProperty("height", `${naturalHeight + bandHeight}px`, "important");
    if (extended) extended.bandHeight = bandHeight;
    else extended = {
      image, naturalHeight, bandHeight, inlineHeight: originalHeight, priority: originalPriority, managedStyles,
    };
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
      const compensated = routeBand !== null
        && applyCgvBudgetCompensation(routeBand.contentRoot, routeBand.height);
      if (!compensated) releaseCgvBudgetCompensation();
      const reflowedBand = compensated ? visibleRouteBand(currentDocument) : routeBand;
      if (compensated && reflowedBand === null) {
        releaseCgvBudgetCompensation();
        observeBand(null);
      } else {
        observeBand(reflowedBand?.element ?? null);
      }
      restore();
      releaseBand(reservationBackground, reservationOwner);
      reservationBackground = null;
      return;
    }
    const ownerDocument = image.ownerDocument ?? currentDocument;
    if (ownerDocument !== currentDocument) bindDocument(ownerDocument);
    const trailerOwnsArtwork = image.closest(".decky-metadata-trailer-target") !== null;
    const measureGeometry = () => {
      const artwork = image.getBoundingClientRect();
      const imageHeight = image.offsetHeight;
      if (imageHeight <= 0) return null;
      const scaleY = artwork.height / imageHeight;
      const naturalHeight = extended?.naturalHeight ?? imageHeight - reservedBandHeight(image, currentWindow);
      const edge = artwork.top + naturalHeight * scaleY;
      let element = ownerDocument.elementFromPoint(artwork.left + artwork.width / 2, edge + 1) as HTMLElement | null;
      while (element && element !== ownerDocument.body && !isStatusBand(element)) element = element.parentElement;
      return { artwork, imageHeight, naturalHeight, edge, element };
    };
    let geometry = measureGeometry();
    if (!geometry) {
      releaseCgvBudgetCompensation();
      observeBand(null);
      restore();
      return;
    }
    const visibleHeight = () => geometry?.element && geometry.element !== ownerDocument.body
      ? visibleBandHeight(geometry.element, ownerDocument, { width: geometry.artwork.width, edge: geometry.edge })
      : null;
    let bandHeight = visibleHeight();
    let compensated = false;
    if (bandHeight !== null && geometry.element) {
      const contentRoot = routeContentAncestor(geometry.element)
        ?? commonContentAncestor(image, geometry.element, ownerDocument);
      compensated = contentRoot !== null && applyCgvBudgetCompensation(contentRoot, bandHeight);
      if (!compensated) releaseCgvBudgetCompensation();
      geometry = measureGeometry();
      bandHeight = visibleHeight();
    } else {
      releaseCgvBudgetCompensation();
    }
    if (compensated && (!geometry || bandHeight === null || !geometry.element || geometry.element === ownerDocument.body)) {
      // A supported formula is still rejected if its real reflow fails the
      // unchanged ownership checks. Return to the unmodified layout instead
      // of leaving a partially allocated status band behind.
      releaseCgvBudgetCompensation();
      geometry = measureGeometry();
      bandHeight = visibleHeight();
    }
    if (!geometry || bandHeight === null || !geometry.element || geometry.element === ownerDocument.body) {
      observeBand(null);
      restore();
      if (geometry) reserveLayoutBand(background, geometry.artwork, geometry.edge);
      return;
    }
    if (!trailerOwnsArtwork && background && currentWindow.getComputedStyle(image).getPropertyValue?.("--sdh-status-band-reserved") === "1") {
      reservationBackground = background;
      reserveBand(background, reservationOwner, bandHeight);
    }
    observeBand(geometry.element);
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
    releaseCgvBudgets(cgvBudgetRoot, cgvBudgetOwner);
  };
}
