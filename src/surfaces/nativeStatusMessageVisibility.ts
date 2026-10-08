type Rect = Readonly<{
  left: number;
  top: number;
  right: number;
  bottom: number;
}>;

type RangeRects = Readonly<{
  supported: boolean;
  rects: readonly Rect[] | null;
}>;

type ScanBudget = {
  nodes: number;
  ranges: number;
};

const MAX_ANCESTOR_DEPTH = 64;
const MAX_BRANCH_DEPTH = 64;
const MAX_SCANNED_NODES = 1_024;
const MAX_RANGE_CALLS = 256;
const MAX_CLIENT_RECTS = 128;
const LABEL_SELECTOR = '[data-sdh-ludusavi-status-label="true"]';
const ICON_SELECTOR = '[data-sdh-ludusavi-status-icon="true"] svg';
const REPLACED_OR_NATIVE_PAINT_TAGS: Record<string, true> = {
  AUDIO: true, BUTTON: true, CANVAS: true, EMBED: true, IFRAME: true, IMG: true, INPUT: true, METER: true,
  OBJECT: true, PROGRESS: true, SELECT: true, SVG: true, TEXTAREA: true, VIDEO: true,
};
const BORDER_SIDES = [["Top", "top"], ["Right", "right"], ["Bottom", "bottom"], ["Left", "left"]] as const;
const UNSUPPORTED_PAINT_EFFECTS = [
  ["boxShadow", "box-shadow", "none"],
  ["textShadow", "text-shadow", "none"],
  ["filter", "filter", "none"],
  ["backdropFilter", "backdrop-filter", "none"],
  ["webkitBackdropFilter", "-webkit-backdrop-filter", "none"],
  ["clipPath", "clip-path", "none"],
  ["maskImage", "mask-image", "none"],
  ["webkitMaskImage", "-webkit-mask-image", "none"],
  ["maskBorderSource", "mask-border-source", "none"],
] as const;
const PSEUDO_ELEMENTS = ["::before", "::after"] as const;


/**
 * Returns true only when the foreign center-hit branch and its sibling branches
 * have no known or potentially spilling paint over any part of the message.
 * The row's own branch is intentionally excluded: its background/hero content
 * is underneath the row rather than a foreign obstruction.
 */
export function isNativeStatusMessageUnoccluded(row: HTMLElement, hit: Element): boolean {
  const ownerDocument = row.ownerDocument;
  const ownerWindow = ownerDocument?.defaultView;
  if (!ownerDocument || !ownerWindow || hit.ownerDocument !== ownerDocument || row.contains(hit)) return false;

  const messageRects = collectMessageRects(row, ownerDocument, ownerWindow);
  if (!messageRects) return false;

  let commonAncestor: Element | null = hit;
  let depth = 0;
  while (commonAncestor && !commonAncestor.contains(row) && depth++ < MAX_ANCESTOR_DEPTH) {
    commonAncestor = commonAncestor.parentElement;
  }
  if (!commonAncestor || !commonAncestor.contains(row)) return false;

  let rowBranch: Element = row;
  depth = 0;
  while (rowBranch.parentElement !== commonAncestor && depth++ < MAX_ANCESTOR_DEPTH) {
    const parent = rowBranch.parentElement;
    if (!parent) return false;
    rowBranch = parent;
  }
  if (rowBranch.parentElement !== commonAncestor) return false;

  const budget: ScanBudget = { nodes: MAX_SCANNED_NODES, ranges: MAX_RANGE_CALLS };
  let container: Element | null = commonAncestor;
  depth = 0;
  while (container && depth++ < MAX_ANCESTOR_DEPTH) {
    const style = getStyle(container, ownerWindow);
    if (!style || !isElementNotSuppressed(style)) return false;
    if (!pseudoContentIsAbsent(container, ownerWindow, messageRects)) return false;
    if (!inspectDirectText(container, style, ownerDocument, messageRects, budget)) return false;
    for (let child = container.firstElementChild; child; child = child.nextElementSibling) {
      if (--budget.nodes < 0) return false;
      if (child === rowBranch) continue;
      if (!inspectBranch(child, ownerDocument, ownerWindow, messageRects, budget, 0)) return false;
    }
    if (container === ownerDocument.body) return true;
    rowBranch = container;
    container = container.parentElement;
  }
  return false;
}

function collectMessageRects(
  row: HTMLElement,
  ownerDocument: Document,
  ownerWindow: Window,
): readonly Rect[] | null {
  if (!isVisibleMessagePart(row, row, ownerDocument, ownerWindow)) return null;
  const label = row.querySelector<HTMLElement>(LABEL_SELECTOR);
  const icon = row.querySelector<SVGElement>(ICON_SELECTOR);
  if (!label || !icon || !label.textContent?.trim()) return null;
  if (!isVisibleMessagePart(label, row, ownerDocument, ownerWindow)
    || !isVisibleMessagePart(icon, row, ownerDocument, ownerWindow)) return null;

  const budget: ScanBudget = { nodes: MAX_SCANNED_NODES, ranges: MAX_RANGE_CALLS };
  const messageRects: Rect[] = [];
  let rangeSupported = typeof ownerDocument.createTreeWalker === "function";
  if (rangeSupported) {
    const textNodes = ownerDocument.createTreeWalker(label, 4);
    let node: Node | null;
    while ((node = textNodes.nextNode())) {
      if (!node.nodeValue?.trim()) continue;
      const measured = rangeRects(ownerDocument, node, budget);
      if (!measured.supported) {
        rangeSupported = false;
        break;
      }
      if (!measured.rects) return null;
      for (const rect of measured.rects) {
        messageRects.push(rect);
        if (messageRects.length > MAX_CLIENT_RECTS) return null;
      }
    }
  }
  if (!rangeSupported) {
    const box = elementRect(label);
    if (!box) return null;
    messageRects.length = 0;
    messageRects.push(box);
  }
  if (!messageRects.length) return null;
  const iconRect = elementRect(icon);
  if (!iconRect || iconRect.right <= iconRect.left || iconRect.bottom <= iconRect.top) return null;
  messageRects.push(iconRect);
  return messageRects;
}

function isVisibleMessagePart(
  element: Element,
  row: HTMLElement,
  ownerDocument: Document,
  ownerWindow: Window,
): boolean {
  let current: Element | null = element;
  let targetVisibility: string | null = null;
  let reachedRow = false;
  for (let depth = 0; current && depth <= MAX_ANCESTOR_DEPTH; depth += 1) {
    if (current.ownerDocument !== ownerDocument) return false;
    const style = getStyle(current, ownerWindow);
    if (!style || !isElementNotSuppressed(style)) return false;
    if (current === element) targetVisibility = styleValue(style, "visibility", "visibility", null);
    if (current === row) {
      reachedRow = true;
      break;
    }
    current = current.parentElement;
  }
  return reachedRow && targetVisibility !== null
    && targetVisibility !== "hidden" && targetVisibility !== "collapse";
}

function rangeRects(ownerDocument: Document, node: Node, budget: ScanBudget): RangeRects {
  if (--budget.ranges < 0) return { supported: true, rects: null };
  let range: Range;
  try {
    range = ownerDocument.createRange();
  } catch {
    return { supported: false, rects: null };
  }
  if (!range || typeof range.selectNodeContents !== "function" || typeof range.getClientRects !== "function") {
    return { supported: false, rects: null };
  }

  try {
    range.selectNodeContents(node);
    const clientRects = range.getClientRects();
    if (!clientRects || typeof clientRects.length !== "number" || clientRects.length > MAX_CLIENT_RECTS) {
      return { supported: true, rects: null };
    }
    const rects: Rect[] = [];
    for (let index = 0; index < clientRects.length; index += 1) {
      const rect = copyRect(clientRects[index]);
      if (!rect) return { supported: true, rects: null };
      if (rect.right > rect.left && rect.bottom > rect.top) rects.push(rect);
    }
    return { supported: true, rects };
  } catch {
    return { supported: false, rects: null };
  } finally {
    try {
      range.detach?.();
    } catch {
      // Detached ranges are optional in current engines.
    }
  }
}

function inspectBranch(
  root: Element,
  ownerDocument: Document,
  ownerWindow: Window,
  messageRects: readonly Rect[],
  budget: ScanBudget,
  depth: number,
): boolean {
  if (depth > MAX_BRANCH_DEPTH || --budget.nodes < 0) return false;
  const style = getStyle(root, ownerWindow);
  if (!style) return false;
  const display = styleValue(style, "display", "display", null);
  const opacity = numericValue(styleValue(style, "opacity", "opacity", null));
  const contentVisibility = styleValue(style, "contentVisibility", "content-visibility", "visible");
  if (display === null || opacity === null || contentVisibility === null) return false;
  if (display === "none" || contentVisibility === "hidden") return true;
  if (typeof root.getAnimations === "function") {
    try {
      for (const animation of root.getAnimations()) {
        if (animation.playState === "running" || animation.pending) return false;
      }
    } catch {
      return false;
    }
  }
  if (opacity <= 0) return true;

  if (!inspectElementPaint(root, style, ownerWindow, messageRects)) return false;
  const visibility = styleValue(style, "visibility", "visibility", null);
  if (visibility === null) return false;

  const children = root.childNodes;
  for (let index = 0; index < children.length; index += 1) {
    const child = children[index];
    if (--budget.nodes < 0) return false;
    if (child.nodeType === 3) {
      const text = child.nodeValue ?? "";
      if (visibility !== "hidden" && visibility !== "collapse" && text.trim()
        && !inspectTextNode(root, child, ownerDocument, messageRects, budget)) return false;
    } else if (child.nodeType === 1) {
      if (!inspectBranch(child as Element, ownerDocument, ownerWindow, messageRects, budget, depth + 1)) return false;
    }
  }
  return true;
}

function inspectElementPaint(
  element: Element,
  style: CSSStyleDeclaration,
  ownerWindow: Window,
  messageRects: readonly Rect[],
): boolean {
  if (!isElementNotSuppressed(style)) return true;
  const visibility = styleValue(style, "visibility", "visibility", null);
  if (visibility === null) return false;

  if (!unknownEffectsAreAbsent(style) || !pseudoContentIsAbsent(element, ownerWindow, messageRects)) return false;
  if (visibility === "hidden" || visibility === "collapse") return true;

  const box = elementRect(element);
  const backgroundColor = colorPaintState(styleValue(style, "backgroundColor", "background-color", null));
  if (backgroundColor === "unknown") return false;
  if (backgroundColor === "paint" && (!box || intersectsAny(box, messageRects))) return false;

  const backgroundImage = styleValue(style, "backgroundImage", "background-image", null);
  if (backgroundImage === null) return false;
  if (backgroundImage !== "none") {
    const attachment = styleValue(style, "backgroundAttachment", "background-attachment", "scroll");
    if (attachment === null || /\bfixed\b/i.test(attachment) || !box || intersectsAny(box, messageRects)) return false;
  }

  const borderImage = styleValue(style, "borderImageSource", "border-image-source", "none");
  if (borderImage === null) return false;
  if (borderImage !== "none") {
    const outset = styleValue(style, "borderImageOutset", "border-image-outset", "0");
    if (outset === null || !outset.split(/\s+/).every(value => numericValue(value) === 0)
      || !box || intersectsAny(box, messageRects)) return false;
  }

  if (!borderPaintIsAbsent(style, box, messageRects)) return false;
  if (REPLACED_OR_NATIVE_PAINT_TAGS[element.tagName.toUpperCase()] === true) {
    if (!box || intersectsAny(box, messageRects)) return false;
  }
  return true;
}

function inspectDirectText(
  element: Element,
  style: CSSStyleDeclaration,
  ownerDocument: Document,
  messageRects: readonly Rect[],
  budget: ScanBudget,
): boolean {
  const visibility = styleValue(style, "visibility", "visibility", null);
  if (visibility === null) return false;
  if (visibility === "hidden" || visibility === "collapse") return true;
  const children = element.childNodes;
  for (let index = 0; index < children.length; index += 1) {
    if (--budget.nodes < 0) return false;
    const child = children[index];
    if (child.nodeType === 3 && (child.nodeValue ?? "").trim()
      && !inspectTextNode(element, child, ownerDocument, messageRects, budget)) return false;
  }
  return true;
}

function inspectTextNode(
  parent: Element,
  textNode: Node,
  ownerDocument: Document,
  messageRects: readonly Rect[],
  budget: ScanBudget,
): boolean {
  const measured = rangeRects(ownerDocument, textNode, budget);
  let rects = measured.rects;
  if (!measured.supported) {
    const fallback = elementRect(parent);
    rects = fallback ? [fallback] : null;
  }
  if (!rects) return false;
  for (const rect of rects) {
    if (intersectsAny(rect, messageRects)) return false;
  }
  return true;
}

function borderPaintIsAbsent(
  style: CSSStyleDeclaration,
  box: Rect | null,
  messageRects: readonly Rect[],
): boolean {
  for (const [suffix, side] of BORDER_SIDES) {
    const width = numericValue(styleValue(style, `border${suffix}Width`, `border-${side}-width`, "0px"));
    if (width === null) return false;
    if (width <= 0) continue;
    const borderStyle = styleValue(style, `border${suffix}Style`, `border-${side}-style`, null);
    if (borderStyle === null) return false;
    if (borderStyle === "none" || borderStyle === "hidden") continue;
    const state = colorPaintState(styleValue(style, `border${suffix}Color`, `border-${side}-color`, null));
    if (state === "unknown") return false;
    if (state === "transparent") continue;
    if (!box) return false;
    const borderRect = borderBand(box, side, width);
    if (borderRect && intersectsAny(borderRect, messageRects)) return false;
  }

  const outlineWidth = numericValue(styleValue(style, "outlineWidth", "outline-width", "0px"));
  if (outlineWidth === null) return false;
  if (outlineWidth > 0) {
    const outlineStyle = styleValue(style, "outlineStyle", "outline-style", null);
    if (outlineStyle === null) return false;
    if (outlineStyle !== "none" && outlineStyle !== "hidden") {
      const outlineColor = colorPaintState(styleValue(style, "outlineColor", "outline-color", null));
      if (outlineColor !== "transparent") return false;
    }
  }
  return true;
}

function borderBand(box: Rect, side: "top" | "right" | "bottom" | "left", width: number): Rect | null {
  const limitedWidth = Math.min(width, side === "top" || side === "bottom" ? box.bottom - box.top : box.right - box.left);
  if (limitedWidth <= 0) return null;
  switch (side) {
    case "top": return { left: box.left, top: box.top, right: box.right, bottom: box.top + limitedWidth };
    case "right": return { left: box.right - limitedWidth, top: box.top, right: box.right, bottom: box.bottom };
    case "bottom": return { left: box.left, top: box.bottom - limitedWidth, right: box.right, bottom: box.bottom };
    case "left": return { left: box.left, top: box.top, right: box.left + limitedWidth, bottom: box.bottom };
  }
}

function unknownEffectsAreAbsent(style: CSSStyleDeclaration): boolean {
  for (const [camel, css, safeValue] of UNSUPPORTED_PAINT_EFFECTS) {
    const value = styleValue(style, camel, css, safeValue);
    if (value === null || value !== safeValue) return false;
  }
  const blendMode = styleValue(style, "mixBlendMode", "mix-blend-mode", "normal");
  return blendMode === "normal";
}

function pseudoContentIsAbsent(element: Element, ownerWindow: Window, messageRects: readonly Rect[]): boolean {
  for (const pseudo of PSEUDO_ELEMENTS) {
    const style = getStyle(element, ownerWindow, pseudo);
    if (!style) return false;
    const display = styleValue(style, "display", "display", null);
    const opacity = numericValue(styleValue(style, "opacity", "opacity", null));
    const visibility = styleValue(style, "visibility", "visibility", null);
    const content = styleValue(style, "content", "content", null);
    if (display === null || opacity === null || visibility === null || content === null) return false;
    if (display === "none" || opacity <= 0 || visibility === "hidden" || visibility === "collapse") continue;
    if (content !== "none" && content !== "normal") {
      const hostStyle = getStyle(element, ownerWindow);
      const box = elementRect(element);
      const position = styleValue(style, "position", "position", "static");
      if (!hostStyle || !box || intersectsAny(box, messageRects) || !unknownEffectsAreAbsent(style)
        || position === "fixed"
        || !["hidden", "clip"].includes(styleValue(hostStyle, "overflowX", "overflow-x", "") ?? "")
        || !["hidden", "clip"].includes(styleValue(hostStyle, "overflowY", "overflow-y", "") ?? "")
        || (position === "absolute" && styleValue(hostStyle, "position", "position", "static") === "static")) return false;
    }
  }
  return true;
}

function isElementNotSuppressed(style: CSSStyleDeclaration): boolean {
  const display = styleValue(style, "display", "display", null);
  const opacity = numericValue(styleValue(style, "opacity", "opacity", null));
  const contentVisibility = styleValue(style, "contentVisibility", "content-visibility", "visible");
  return display !== null && opacity !== null && contentVisibility !== null
    && display !== "none" && opacity > 0 && contentVisibility !== "hidden";
}

function getStyle(element: Element, ownerWindow: Window, pseudo?: string): CSSStyleDeclaration | null {
  try {
    return ownerWindow.getComputedStyle(element, pseudo);
  } catch {
    return null;
  }
}

function styleValue(
  style: CSSStyleDeclaration,
  camelName: string,
  cssName: string,
  fallback: string | null,
): string | null {
  const values = style as unknown as Record<string, unknown>;
  const direct = values[camelName];
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const getPropertyValue = values.getPropertyValue;
  if (typeof getPropertyValue === "function") {
    try {
      const value = (getPropertyValue as (name: string) => unknown).call(style, cssName);
      if (typeof value === "string" && value.trim()) return value.trim();
    } catch {
      return null;
    }
  }
  return fallback;
}

function colorPaintState(value: string | null): "paint" | "transparent" | "unknown" {
  if (value === null) return "unknown";
  const color = value.trim().toLowerCase();
  if (color === "transparent") return "transparent";
  if (color.startsWith("#")) {
    const hex = color.slice(1);
    if (/^[0-9a-f]{3}$/.test(hex) || /^[0-9a-f]{6}$/.test(hex)) return "paint";
    if (/^[0-9a-f]{4}$/.test(hex)) return Number.parseInt(hex[3] + hex[3], 16) === 0 ? "transparent" : "paint";
    if (/^[0-9a-f]{8}$/.test(hex)) return Number.parseInt(hex.slice(6), 16) === 0 ? "transparent" : "paint";
    return "unknown";
  }
  if (/^(?:rgb|rgba)\(/.test(color)) {
    const open = color.indexOf("(");
    const body = color.slice(open + 1, color.lastIndexOf(")"));
    const slash = body.lastIndexOf("/");
    if (slash >= 0) return alphaPaintState(body.slice(slash + 1));
    const parts = body.split(",");
    if (parts.length === 4) return alphaPaintState(parts[3]);
    return "paint";
  }
  const slash = color.lastIndexOf("/");
  if (slash >= 0 && color.endsWith(")")) return alphaPaintState(color.slice(slash + 1, -1));
  if (/^[a-z]+$/.test(color)) return "paint";
  return "unknown";
}

function alphaPaintState(rawAlpha: string): "paint" | "transparent" | "unknown" {
  const alpha = rawAlpha.trim().replace(/%$/, "");
  const parsed = Number.parseFloat(alpha);
  if (!Number.isFinite(parsed)) return "unknown";
  return parsed === 0 ? "transparent" : "paint";
}

function numericValue(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function elementRect(element: Element): Rect | null {
  try {
    return copyRect(element.getBoundingClientRect());
  } catch {
    return null;
  }
}

function copyRect(value: DOMRect | DOMRectReadOnly | undefined): Rect | null {
  if (!value) return null;
  const { left, top, right, bottom } = value;
  if (!Number.isFinite(left) || !Number.isFinite(top) || !Number.isFinite(right) || !Number.isFinite(bottom)
    || right < left || bottom < top) return null;
  return value;
}


function intersectsAny(rect: Rect, targets: readonly Rect[]): boolean {
  for (const target of targets) {
    if (rect.left < target.right && rect.right > target.left
      && rect.top < target.bottom && rect.bottom > target.top) return true;
  }
  return false;
}
