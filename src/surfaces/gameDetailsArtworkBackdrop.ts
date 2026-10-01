import { getNativeGameDetailsStatusClasses } from "./gameDetailsStatusClasses";

type HostWindow = Window & {
  MutationObserver?: typeof MutationObserver;
  ResizeObserver?: typeof ResizeObserver;
};
type ArtworkStyleSnapshot = Readonly<{
  element: HTMLElement;
  marker: string | null;
  bandHeight: string;
  bandHeightPriority: string;
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
const PAINT_SUPPRESSED_MARKER = "data-sdh-ludusavi-paint-suppressed";
const BAND_HEIGHT_PROPERTY = "--sdh-status-band-height";
const CLIPPING_OVERFLOW: Record<string, true> = {
  hidden: true,
  clip: true,
  auto: true,
  scroll: true,
};

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
      if (records.length > 0 && records.every(isStatusPaintMeasurement)) return;
      const managedStyles = extended?.managedStyles;
      if (records.length > 0 && managedStyles && records.every((record) => record.type === "attributes"
        && (record.attributeName === "style" || record.attributeName === ARTWORK_MARKER)
        && managedStyles.some(({ element }) => element === record.target))) return;
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
      if (snapshot.bandHeight) {
        snapshot.element.style.setProperty(BAND_HEIGHT_PROPERTY, snapshot.bandHeight, snapshot.bandHeightPriority);
      } else {
        snapshot.element.style.removeProperty(BAND_HEIGHT_PROPERTY);
      }
      if (snapshot.marker === null) snapshot.element.removeAttribute(ARTWORK_MARKER);
      else snapshot.element.setAttribute(ARTWORK_MARKER, snapshot.marker);
    }
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


  function visibleBandHeight(
    element: HTMLElement,
    artwork: DOMRect,
    edge: number,
    document: Document,
  ): number | null {
    const ownSuppression = element.getAttribute(PAINT_SUPPRESSED_MARKER) === "true"
      && element.style.getPropertyValue("opacity") === "0";
    return measureStatusBandPaint(element, () => {
      const band = element.getBoundingClientRect();
      const bandHeight = element.offsetHeight;
      if (bandHeight <= 0 || band.height <= 0 || band.width <= 0
        || Math.abs(band.top - edge) > 1 || Math.abs(band.width - artwork.width) > 2) return null;

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

      const root = document.documentElement;
      if ((root.clientWidth > 0 && (band.left < 0 || band.right > root.clientWidth))
        || (root.clientHeight > 0 && (band.bottom <= 0 || band.top >= root.clientHeight))) return null;
      if (typeof document.elementFromPoint === "function") {
        const hit = document.elementFromPoint(band.left + band.width / 2, band.top + Math.min(4, band.height / 2));
        if (!hit || (hit !== element && !element.contains(hit))) return null;
      }
      return bandHeight;
    });
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
        bandHeight: element.style.getPropertyValue(BAND_HEIGHT_PROPERTY),
        bandHeightPriority: element.style.getPropertyPriority(BAND_HEIGHT_PROPERTY),
      }));
    })();
    const managedHeight = `${bandHeight}px`;
    for (const snapshot of managedStyles) {
      snapshot.element.setAttribute(ARTWORK_MARKER, "true");
      if (snapshot.element.style.getPropertyValue(BAND_HEIGHT_PROPERTY) !== managedHeight
        || snapshot.element.style.getPropertyPriority(BAND_HEIGHT_PROPERTY) !== "") {
        snapshot.element.style.setProperty(BAND_HEIGHT_PROPERTY, managedHeight);
      }
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
    if (!image || image.closest(".decky-metadata-trailer-target")) {
      observeBand(null);
      restore();
      return;
    }
    const ownerDocument = image.ownerDocument ?? currentDocument;
    if (ownerDocument !== currentDocument) bindDocument(ownerDocument);
    const artwork = image.getBoundingClientRect();
    const imageHeight = image.offsetHeight;
    if (imageHeight <= 0) {
      observeBand(null);
      restore();
      return;
    }
    const scaleY = artwork.height / imageHeight;
    const naturalHeight = extended?.naturalHeight ?? imageHeight;
    const edge = artwork.top + naturalHeight * scaleY;
    let element = ownerDocument.elementFromPoint(artwork.left + artwork.width / 2, edge + 1) as HTMLElement | null;
    while (element && element !== ownerDocument.body && !isStatusBand(element)) element = element.parentElement;
    if (!element || element === ownerDocument.body) {
      observeBand(null);
      restore();
      return;
    }
    const bandHeight = visibleBandHeight(element, artwork, edge, ownerDocument);
    if (bandHeight === null) {
      observeBand(null);
      restore();
      return;
    }
    observeBand(element);
    if (extended?.bandHeight === bandHeight) return;
    applyExtension(bandHeight, image, extended?.naturalHeight ?? naturalHeight);
  }

  bindDocument(initialDocument);
  sync();
  return () => {
    mutationObserver?.disconnect();
    resizeObserver?.disconnect();
    currentWindow.removeEventListener("scroll", schedule, true);
    currentWindow.removeEventListener("resize", resize);
    cancelFrame();
    observeBand(null);
    restore();
  };
}
