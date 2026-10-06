import { afterEach, expect, it, vi } from "vitest";
import { mountGameDetailsArtworkBackdrop } from "./gameDetailsArtworkBackdrop";

vi.mock("@decky/ui", () => ({
  playSectionClasses: {
    CloudStatusRow: "native-status-row",
    CloudStatusIcon: "native-status-icon",
    CloudIconSVG: "native-status-svg",
    CloudStatusLabel: "native-status-label",
    CloudSyncProblem: "native-status-problem",
    CloudSynching: "native-status-syncing",
    CloudStatusUploading: "native-status-uploading",
  },
  basicAppDetailsSectionStylerClasses: { AppDetailsRoot: "native-details-root", PlaySection: "native-play-section" },
  appDetailsClasses: { InnerContainer: "native-inner-container", Header: "native-header" },
  appDetailsHeaderClasses: { HeaderBackgroundImage: "native-artwork-background" },
}));

function gamePage(appID: string, src: string, siblingHeader = false) {
  let naturalHeight = 494;
  let rowTop = 494;
  let scale = 1;
  let rowHeight = 30;
  let rowOpacity = "1";
  let rowVisibility = "visible";
  let rowDisplay = "flex";
  let rowPosition = "static";
  let rowWidth = 854;
  let rowVisible = true;
  let rowSuppressed = false;
  let rowMarked = true;
  let nativeStatusClass = false;
  let clipped = false;
  let metadataOwnsHero = false;
  let earlyReservation = false;
  let cgvMode: "none" | "standard" | "connected" = "none";
  let resolvedCgvGeometry = false;
  let unsupportedHeaderGeometry = false;
  let matchingHero = true;
  let staleRoute = false;
  let nextFrame = 0;
  let frameRuns = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const listeners = new Map<string, Set<() => void>>();
  const documentListeners = new Map<string, Set<() => void>>();
  const mutationCallbacks = new Set<MutationCallback>();
  const pendingMutations: MutationRecord[] = [];
  const mutationTargets = new Map<string, () => Node>();
  const queueMutation = (target: string, attributeName = "style") => {
    const node = mutationTargets.get(target)?.();
    if (node) pendingMutations.push({ type: "attributes", attributeName, target: node } as MutationRecord);
  };
  const makeStyle = (target: string) => {
    const values = new Map<string, string>();
    const priorities = new Map<string, string>();
    return {
      getPropertyValue: (name: string) => values.get(name) ?? "",
      getPropertyPriority: (name: string) => priorities.get(name) ?? "",
      setProperty(name: string, value: string, importance = "") {
        if (values.get(name) === value && priorities.get(name) === importance) return;
        values.set(name, value);
        priorities.set(name, importance);
        queueMutation(target);
      },
      removeProperty(name: string) {
        const value = values.get(name) ?? "";
        const hadValue = values.has(name) || priorities.has(name);
        values.delete(name);
        priorities.delete(name);
        if (hadValue) queueMutation(target);
        return value;
      },
    };
  };
  const imageAttributes = new Map<string, string>([["src", src]]);
  const staleImageAttributes = new Map<string, string>([["src", "/assets/old-app/library_hero.jpg"]]);
  const staleImageStyle = makeStyle("stale-image");
  const staleArtworkStyle = makeStyle("stale-artwork");
  const imageStyle = makeStyle("image");
  const rowStyle = makeStyle("row");
  const artworkStyle = makeStyle("artwork");
  const contentStyle = makeStyle("content");
  const commonContentStyle = siblingHeader ? makeStyle("common-content") : contentStyle;
  const staleContentStyle = makeStyle("stale-content");
  const staleRowStyle = makeStyle("stale-row");
  const bodyStyle = makeStyle("body");
  const budgetDeduction = (property: string) => {
    const match = commonContentStyle.getPropertyValue(property).match(/-\s*(\d+(?:\.\d+)?)px\)\s*$/);
    return match ? Number(match[1]) : 0;
  };
  const staleBudgetDeduction = (property: string) => {
    const match = staleContentStyle.getPropertyValue(property).match(/-\s*(\d+(?:\.\d+)?)px\)\s*$/);
    return match ? Number(match[1]) : 0;
  };
  const backgroundAttributes = new Map<string, string>();
  const staleBackgroundAttributes = new Map<string, string>();
  const image = {
    style: imageStyle,
    get parentElement() { return background; },
    getAttribute: (name: string) => imageAttributes.get(name) ?? null,
    setAttribute(name: string, value: string) { imageAttributes.set(name, value); queueMutation("image", name); },
    removeAttribute(name: string) { imageAttributes.delete(name); queueMutation("image", name); },
    closest: (selector: string) => selector === ".decky-metadata-trailer-target" && metadataOwnsHero ? {}
      : selector === ".native-artwork-background" ? background
        : selector === ".native-inner-container" ? siblingHeader ? commonContent : content : null,
    get offsetHeight() {
      const reserved = earlyReservation ? Number.parseFloat(artworkStyle.getPropertyValue("--sdh-status-band-height") || "30") : 0;
      const layoutHeight = naturalHeight - budgetDeduction("--CGV-image-height");
      const minimum = imageStyle.getPropertyValue("min-height");
      const minimumBand = minimum.match(/\+\s*(\d+(?:\.\d+)?)px\)/);
      const minimumHeight = minimumBand ? layoutHeight + Number(minimumBand[1]) : Number.parseFloat(minimum) || 0;
      return Math.max(Number.parseFloat(imageStyle.getPropertyValue("height")) || layoutHeight, layoutHeight + reserved, minimumHeight);
    },
    getBoundingClientRect() {
      const renderedHeight = this.offsetHeight * scale;
      return { left: 0, top: 0, width: 854 * scale, height: renderedHeight, right: 854 * scale, bottom: renderedHeight };
    },
  };
  const background = {
    style: artworkStyle,
    get parentElement() { return siblingHeader ? commonContent : content; },
    getAttribute: (name: string) => backgroundAttributes.get(name) ?? null,
    setAttribute(name: string, value: string) { backgroundAttributes.set(name, value); queueMutation("artwork", name); },
    removeAttribute(name: string) { backgroundAttributes.delete(name); queueMutation("artwork", name); },
    getBoundingClientRect() {
      const minimumBand = artworkStyle.getPropertyValue("min-height").match(/\+\s*(\d+(?:\.\d+)?)px\)/);
      const height = Math.max(image.offsetHeight, naturalHeight - budgetDeduction("--CGV-image-height")
        + (minimumBand ? Number(minimumBand[1]) : 0)) * scale;
      return { left: 0, top: 0, width: 854 * scale, height, right: 854 * scale, bottom: height };
    },
  };
  const body = {
    style: bodyStyle,
    parentElement: null,
    hidden: false,
    getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: 534 * scale,
      width: 854 * scale, height: 534 * scale }),
  };
  const content = {
    style: contentStyle,
    get parentElement() { return siblingHeader ? commonContent : body; },
    hidden: false,
    getAttribute: () => null,
    querySelector: (selector: string) => selector === ".native-artwork-background" ? background : null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: 534 * scale,
      width: 854 * scale, height: 534 * scale }),
  };
  const commonContent = {
    style: commonContentStyle,
    parentElement: body,
    hidden: false,
    getAttribute: () => null,
    querySelector: (selector: string) => selector === ".native-artwork-background" ? background : null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: 534 * scale,
      width: 854 * scale, height: 534 * scale }),
  };
  const staleContent = {
    style: staleContentStyle,
    parentElement: body,
    hidden: false,
    getAttribute: () => null,
    querySelector: (selector: string) => selector === ".native-artwork-background" ? staleBackground : null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: 534 * scale,
      width: 854 * scale, height: 534 * scale }),
  };
  const staleBackground = {
    style: staleArtworkStyle,
    parentElement: staleContent,
    getAttribute: (name: string) => staleBackgroundAttributes.get(name) ?? null,
    setAttribute(name: string, value: string) { staleBackgroundAttributes.set(name, value); queueMutation("stale-artwork", name); },
    removeAttribute(name: string) { staleBackgroundAttributes.delete(name); queueMutation("stale-artwork", name); },
  };
  const staleNaturalHeight = 494;
  const staleImage = {
    style: staleImageStyle,
    get parentElement() { return staleBackground; },
    getAttribute: (name: string) => staleImageAttributes.get(name) ?? null,
    setAttribute(name: string, value: string) { staleImageAttributes.set(name, value); queueMutation("stale-image", name); },
    removeAttribute(name: string) { staleImageAttributes.delete(name); queueMutation("stale-image", name); },
    closest: (selector: string) => selector === ".native-artwork-background" ? staleBackground
      : selector === ".native-inner-container" ? staleContent : null,
    get offsetHeight() {
      return Number.parseFloat(staleImageStyle.getPropertyValue("height"))
        || staleNaturalHeight - staleBudgetDeduction("--CGV-image-height");
    },
    getBoundingClientRect() {
      const renderedHeight = this.offsetHeight * scale;
      return { left: 0, top: 0, width: 854 * scale, height: renderedHeight, right: 854 * scale, bottom: renderedHeight };
    },
  };
  const rowParent = {
    parentElement: content,
    hidden: false,
    getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: clipped ? (rowTop + 8) * scale : 534 * scale,
      width: 854 * scale, height: clipped ? (rowTop + 8) * scale : 534 * scale }),
  };
  const rowRect = () => {
    const top = rowTop - budgetDeduction("--CGV-top-panel-height");
    return { left: 0, top: top * scale, width: rowWidth * scale,
      height: rowHeight * scale, right: rowWidth * scale, bottom: (top + rowHeight) * scale };
  };
  const label: { parentElement: object | null; getBoundingClientRect: () => {
    left: number; top: number; width: number; height: number;
  } } = {
    parentElement: null,
    getBoundingClientRect: () => ({ left: 340 * scale, top: (rowTop - budgetDeduction("--CGV-top-panel-height") + 4) * scale,
      width: 174 * scale, height: Math.max(1, rowHeight - 8) * scale }),
  };
  const row = {
    style: rowStyle,
    textContent: "Steam Cloud: Up to date",
    parentElement: rowParent,
    classList: { contains: (name: string) => nativeStatusClass && Boolean(name) },
    contains: (element: unknown) => element === label,
    hidden: false,
    getAttribute: (name: string) => name === "aria-hidden" && rowSuppressed ? "true"
      : name === "data-sdh-ludusavi-status-row" && rowMarked ? "true"
        : name === "data-sdh-ludusavi-paint-suppressed" && rowSuppressed ? "true"
          : name === "data-sdh-ludusavi-status-appid" ? appID : null,
    closest: (selector: string) => selector === ".native-details-root" ? content
      : selector === ".native-inner-container" ? siblingHeader ? commonContent : content : null,
    getClientRects: () => [rowRect()],
    get offsetHeight() { return rowHeight; },
    getBoundingClientRect: rowRect,
  };
  label.parentElement = row;
  let staleRowTop = 360;
  const staleRowRect = () => {
    const top = staleRowTop - staleBudgetDeduction("--CGV-top-panel-height");
    return { left: 0, top: top * scale, width: 854 * scale, height: rowHeight * scale,
      right: 854 * scale, bottom: (top + rowHeight) * scale };
  };
  const staleLabel = {
    parentElement: null as object | null,
    getBoundingClientRect: () => ({ left: 340 * scale, top: (staleRowTop - staleBudgetDeduction("--CGV-top-panel-height") + 4) * scale,
      width: 174 * scale, height: Math.max(1, rowHeight - 8) * scale }),
  };
  const staleRowParent = {
    parentElement: staleContent,
    hidden: false,
    getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: 534 * scale,
      width: 854 * scale, height: 534 * scale }),
  };
  const staleRow = {
    style: staleRowStyle,
    textContent: "Ludusavi: Old game",
    parentElement: staleRowParent,
    classList: { contains: () => false },
    contains: (element: unknown) => element === staleLabel,
    hidden: false,
    getAttribute: (name: string) => name === "data-sdh-ludusavi-status-row" ? "true"
      : name === "data-sdh-ludusavi-status-appid" ? "old-app" : null,
    closest: (selector: string) => selector === ".native-details-root" ? staleContent
      : selector === ".native-inner-container" ? staleContent : null,
    getClientRects: () => [staleRowRect()],
    get offsetHeight() { return rowHeight; },
    getBoundingClientRect: staleRowRect,
  };
  staleLabel.parentElement = staleRow;
  const notifyMutation = (target: object = row) => {
    const record = { type: "attributes", attributeName: "class", target } as unknown as MutationRecord;
    mutationCallbacks.forEach((callback) => callback([record], null as unknown as MutationObserver));
  };
  const hostDocument = {
    body,
    head: {},
    documentElement: { clientWidth: 854, clientHeight: 534 },
    get images() { return matchingHero ? staleRoute ? [image, staleImage] : [image] : staleRoute ? [staleImage] : []; },
    querySelector: () => rowMarked || nativeStatusClass ? row : null,
    querySelectorAll: () => rowMarked || nativeStatusClass ? staleRoute ? [staleRow, row] : [row] : staleRoute ? [staleRow] : [],
    elementFromPoint: (x: number, y: number) => {
      const staleRect = staleRowRect();
      if (staleRoute && x >= staleRect.left && x <= staleRect.right && y >= staleRect.top && y < staleRect.bottom) return staleLabel;
      const rect = rowRect();
      return rowVisible && x >= rect.left && x <= rect.right && y >= rect.top && y < rect.bottom ? label : null;
    },
    addEventListener: (type: string, listener: () => void) => {
      const callbacks = documentListeners.get(type) ?? new Set<() => void>();
      callbacks.add(listener); documentListeners.set(type, callbacks);
    },
    removeEventListener: (type: string, listener: () => void) => documentListeners.get(type)?.delete(listener),
  };
  const hostWindow = {
    document: hostDocument,
    getComputedStyle: (element: unknown) => ({
      display: element === row ? rowDisplay : "flex",
      visibility: element === row ? rowVisibility : "visible",
      opacity: element === row ? rowStyle.getPropertyValue("opacity") || rowOpacity : "1",
      position: element === row ? rowPosition : "static",
      overflow: element === rowParent && clipped ? "hidden" : "visible",
      overflowX: "visible",
      overflowY: element === rowParent && clipped ? "hidden" : "visible",
      getPropertyValue: (name: string) => {
        if (name === "--sdh-status-band-reserved") return earlyReservation ? "1" : "";
        if (name === "--sdh-status-band-height") return artworkStyle.getPropertyValue(name);
        const directStyle = element === content ? contentStyle
          : element === staleContent ? staleContentStyle : commonContentStyle;
        if (name === "--CGV-image-height") return directStyle.getPropertyValue(name)
          || (earlyReservation && element !== commonContent && element !== content && element !== staleContent ? `${naturalHeight}px`
            : cgvMode === "standard" ? resolvedCgvGeometry ? "calc(100vh - 40px)" : "calc(100vh - var(--CGV-footer-height))"
              : cgvMode === "connected" ? "100%" : "");
        if (name === "--CGV-top-panel-height") return directStyle.getPropertyValue(name)
          || (unsupportedHeaderGeometry ? "calc(100% - 80px - 40px)"
            : cgvMode === "standard" ? resolvedCgvGeometry ? "calc(100vh - 80px - 40px)" : "calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height))"
              : cgvMode === "connected" ? "calc(100% - var(--CGV-play-bar-height) - var(--CGV-footer-height))" : "");
        if (name === "--CGV-play-bar-height") return cgvMode === "none" ? "" : "80px";
        if (name === "--CGV-footer-height") return cgvMode === "none" ? "" : "40px";
        return "";
      },
    }),
    MutationObserver: class {
      constructor(private readonly callback: MutationCallback) {}
      observe() { mutationCallbacks.add(this.callback); }
      disconnect() { mutationCallbacks.delete(this.callback); }
      takeRecords() { return []; }
    },
    addEventListener: (type: string, listener: () => void) => {
      const callbacks = listeners.get(type) ?? new Set<() => void>();
      callbacks.add(listener); listeners.set(type, callbacks);
    },
    removeEventListener: (type: string, listener: () => void) => listeners.get(type)?.delete(listener),
    requestAnimationFrame(callback: FrameRequestCallback) {
      frames.set(++nextFrame, callback);
      return nextFrame;
    },
    cancelAnimationFrame(id: number) { frames.delete(id); },
  };
  Object.assign(hostDocument, { defaultView: hostWindow });
  Object.assign(image, { ownerDocument: hostDocument });
  Object.assign(background, { ownerDocument: hostDocument });
  Object.assign(content, { ownerDocument: hostDocument });
  Object.assign(commonContent, { ownerDocument: hostDocument });
  Object.assign(staleContent, { ownerDocument: hostDocument });
  mutationTargets.set("image", () => image as unknown as Node);
  mutationTargets.set("row", () => row as unknown as Node);
  mutationTargets.set("artwork", () => background as unknown as Node);
  mutationTargets.set("content", () => content as unknown as Node);
  mutationTargets.set("common-content", () => commonContent as unknown as Node);
  mutationTargets.set("stale-row", () => staleRow as unknown as Node);
  mutationTargets.set("stale-content", () => staleContent as unknown as Node);
  Object.assign(staleImage, { ownerDocument: hostDocument });
  Object.assign(staleBackground, { ownerDocument: hostDocument });
  Object.assign(staleRow, { ownerDocument: hostDocument });
  mutationTargets.set("stale-image", () => staleImage as unknown as Node);
  mutationTargets.set("stale-artwork", () => staleBackground as unknown as Node);
  function flush() {
    let passes = 0;
    while (frames.size > 0 || pendingMutations.length > 0) {
      if (++passes > 20) throw new Error("fixture did not settle");
      for (const [id, callback] of [...frames]) {
        frames.delete(id);
        frameRuns += 1;
        callback(0);
      }
      if (pendingMutations.length > 0) {
        const records = pendingMutations.splice(0);
        mutationCallbacks.forEach((callback) => callback(records, null as unknown as MutationObserver));
      }
    }
  }
  return {
    background,
    staleImage,
    appID,
    image,
    row,
    hostWindow: hostWindow as unknown as Window,
    flush,
    get frameRuns() { return frameRuns; },
    get height() { return imageStyle.getPropertyValue("height"); },
    get originalHeight() { return naturalHeight; },
    get bandVariable() { return imageStyle.getPropertyValue("--sdh-status-band-height"); },
    get heightPriority() { return imageStyle.getPropertyPriority("height"); },
    get artworkMarker() { return image.getAttribute("data-sdh-ludusavi-artwork-band"); },
    get bandVariablePriority() { return imageStyle.getPropertyPriority("--sdh-status-band-height"); },
    set rowText(value: string) { row.textContent = value; },
    set visible(value: boolean) { rowVisible = value; notifyMutation(); flush(); },
    set suppressed(value: boolean) {
      rowSuppressed = value;
      if (value) rowStyle.setProperty("opacity", "0");
      else rowStyle.removeProperty("opacity");
      notifyMutation();
      flush();
    },
    set metadataOwnsHero(value: boolean) { metadataOwnsHero = value; notifyMutation(); flush(); },
    set scale(value: number) { scale = value; notifyMutation(); flush(); },
    set earlyReservation(value: boolean) { earlyReservation = value; notifyMutation(); flush(); },
    set bandHeight(value: number) { rowHeight = value; notifyMutation(); flush(); },
    set bandOpacity(value: string) { rowOpacity = value; notifyMutation(); flush(); },
    set bandVisibility(value: string) { rowVisibility = value; notifyMutation(); flush(); },
    set bandDisplay(value: string) { rowDisplay = value; notifyMutation(); flush(); },
    set bandPosition(value: string) { rowPosition = value; notifyMutation(); flush(); },
    set bandWidth(value: number) { rowWidth = value; notifyMutation(); flush(); },
    set bandTop(value: number) { rowTop = value; notifyMutation(); flush(); },
    set marker(value: boolean) { rowMarked = value; notifyMutation(); flush(); },
    set nativeClass(value: boolean) { nativeStatusClass = value; notifyMutation(); flush(); },
    set clipping(value: boolean) { clipped = value; notifyMutation(); flush(); },
    seedOriginalStyles() {
      imageStyle.setProperty("height", "494px", "important");
      imageStyle.setProperty("--sdh-status-band-height", "12px", "important");
      imageAttributes.set("data-sdh-ludusavi-artwork-band", "original-image-marker");
      artworkStyle.setProperty("--sdh-status-band-height", "14px", "important");
      backgroundAttributes.set("data-sdh-ludusavi-artwork-band", "original-background-marker");
    },
    seedPeerBand() {
      artworkStyle.setProperty("--sdh-status-band-height", "0px");
      Object.assign(hostWindow, {
        __sdhStatusBandReservations: new WeakMap([[background, { original: "", priority: "", owner: {} }]]),
      });
    },
    resize(height: number) { naturalHeight = height; rowTop = height; listeners.get("resize")?.forEach((listener) => listener()); flush(); },
    get backgroundBandVariable() { return artworkStyle.getPropertyValue("--sdh-status-band-height"); },
    get backgroundMarker() { return backgroundAttributes.get("data-sdh-ludusavi-artwork-band") ?? null; },
    scroll() { listeners.get("scroll")?.forEach((listener) => listener()); flush(); },
    scrollOldestOwner() { listeners.get("scroll")?.values().next().value?.(); flush(); },
    get backgroundBandVariablePriority() { return artworkStyle.getPropertyPriority("--sdh-status-band-height"); },
    get topPanelBudget() { return commonContentStyle.getPropertyValue("--CGV-top-panel-height"); },
    get imageBudget() { return commonContentStyle.getPropertyValue("--CGV-image-height"); },
    get staleTopPanelBudget() { return staleContentStyle.getPropertyValue("--CGV-top-panel-height"); },
    get staleImageBudget() { return staleContentStyle.getPropertyValue("--CGV-image-height"); },
    get outerTopPanelBudget() { return bodyStyle.getPropertyValue("--CGV-top-panel-height"); },
    get topPanelBudgetPriority() { return commonContentStyle.getPropertyPriority("--CGV-top-panel-height"); },
    get imageBudgetPriority() { return commonContentStyle.getPropertyPriority("--CGV-image-height"); },
    get playStatusTopPanelBudget() { return contentStyle.getPropertyValue("--CGV-top-panel-height"); },
    get playStatusImageBudget() { return contentStyle.getPropertyValue("--CGV-image-height"); },
    set cgv(value: "none" | "standard" | "connected") { cgvMode = value; notifyMutation(hostDocument.head); flush(); },
    set browserResolvedCgvGeometry(value: boolean) { resolvedCgvGeometry = value; notifyMutation(hostDocument.head); flush(); },
    set unsupportedHeader(value: boolean) { unsupportedHeaderGeometry = value; notifyMutation(hostDocument.head); flush(); },
    set matchingHeroAvailable(value: boolean) { matchingHero = value; notifyMutation(); flush(); },
    set oldRouteMounted(value: boolean) { staleRoute = value; notifyMutation(); flush(); },
    set overlappingRoute(value: boolean) {
      staleRoute = value;
      staleRowTop = value ? rowTop : 360;
      notifyMutation();
      flush();
    },
    completeEntryAnimation() {
      scale = 1;
      rowVisible = true;
      documentListeners.get("animationend")?.forEach((listener) => listener());
      flush();
    },
    get browserResolvedTopBudget() { return hostWindow.getComputedStyle(commonContent).getPropertyValue("--CGV-top-panel-height"); },
    get browserResolvedImageBudget() { return hostWindow.getComputedStyle(commonContent).getPropertyValue("--CGV-image-height"); },
    seedBudgetStyles(deduction = 0) {
      const suffix = deduction ? ` - ${deduction}px` : "";
      commonContentStyle.setProperty("--CGV-top-panel-height", `calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height)${suffix})`, "important");
      commonContentStyle.setProperty("--CGV-image-height", `calc(100vh - var(--CGV-footer-height)${suffix})`, "important");
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

it.each(["Steam Cloud", "Ludusavi"])("keeps the original %s row placement when artwork coverage mounts", (kind) => {
  const steam = kind === "Steam Cloud";
  const page = gamePage(steam ? "1942280" : "2155012430", steam
    ? "/assets/1942280/library_hero.jpg" : "/customimages/2155012430_hero.png", true);
  page.cgv = "standard";
  page.earlyReservation = true;
  page.rowText = `${kind}: Up to date`;
  page.marker = !steam;
  page.nativeClass = steam;
  const original = page.row.getBoundingClientRect();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.row.getBoundingClientRect()).toEqual(original);
  expect(page.image.getBoundingClientRect().bottom).toBe(original.bottom);
  page.scroll();
  expect(page.row.getBoundingClientRect()).toEqual(original);
  dispose();
});

it.each(["Steam Cloud", "Ludusavi"])("keeps the original %s row placement when no hero image is available", (kind) => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg", true);
  page.cgv = "standard";
  page.matchingHeroAvailable = false;
  page.rowText = `${kind}: Up to date`;
  page.marker = kind !== "Steam Cloud";
  page.nativeClass = kind === "Steam Cloud";
  const original = page.row.getBoundingClientRect();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.row.getBoundingClientRect()).toEqual(original);
  dispose();
});

it("preserves a peer's existing header and image layout without adding another deduction", () => {
  const page = gamePage("2155012430", "/customimages/2155012430_hero.png", true);
  page.cgv = "standard";
  page.earlyReservation = true;
  page.seedBudgetStyles(15);
  const original = page.row.getBoundingClientRect();
  const header = page.topPanelBudget;
  const image = page.imageBudget;
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.row.getBoundingClientRect()).toEqual(original);
  expect(page.topPanelBudget).toBe(header);
  expect(page.imageBudget).toBe(image);
  dispose();
});

it("keeps the newer trailer canvas when an older owner's late event is followed by cleanup", () => {
  const page = gamePage("2155012430", "/customimages/2155012430_hero.png", true);
  page.cgv = "standard";
  page.metadataOwnsHero = true;
  const first = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  const second = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  page.bandHeight = 44;
  page.scrollOldestOwner();
  first();
  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  second();
  expect(page.image.getBoundingClientRect().height).toBe(page.originalHeight);
});

it("keeps the newer ordinary image extension after a covered older owner's late event and cleanup", () => {
  const page = gamePage("2155012430", "/customimages/2155012430_hero.png", true);
  page.cgv = "standard";
  const first = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  const second = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  page.visible = false;
  page.scrollOldestOwner();
  first();
  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  second();
  expect(page.image.getBoundingClientRect().height).toBe(page.originalHeight);
});

it("remeasures Metadata coverage after external geometry changes without moving the native row", () => {
  const page = gamePage("2155012430", "/customimages/2155012430_hero.png", true);
  page.cgv = "standard";
  page.metadataOwnsHero = true;
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  page.seedBudgetStyles(12);
  page.flush();
  expect(page.row.getBoundingClientRect().top).toBe(page.originalHeight - 12);
  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  dispose();
});

it("shows a Steam Cloud row over artwork without fighting an active Metadata trailer", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  vi.stubGlobal("document", { images: [], elementFromPoint: () => null });
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  expect(page.artworkMarker).toBe("true");
  page.scroll();
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.metadataOwnsHero = true;
  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().top);
  page.metadataOwnsHero = false;
  expect(page.image.getBoundingClientRect().bottom).toBe(524);

  dispose();
  expect(page.height).toBe("");
  expect(page.bandVariable).toBe("");
  expect(page.artworkMarker).toBeNull();
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
});


it("keeps the full status image visible while Steam scales the entering page", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png");
  page.scale = 0.95;
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBeCloseTo(page.row.getBoundingClientRect().bottom);

  page.scale = 1;
  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  dispose();
  expect(page.height).toBe("");
});

it("restores a non-Steam image when its Ludusavi row yields, leaves, or resizes", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png?v=1");
  page.rowText = "Ludusavi: Up to date";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBe(524);

  page.suppressed = true;
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.bandOpacity = "0";
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  page.bandOpacity = "1";
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.suppressed = false;
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.visible = false;
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  page.visible = true;
  page.resize(510);
  expect(page.image.getBoundingClientRect().bottom).toBe(540);
  expect(page.row.getBoundingClientRect().top).toBe(510);

  dispose();
  expect(page.height).toBe("");
  expect(page.image.getBoundingClientRect().bottom).toBe(510);
});

it("covers the actual themed band height instead of a fixed 30-pixel allowance", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png");
  page.bandHeight = 52;
  page.scale = 0.95;
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBeCloseTo(page.row.getBoundingClientRect().bottom);
  page.bandHeight = 44;
  expect(page.image.getBoundingClientRect().bottom).toBeCloseTo(page.row.getBoundingClientRect().bottom);
  expect(page.height).toBe("538px");
  dispose();
  expect(page.height).toBe("");
});

it("restores original artwork styles and attributes on cleanup", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png");
  page.seedOriginalStyles();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  expect(page.height).toBe("524px");
  expect(page.artworkMarker).toBe("true");
  expect(page.backgroundMarker).toBe("true");
  dispose();
  expect(page.height).toBe("494px");
  expect(page.artworkMarker).toBe("original-image-marker");
  expect(page.bandVariable).toBe("12px");
  expect(page.heightPriority).toBe("important");
  expect(page.backgroundMarker).toBe("original-background-marker");
  expect(page.bandVariablePriority).toBe("important");
  expect(page.backgroundBandVariable).toBe("14px");
  expect(page.backgroundBandVariablePriority).toBe("important");
});

it("recognizes Steam-native rows but never extends arbitrary or clipped artwork bands", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png");
  page.marker = false;
  page.rowText = "Activity";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBe(494);

  page.nativeClass = true;
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.bandPosition = "absolute";
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  page.bandPosition = "static";
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.clipping = true;
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  dispose();
});

it("restores the artwork when a status row is moved or display-hidden", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png");
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBe(524);

  page.bandPosition = "fixed";
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  page.bandPosition = "static";
  page.bandTop = 496;
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  page.bandTop = 494;
  expect(page.image.getBoundingClientRect().bottom).toBe(524);

  page.bandVisibility = "hidden";
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  page.bandVisibility = "visible";
  page.bandDisplay = "none";
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  dispose();
});

it("does not reserve full-width artwork for a theme-hidden or compact indicator", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png");
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  page.bandOpacity = "0";
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  page.bandOpacity = "1";
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.bandWidth = 32;
  page.bandHeight = 16;
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  dispose();
});

it("adopts an early theme reservation and resizes the band without a second crop or double allowance", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.earlyReservation = true;
  expect(page.image.offsetHeight).toBe(524);
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.offsetHeight).toBe(524);
  page.bandHeight = 52;
  expect(page.image.offsetHeight).toBe(546);
  page.bandWidth = 32;
  page.bandHeight = 16;
  expect(page.image.offsetHeight).toBe(494);
  dispose();
  expect(page.backgroundBandVariable).toBe("");
});

it("keeps a full-width row reserved while the entering page is temporarily covered", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.earlyReservation = true;
  page.visible = false;
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.offsetHeight).toBe(524);
  page.visible = true;
  expect(page.image.offsetHeight).toBe(524);
  page.bandOpacity = "0";
  expect(page.image.offsetHeight).toBe(524);
  dispose();
});

it("restores the genuine CSS variable when the reservation theme is enabled after the artwork extension", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.seedOriginalStyles();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  page.earlyReservation = true;
  expect(page.image.offsetHeight).toBe(524);
  dispose();
  expect(page.backgroundBandVariable).toBe("14px");
  expect(page.backgroundBandVariablePriority).toBe("important");
  expect(page.bandVariable).toBe("12px");
});

it("keeps the early reservation until native slot layout effects finish", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.earlyReservation = true;
  page.bandDisplay = "none";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  expect(page.image.offsetHeight).toBe(524);
  page.bandDisplay = "flex";
  expect(page.image.offsetHeight).toBe(524);
  dispose();
});

it("keeps full hero coverage when an overlay covers the mounted native row", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  const fullHeight = page.image.getBoundingClientRect().height;
  page.visible = false;
  expect(page.image.getBoundingClientRect().height).toBe(fullHeight);
  page.visible = true;
  expect(page.image.getBoundingClientRect().height).toBe(fullHeight);
  dispose();
});

it("shares one hero extension across overlapping owners and ignores stale cleanup", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  const originalHeight = page.image.getBoundingClientRect().height;
  const first = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  const fullHeight = page.image.getBoundingClientRect().height;
  const second = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().height).toBe(fullHeight);
  first();
  expect(page.image.getBoundingClientRect().height).toBe(fullHeight);
  second();
  expect(page.image.getBoundingClientRect().height).toBe(originalHeight);
});

it("releases an unsupported header theme without changing full hero coverage", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  const fullHeight = page.image.getBoundingClientRect().height;
  page.unsupportedHeader = true;
  expect(page.row.getBoundingClientRect().top).toBe(494);
  expect(page.image.getBoundingClientRect().height).toBe(fullHeight);
  dispose();
});

it("keeps native trailer coverage with browser-resolved CGV values without moving controls", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  page.browserResolvedCgvGeometry = true;
  page.metadataOwnsHero = true;
  const original = page.row.getBoundingClientRect();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBe(original.bottom);
  expect(page.row.getBoundingClientRect()).toEqual(original);
  page.cgv = "connected";
  expect(page.row.getBoundingClientRect()).toEqual(original);
  expect(page.image.getBoundingClientRect().height).toBe(page.originalHeight);
  dispose();
});

it("leaves third-party layout changes untouched while artwork is mounted", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  page.seedBudgetStyles(12);
  page.flush();
  const thirdPartyTop = "calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height) - 12px)";
  const thirdPartyImage = "calc(100vh - var(--CGV-footer-height) - 12px)";
  expect(page.topPanelBudget).toBe(thirdPartyTop);
  expect(page.imageBudget).toBe(thirdPartyImage);
  dispose();
  expect(page.topPanelBudget).toBe(thirdPartyTop);
  expect(page.imageBudget).toBe(thirdPartyImage);
});

it("preserves full native artwork coverage while Metadata owns the trailer", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  page.metadataOwnsHero = true;
  const original = page.row.getBoundingClientRect();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  expect(page.row.getBoundingClientRect()).toEqual(original);
  expect(page.image.getBoundingClientRect().bottom).toBe(original.bottom);
  expect(page.height).toBe("");
  dispose();
});

it("keeps native artwork full-size without changing a peer-owned zero allowance", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg", true);
  page.cgv = "standard";
  page.earlyReservation = true;
  page.metadataOwnsHero = true;
  page.seedPeerBand();
  const original = page.row.getBoundingClientRect();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().height).toBe(524);
  expect(page.row.getBoundingClientRect()).toEqual(original);
  expect(page.height).toBe("");
  expect(page.backgroundBandVariable).toBe("0px");
  dispose();
  expect(page.image.getBoundingClientRect().height).toBe(494);
  expect(page.backgroundBandVariable).toBe("0px");
});

it("covers the correct native background without an image, including entry, resize and stale routes", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg", true);
  page.cgv = "standard";
  page.matchingHeroAvailable = false;
  page.oldRouteMounted = true;
  page.scale = 0.95;
  page.visible = false;
  const original = page.row.getBoundingClientRect();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.row.getBoundingClientRect()).toEqual(original);
  expect(page.background.getBoundingClientRect().bottom).toBeCloseTo(original.bottom);
  page.completeEntryAnimation();
  expect(page.background.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  page.bandHeight = 44;
  expect(page.background.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  dispose();
  expect(page.background.getBoundingClientRect().height).toBe(page.originalHeight);
});

it("keeps overlapping artwork copies on their own native route roots without moving either row", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg", true);
  page.cgv = "standard";
  const original = page.row.getBoundingClientRect();
  const disposeCurrent = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBe(original.bottom);
  page.overlappingRoute = true;
  expect(page.row.getBoundingClientRect()).toEqual(original);
  expect(page.staleImage.getBoundingClientRect().height).toBe(page.originalHeight);
  const disposeExiting = mountGameDetailsArtworkBackdrop(page.hostWindow, "old-app");
  page.flush();
  expect(page.image.getBoundingClientRect().bottom).toBe(original.bottom);
  expect(page.staleImage.getBoundingClientRect().bottom).toBe(original.bottom);
  disposeCurrent();
  expect(page.image.getBoundingClientRect().height).toBe(page.originalHeight);
  expect(page.staleImage.getBoundingClientRect().bottom).toBe(original.bottom);
  disposeExiting();
  expect(page.staleImage.getBoundingClientRect().height).toBe(page.originalHeight);
});
