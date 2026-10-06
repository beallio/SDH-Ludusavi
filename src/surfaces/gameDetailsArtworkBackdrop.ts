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
  naturalHeight?: number;
};
type ReservationWindow = Window & {
  __sdhStatusBandReservations?: WeakMap<HTMLElement, SharedBandReservation>;
  __sdhArtworkExtensions?: WeakMap<HTMLImageElement, ExtendedArtwork>;
  __sdhNativeArtworkMinHeightReservations?: WeakMap<HTMLElement, SharedBandReservation>;
};

const managedArtworkStyles = new WeakSet<Node>();

function isManagedArtworkStyle(record: MutationRecord): boolean {
  return record.type === "attributes" && record.attributeName === "style" && managedArtworkStyles.has(record.target);
}

function manageArtworkStyle(element: HTMLElement, update: () => void): void {
  managedArtworkStyles.add(element);
  update();
  queueMicrotask(() => managedArtworkStyles.delete(element));
}

function supportsCgvArtworkCoverage(root: HTMLElement, host: Window): boolean {
  const style = host.getComputedStyle(root);
  const compact = (property: string) => style.getPropertyValue(property).replace(/\s+/g, "");
  const playBar = compact("--CGV-play-bar-height");
  const footer = compact("--CGV-footer-height");
  if (!/^\d+(?:\.\d+)?px$/.test(playBar) || !/^\d+(?:\.\d+)?px$/.test(footer)) return false;
  const topDeduction = knownCgvDeduction(compact("--CGV-top-panel-height"), [
    `calc(100vh-${playBar}-${footer}`,
    "calc(100vh-var(--CGV-play-bar-height)-var(--CGV-footer-height)",
  ]);
  const imageDeduction = knownCgvDeduction(compact("--CGV-image-height"), [
    `calc(100vh-${footer}`,
    "calc(100vh-var(--CGV-footer-height)",
  ]);
  return topDeduction !== null && topDeduction === imageDeduction;
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
  let refreshBaseline = false;
  let artworkRoot: HTMLElement | null = null;
  const artworkOwner = {};
  const reservationOwner = {};
  let reservationBackground: HTMLElement | null = null;
  let coverageBackground: HTMLElement | null = null;
  let coverageImage: HTMLImageElement | null = null;
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
      if (restoreBeforeSync || refreshBaseline) {
        restoreBeforeSync = false;
        refreshBaseline = false;
        restore();
        releaseNativeCoverage();
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
      releaseNativeCoverage();
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
        || isManagedArtworkStyle(record)
        || Boolean(managedStyles && record.type === "attributes"
          && (record.attributeName === "style" || record.attributeName === ARTWORK_MARKER)
          && managedStyles.some(({ element }) => element === record.target));
      if (records.length > 0 && records.every(isOwnedMutation)) return;
      if (records.some((record) => !isOwnedMutation(record) && (
        record.target === document.head || document.head?.contains?.(record.target)
        || (record.type === "attributes" && (record.attributeName === "class" || record.attributeName === "style")
          && (record.target === document.body || record.target === document.documentElement
            || record.target === artworkRoot || (artworkRoot !== null && record.target.contains?.(artworkRoot))))
      ))) refreshBaseline = true;
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
    const { image, inlineHeight, priority } = previous;
    const reservations = ((image.ownerDocument.defaultView ?? currentWindow) as ReservationWindow).__sdhArtworkExtensions;
    if (previous.owner !== artworkOwner || reservations?.get(image) !== previous) return;
    extended = null;
    reservations.delete(image);
    if (inlineHeight) image.style.setProperty("height", inlineHeight, priority);
    else image.style.removeProperty("height");
    for (const snapshot of previous.managedStyles) {
      if (snapshot.marker === null) snapshot.element.removeAttribute(ARTWORK_MARKER);
      else snapshot.element.setAttribute(ARTWORK_MARKER, snapshot.marker);
    }
  }

  function releaseMinimumCoverage(element: HTMLElement | null): boolean {
    if (!element) return true;
    const leases = ((element.ownerDocument.defaultView ?? currentWindow) as ReservationWindow).__sdhNativeArtworkMinHeightReservations;
    const lease = leases?.get(element);
    if (!lease) return true;
    if (lease.owner !== artworkOwner) return false;
    if (element.style.getPropertyValue("min-height") === lease.reservedValue
      && element.style.getPropertyPriority("min-height") === "important") {
      manageArtworkStyle(element, () => {
        if (lease.original) element.style.setProperty("min-height", lease.original, lease.priority);
        else element.style.removeProperty("min-height");
      });
    }
    leases?.delete(element);
    return true;
  }

  function releaseNativeCoverage(): void {
    if (releaseMinimumCoverage(coverageImage)) coverageImage = null;
    if (releaseMinimumCoverage(coverageBackground)) coverageBackground = null;
  }

  function reserveMinimumCoverage(element: HTMLElement, bandHeight: number, naturalHeight?: number): void {
    const host = (element.ownerDocument.defaultView ?? currentWindow) as ReservationWindow;
    const leases = host.__sdhNativeArtworkMinHeightReservations ??= new WeakMap();
    let lease = leases.get(element);
    if (!lease) {
      lease = { original: element.style.getPropertyValue("min-height"),
        priority: element.style.getPropertyPriority("min-height"), owner: artworkOwner, naturalHeight };
      leases.set(element, lease);
    }
    lease.owner = artworkOwner;
    const value = `calc(var(--CGV-image-height) + ${bandHeight}px)`;
    lease.reservedValue = value;
    if (element.style.getPropertyValue("min-height") !== value
      || element.style.getPropertyPriority("min-height") !== "important") {
      manageArtworkStyle(element, () => element.style.setProperty("min-height", value, "important"));
    }
  }

  function reserveNativeCoverage(background: HTMLElement | null, image: HTMLImageElement | null, bandHeight: number, naturalHeight?: number): void {
    const host = (image?.ownerDocument.defaultView ?? background?.ownerDocument.defaultView ?? currentWindow) as ReservationWindow;
    const leases = host.__sdhNativeArtworkMinHeightReservations;
    const backgroundOwner = background && coverageBackground === background ? leases?.get(background)?.owner : undefined;
    const imageOwner = image && coverageImage === image ? leases?.get(image)?.owner : undefined;
    if ((backgroundOwner !== undefined && backgroundOwner !== artworkOwner)
      || (imageOwner !== undefined && imageOwner !== artworkOwner)) return;
    if (coverageBackground !== background || coverageImage !== image) releaseNativeCoverage();
    coverageBackground = background;
    coverageImage = image;
    if (background) reserveMinimumCoverage(background, bandHeight);
    if (image) reserveMinimumCoverage(image, bandHeight, naturalHeight);
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
    const visible = candidates.find((row) => measureBandHeight(row, document, { width: rootWidth }) !== null);
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
    const height = Math.max(0, row.offsetHeight);
    const hasExpectedGeometry = Math.abs(rect.width - artwork.width) <= 2 && Math.abs(rect.top - edge) <= 1;
    reservationBackground = background;
    reserveBand(background, reservationOwner, hasExpectedGeometry ? height : 0);
  }

  function measureBandHeight(
    element: HTMLElement,
    document: Document,
    expectedGeometry: Readonly<{ width: number; edge?: number }> | null,
    requirePaint = true,
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
          || ((requirePaint || ancestor === element) && style.opacity !== "" && Number(style.opacity) <= 0)) return null;
        if (ancestor === element && (style.position === "absolute" || style.position === "fixed" || style.position === "sticky")) return null;
        if (requirePaint && ancestor !== element) {
          const bounds = ancestor.getBoundingClientRect();
          const clipsX = CLIPPING_OVERFLOW[style.overflowX || style.overflow || "visible"] === true;
          const clipsY = CLIPPING_OVERFLOW[style.overflowY || style.overflow || "visible"] === true;
          if ((clipsX && (band.left < bounds.left || band.right > bounds.right))
            || (clipsY && (band.top < bounds.top || band.bottom > bounds.bottom))) return null;
        }
      }

      if (requirePaint && ((root.clientWidth > 0 && (band.left < 0 || band.right > root.clientWidth))
        || (root.clientHeight > 0 && (band.bottom <= 0 || band.top >= root.clientHeight)))) return null;
      if (requirePaint && typeof document.elementFromPoint === "function") {
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

  function findRouteBand(document: Document): Readonly<{
    element: HTMLElement;
    contentRoot: HTMLElement;
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
      measureBandHeight(element, document, { width: contentRoot.getBoundingClientRect().width }) !== null);
    return visible ?? candidates.find(({ element }) => element === observedBand)
      ?? (candidates.length === 1 ? candidates[0] : null);
  }

  function applyExtension(bandHeight: number, image: HTMLImageElement, naturalHeight: number): void {
    const host = (image.ownerDocument.defaultView ?? currentWindow) as ReservationWindow;
    const reservations = host.__sdhArtworkExtensions ??= new WeakMap();
    let reservation = reservations.get(image);
    if (reservation && reservation.owner !== artworkOwner && extended?.image === image) return;
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
      const routeBand = findRouteBand(currentDocument);
      artworkRoot = routeBand?.contentRoot ?? null;
      const height = routeBand ? measureBandHeight(routeBand.element, currentDocument, {
        width: routeBand.contentRoot.getBoundingClientRect().width,
      }, false) : null;
      if (routeBand && height !== null && supportsCgvArtworkCoverage(routeBand.contentRoot, currentWindow)) {
        const routeBackground = backgroundClass
          ? routeBand.contentRoot.querySelector?.<HTMLElement>(`.${backgroundClass}`) ?? null : null;
        reserveNativeCoverage(routeBackground, null, height);
      } else releaseNativeCoverage();
      observeBand(routeBand?.element ?? null);
      restore();
      return;
    }
    const ownerDocument = image.ownerDocument ?? currentDocument;
    if (ownerDocument !== currentDocument) bindDocument(ownerDocument);
    const contentRoot = routeContentAncestor(image);
    artworkRoot = contentRoot;
    const trailerOwnsArtwork = image.closest(".decky-metadata-trailer-target") !== null;
    const artwork = image.getBoundingClientRect();
    const imageHeight = image.offsetHeight;
    if (!contentRoot || imageHeight <= 0) {
      releaseNativeCoverage();
      observeBand(null);
      restore();
      return;
    }
    const host = (ownerDocument.defaultView ?? currentWindow) as ReservationWindow;
    const naturalHeight = host.__sdhArtworkExtensions?.get(image)?.naturalHeight
      ?? host.__sdhNativeArtworkMinHeightReservations?.get(image)?.naturalHeight
      ?? imageHeight - reservedBandHeight(image, currentWindow);
    const edge = artwork.top + naturalHeight * artwork.height / imageHeight;
    const statusRow = findRouteStatusRow(ownerDocument, contentRoot);
    if (!statusRow) {
      releaseNativeCoverage();
      observeBand(null);
      restore();
      reserveLayoutBand(background, contentRoot, artwork, edge);
      return;
    }
    const expected = { width: artwork.width, edge };
    const layoutHeight = measureBandHeight(statusRow, ownerDocument, expected, false);
    const paintHeight = measureBandHeight(statusRow, ownerDocument, expected);
    const canCover = layoutHeight !== null && supportsCgvArtworkCoverage(contentRoot, currentWindow);
    if (canCover && trailerOwnsArtwork) reserveNativeCoverage(background, image, layoutHeight, naturalHeight);
    else releaseNativeCoverage();
    observeBand(statusRow);
    if (paintHeight === null) {
      if (canCover && !trailerOwnsArtwork) applyExtension(layoutHeight, image, naturalHeight);
      else restore();
      reserveLayoutBand(background, contentRoot, artwork, edge);
      return;
    }
    if (!trailerOwnsArtwork && background
      && currentWindow.getComputedStyle(image).getPropertyValue?.("--sdh-status-band-reserved") === "1") {
      reservationBackground = background;
      reserveBand(background, reservationOwner, paintHeight);
    }
    if (trailerOwnsArtwork) {
      restore();
      releaseBand(reservationBackground, reservationOwner);
      reservationBackground = null;
      return;
    }
    if (extended?.bandHeight === paintHeight) return;
    applyExtension(paintHeight, image, naturalHeight);
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
  };
}
