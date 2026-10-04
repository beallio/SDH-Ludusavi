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
  basicAppDetailsSectionStylerClasses: { PlaySection: "native-play-section" },
  appDetailsHeaderClasses: { HeaderBackgroundImage: "native-artwork-background" },
}));

function gamePage(appID: string, src: string) {
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
  let notifyMutation = () => {};
  let nextFrame = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const listeners = new Map<string, () => void>();
  const makeStyle = () => {
    const values = new Map<string, string>();
    const priorities = new Map<string, string>();
    return {
      getPropertyValue: (name: string) => values.get(name) ?? "",
      getPropertyPriority: (name: string) => priorities.get(name) ?? "",
      setProperty(name: string, value: string, importance = "") {
        values.set(name, value);
        priorities.set(name, importance);
      },
      removeProperty(name: string) {
        const value = values.get(name) ?? "";
        values.delete(name);
        priorities.delete(name);
        return value;
      },
    };
  };
  const imageAttributes = new Map<string, string>([["src", src]]);
  const imageStyle = makeStyle();
  const rowStyle = makeStyle();
  const artworkStyle = makeStyle();
  const contentStyle = makeStyle();
  const budgetDeduction = (property: string) => {
    const match = contentStyle.getPropertyValue(property).match(/-\s*(\d+(?:\.\d+)?)px\)\s*$/);
    return match ? Number(match[1]) : 0;
  };
  const backgroundAttributes = new Map<string, string>();
  const image = {
    style: imageStyle,
    get parentElement() { return background; },
    getAttribute: (name: string) => imageAttributes.get(name) ?? null,
    setAttribute: (name: string, value: string) => imageAttributes.set(name, value),
    removeAttribute: (name: string) => imageAttributes.delete(name),
    closest: (selector: string) => selector === ".decky-metadata-trailer-target" && metadataOwnsHero ? {}
      : selector === ".native-artwork-background" ? background : null,
    get offsetHeight() {
      const reserved = earlyReservation ? Number.parseFloat(artworkStyle.getPropertyValue("--sdh-status-band-height") || "30") : 0;
      const layoutHeight = naturalHeight - budgetDeduction("--CGV-image-height");
      return Math.max(Number.parseFloat(imageStyle.getPropertyValue("height")) || layoutHeight, layoutHeight + reserved);
    },
    getBoundingClientRect() {
      const renderedHeight = this.offsetHeight * scale;
      return { left: 0, top: 0, width: 854 * scale, height: renderedHeight, right: 854 * scale, bottom: renderedHeight };
    },
  };
  const background = {
    style: artworkStyle,
    get parentElement() { return content; },
    getAttribute: (name: string) => backgroundAttributes.get(name) ?? null,
    setAttribute: (name: string, value: string) => backgroundAttributes.set(name, value),
    removeAttribute: (name: string) => backgroundAttributes.delete(name),
  };
  const body = {
    parentElement: null,
    hidden: false,
    getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: 534 * scale,
      width: 854 * scale, height: 534 * scale }),
  };
  const content = {
    style: contentStyle,
    parentElement: body,
    hidden: false,
    getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 854 * scale, bottom: 534 * scale,
      width: 854 * scale, height: 534 * scale }),
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
        : name === "data-sdh-ludusavi-paint-suppressed" && rowSuppressed ? "true" : null,
    getClientRects: () => [rowRect()],
    get offsetHeight() { return rowHeight; },
    getBoundingClientRect: rowRect,
  };
  label.parentElement = row;
  const hostDocument = {
    body,
    head: {},
    documentElement: { clientWidth: 854, clientHeight: 534 },
    images: [image],
    querySelector: () => rowMarked || nativeStatusClass ? row : null,
    querySelectorAll: () => rowMarked || nativeStatusClass ? [row] : [],
    elementFromPoint: (x: number, y: number) => {
      const rect = rowRect();
      return rowVisible && x >= rect.left && x <= rect.right && y >= rect.top && y < rect.bottom ? label : null;
    },
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
        if (name === "--CGV-image-height" && element !== content) return contentStyle.getPropertyValue(name)
          || (earlyReservation ? `${naturalHeight}px`
            : cgvMode === "standard" ? "calc(100vh - var(--CGV-footer-height))"
              : cgvMode === "connected" ? "100%" : "");
        if (element === content) {
          if (name === "--CGV-top-panel-height") return contentStyle.getPropertyValue(name)
            || (cgvMode === "standard" ? "calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height))"
              : cgvMode === "connected" ? "calc(100% - var(--CGV-play-bar-height) - var(--CGV-footer-height))" : "");
          if (name === "--CGV-image-height") return contentStyle.getPropertyValue(name)
            || (cgvMode === "standard" ? "calc(100vh - var(--CGV-footer-height))"
              : cgvMode === "connected" ? "100%" : "");
          if (name === "--CGV-play-bar-height") return cgvMode === "none" ? "" : "80px";
          if (name === "--CGV-footer-height") return cgvMode === "none" ? "" : "40px";
        }
        return "";
      },
    }),
    MutationObserver: class {
      constructor(callback: MutationCallback) { notifyMutation = () => callback([], this as unknown as MutationObserver); }
      observe() {}
      disconnect() { notifyMutation = () => {}; }
      takeRecords() { return []; }
    },
    addEventListener: (type: string, listener: () => void) => listeners.set(type, listener),
    removeEventListener: (type: string) => listeners.delete(type),
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
  function flush() {
    for (const [id, callback] of frames) {
      frames.delete(id);
      callback(0);
    }
  }
  return {
    appID,
    image,
    row,
    hostWindow: hostWindow as unknown as Window,
    flush,
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
    resize(height: number) { naturalHeight = height; rowTop = height; listeners.get("resize")?.(); flush(); },
    get backgroundBandVariable() { return artworkStyle.getPropertyValue("--sdh-status-band-height"); },
    get backgroundMarker() { return backgroundAttributes.get("data-sdh-ludusavi-artwork-band") ?? null; },
    scroll() { listeners.get("scroll")?.(); flush(); },
    get backgroundBandVariablePriority() { return artworkStyle.getPropertyPriority("--sdh-status-band-height"); },
    get topPanelBudget() { return contentStyle.getPropertyValue("--CGV-top-panel-height"); },
    get imageBudget() { return contentStyle.getPropertyValue("--CGV-image-height"); },
    get topPanelBudgetPriority() { return contentStyle.getPropertyPriority("--CGV-top-panel-height"); },
    get imageBudgetPriority() { return contentStyle.getPropertyPriority("--CGV-image-height"); },
    set cgv(value: "none" | "standard" | "connected") { cgvMode = value; notifyMutation(); flush(); },
    seedBudgetStyles() {
      contentStyle.setProperty("--CGV-top-panel-height", "calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height))", "important");
      contentStyle.setProperty("--CGV-image-height", "calc(100vh - var(--CGV-footer-height))", "important");
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

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
  expect(page.image.offsetHeight).toBe(494);
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

it("moves a supported default CGV row into the visible budget without changing its native band", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  expect(page.row.getBoundingClientRect().top).toBe(464);
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
  expect(page.topPanelBudget).toBe("calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height) - 30px)");
  expect(page.imageBudget).toBe("calc(100vh - var(--CGV-footer-height) - 30px)");
  expect(page.topPanelBudgetPriority).toBe("important");
  expect(page.imageBudgetPriority).toBe("important");

  dispose();
  expect(page.topPanelBudget).toBe("");
  expect(page.imageBudget).toBe("");
});

it("restores supported CGV budgets on a theme change and leaves unsupported geometry untouched", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  expect(page.row.getBoundingClientRect().top).toBe(464);

  page.cgv = "connected";
  expect(page.topPanelBudget).toBe("");
  expect(page.imageBudget).toBe("");
  expect(page.topPanelBudgetPriority).toBe("");
  expect(page.imageBudgetPriority).toBe("");

  dispose();
});

it("restores pre-existing CGV budget values and priorities on cleanup", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  page.seedBudgetStyles();
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  expect(page.topPanelBudget).toContain("- 30px)");
  expect(page.imageBudget).toContain("- 30px)");
  dispose();
  expect(page.topPanelBudget).toBe("calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height))");
  expect(page.imageBudget).toBe("calc(100vh - var(--CGV-footer-height))");
  expect(page.topPanelBudgetPriority).toBe("important");
  expect(page.imageBudgetPriority).toBe("important");
});

it("does not let stale CGV cleanup erase a newer lifecycle lease", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  page.metadataOwnsHero = true;
  page.seedBudgetStyles();
  const first = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();
  const second = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  first();
  expect(page.topPanelBudget).toContain("- 30px)");
  expect(page.imageBudget).toContain("- 30px)");
  second();
  expect(page.topPanelBudget).toBe("calc(100vh - var(--CGV-play-bar-height) - var(--CGV-footer-height))");
  expect(page.imageBudget).toBe("calc(100vh - var(--CGV-footer-height))");
});

it("keeps CGV allocation available when Metadata owns the trailer without extending its artwork", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  page.cgv = "standard";
  page.metadataOwnsHero = true;
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
  page.flush();

  expect(page.row.getBoundingClientRect().top).toBe(464);
  expect(page.image.getBoundingClientRect().bottom).toBe(464);
  expect(page.height).toBe("");
  dispose();
});
