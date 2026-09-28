import { afterEach, expect, it, vi } from "vitest";
import { mountGameDetailsArtworkBackdrop } from "./gameDetailsArtworkBackdrop";

function gamePage(appID: string, src: string) {
  let naturalHeight = 494;
  let rowTop = 494;
  let scale = 1;
  let rowVisible = true;
  let rowSuppressed = false;
  let metadataOwnsHero = false;
  let height = "";
  let priority = "";
  let notifyMutation = () => {};
  let nextFrame = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const listeners = new Map<string, () => void>();
  const image = {
    style: {
      getPropertyValue: (name: string) => name === "height" ? height : "",
      getPropertyPriority: (name: string) => name === "height" ? priority : "",
      setProperty(name: string, value: string, importance = "") {
        if (name !== "height") return;
        height = value;
        priority = importance;
      },
    },
    getAttribute: (name: string) => name === "src" ? src : null,
    closest: () => metadataOwnsHero ? {} : null,
    get offsetHeight() { return Number.parseFloat(height) || naturalHeight; },
    getBoundingClientRect() {
      const renderedHeight = this.offsetHeight * scale;
      return { left: 0, top: 0, width: 854 * scale, height: renderedHeight, right: 854 * scale, bottom: renderedHeight };
    },
  };
  const row = {
    textContent: "Steam Cloud: Up to date",
    parentElement: null,
    getAttribute: (name: string) => name === "aria-hidden" && rowSuppressed ? "true" : null,
    offsetHeight: 30,
    getBoundingClientRect: () => ({ left: 0, top: rowTop * scale, width: 854 * scale,
      height: 30 * scale, right: 854 * scale, bottom: (rowTop + 30) * scale }),
  };
  const label = { parentElement: row, getBoundingClientRect: () => ({ left: 340 * scale, top: (rowTop + 4) * scale, width: 174 * scale, height: 22 * scale }) };
  const hostDocument = {
    body: {},
    images: [image],
    elementFromPoint: (x: number, y: number) =>
      rowVisible && Math.abs(x - 427 * scale) < 1 && y >= rowTop * scale
        && y < (rowTop + 6) * scale ? label : null,
  };
  const hostWindow = {
    document: hostDocument,
    MutationObserver: class {
      constructor(callback: MutationCallback) { notifyMutation = () => callback([], this as unknown as MutationObserver); }
      observe() {}
      disconnect() { notifyMutation = () => {}; }
    },
    addEventListener: (type: string, listener: () => void) => listeners.set(type, listener),
    removeEventListener: (type: string) => listeners.delete(type),
    requestAnimationFrame(callback: FrameRequestCallback) {
      frames.set(++nextFrame, callback);
      return nextFrame;
    },
    cancelAnimationFrame(id: number) { frames.delete(id); },
  };
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
    get height() { return height; },
    get originalHeight() { return naturalHeight; },
    set rowText(value: string) { row.textContent = value; },
    set visible(value: boolean) { rowVisible = value; notifyMutation(); flush(); },
    set suppressed(value: boolean) { rowSuppressed = value; notifyMutation(); flush(); },
    set metadataOwnsHero(value: boolean) { metadataOwnsHero = value; notifyMutation(); flush(); },
    set scale(value: number) { scale = value; notifyMutation(); flush(); },
    resize(height: number) { naturalHeight = height; rowTop = height; listeners.get("resize")?.(); flush(); },
    scroll() { listeners.get("scroll")?.(); flush(); },
  };
}

afterEach(() => vi.unstubAllGlobals());

it("shows a Steam Cloud row over artwork without fighting an active Metadata trailer", () => {
  const page = gamePage("1942280", "/assets/1942280/library_hero.jpg");
  vi.stubGlobal("document", { images: [], elementFromPoint: () => null });
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);

  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().bottom);
  page.scroll();
  expect(page.image.getBoundingClientRect().bottom).toBe(524);
  page.metadataOwnsHero = true;
  expect(page.image.getBoundingClientRect().bottom).toBe(page.row.getBoundingClientRect().top);
  page.metadataOwnsHero = false;
  expect(page.image.getBoundingClientRect().bottom).toBe(524);

  dispose();
  expect(page.height).toBe("");
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
});

it("keeps the full status image visible while Steam scales the entering page", () => {
  const page = gamePage("3156562597", "/customimages/3156562597_hero.png");
  page.scale = 0.95;
  const dispose = mountGameDetailsArtworkBackdrop(page.hostWindow, page.appID);
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
  expect(page.image.getBoundingClientRect().bottom).toBe(524);

  page.suppressed = true;
  expect(page.image.getBoundingClientRect().bottom).toBe(494);
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
