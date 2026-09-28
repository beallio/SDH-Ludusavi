type HostWindow = Window & { MutationObserver?: typeof MutationObserver };

type ExtendedArtwork = {
  image: HTMLImageElement;
  naturalHeight: number;
  bandHeight: number;
  inlineHeight: string;
  priority: string;
};

export function mountGameDetailsArtworkBackdrop(hostWindow: Window, appID: string): () => void {
  const windowWithObserver = hostWindow as HostWindow;
  const hostDocument = hostWindow.document;
  if (!hostDocument.body) return () => {};
  const steamPrefix = `/assets/${appID}/`;
  const shortcutPrefix = `/customimages/${appID}_hero.`;
  let extended: ExtendedArtwork | null = null;
  let frame: number | null = null;

  function restore(): void {
    if (!extended) return;
    const { image, inlineHeight, priority } = extended;
    extended = null;
    image.style.setProperty("height", inlineHeight, priority);
  }

  function findArtwork(): HTMLImageElement | null {
    for (const image of hostDocument.images) {
      const source = image.getAttribute("src") ?? "";
      if (!(source.includes(steamPrefix) && source.includes("/library_hero."))
        && !source.includes(shortcutPrefix)) continue;
      const rect = image.getBoundingClientRect();
      if (rect.width >= 420 && rect.height >= 180) return image;
    }
    return null;
  }

  function sync(): void {
    const image = findArtwork();
    if (extended && extended.image !== image) restore();
    // Decky Metadata owns the clipped trailer target while a trailer is attached.
    if (!image || image.closest(".decky-metadata-trailer-target")) {
      restore();
      return;
    }
    const artwork = image.getBoundingClientRect();
    if (image.offsetHeight <= 0) {
      restore();
      return;
    }
    const scaleY = artwork.height / image.offsetHeight;
    const naturalHeight = extended?.naturalHeight ?? image.offsetHeight;
    const edge = artwork.top + naturalHeight * scaleY;
    let element = hostDocument.elementFromPoint(artwork.left + artwork.width / 2, edge + 4);
    let bandHeight = 0;
    while (element && element !== hostDocument.body) {
      const band = element.getBoundingClientRect();
      const layoutHeight = (element as HTMLElement).offsetHeight;
      if (Math.abs(band.top - edge) <= 1 && Math.abs(band.width - artwork.width) <= 2
        && layoutHeight >= 24 && layoutHeight <= 40 && element.textContent?.trim()
        && element.getAttribute("aria-hidden") !== "true") {
        bandHeight = layoutHeight;
        break;
      }
      element = element.parentElement;
    }
    if (!bandHeight) {
      restore();
      return;
    }
    if (extended?.bandHeight === bandHeight) return;
    if (extended) {
      extended.bandHeight = bandHeight;
    } else {
      extended = {
        image, naturalHeight, bandHeight,
        inlineHeight: image.style.getPropertyValue("height"),
        priority: image.style.getPropertyPriority("height"),
      };
    }
    image.style.setProperty("height", `${naturalHeight + bandHeight}px`, "important");
  }

  function schedule(): void {
    if (frame !== null) return;
    frame = hostWindow.requestAnimationFrame(() => {
      frame = null;
      sync();
    });
  }

  function resize(): void {
    // Steam can change the natural hero height at a new viewport size.
    restore();
    schedule();
  }

  const HostMutationObserver = windowWithObserver.MutationObserver;
  const observer = HostMutationObserver ? new HostMutationObserver(schedule) : null;
  observer?.observe(hostDocument.body, {
    attributes: true, attributeFilter: ["src", "class", "style", "hidden", "aria-hidden"],
    childList: true, subtree: true,
  });
  hostWindow.addEventListener("scroll", schedule, true);
  hostWindow.addEventListener("resize", resize);
  sync();
  return () => {
    observer?.disconnect();
    hostWindow.removeEventListener("scroll", schedule, true);
    hostWindow.removeEventListener("resize", resize);
    if (frame !== null) hostWindow.cancelAnimationFrame(frame);
    restore();
  };
}
