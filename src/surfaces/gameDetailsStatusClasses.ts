import { appDetailsClasses, appDetailsHeaderClasses, basicAppDetailsSectionStylerClasses, playSectionClasses } from "@decky/ui";

export type NativeGameDetailsStatusClasses = Readonly<{
  row: string;
  icon: string;
  iconSvg: string;
  label: string;
  problem: string;
  syncing: string;
  activeValue: string;
  appDetailsInnerContainer: string | null;
  playSection: string;
}>;

export type TranslatedGameDetailsStatusClasses = Partial<Record<
  "row"
  | "icon"
  | "iconSvg"
  | "label"
  | "problem"
  | "syncing"
  | "activeValue"
  | "appDetailsInnerContainer"
  | "playSection"
  | "headerBackgroundImage",
  string
>>;

const FALLBACK_CLASSES = {
  row: "sdh-ludusavi-status-row",
  icon: "sdh-ludusavi-status-icon",
  iconSvg: "sdh-ludusavi-status-icon-svg",
  label: "sdh-ludusavi-status-label",
  problem: "sdh-ludusavi-status-problem",
  syncing: "sdh-ludusavi-status-syncing",
  activeValue: "sdh-ludusavi-status-active",
  playSection: "sdh-ludusavi-play-section",
} as const;

const FALLBACK_STYLE_ID = "sdh-ludusavi-status-fallback-style";
const VALID_CSS_CLASS = /^[A-Za-z_-][A-Za-z0-9_-]*$/;

// Zero-specificity (:where) native-matching fallback so Steam CSS and CSS Loader themes always override cleanly.
const FALLBACK_STATUS_CSS = `
:where([data-sdh-ludusavi-status-row="true"]) {
  overflow: hidden;
  text-align: center;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 4px 0;
  scroll-padding-top: 28px;
}
:where([data-sdh-ludusavi-status-row="true"][data-sdh-ludusavi-tone="warning"]),
:where([data-sdh-ludusavi-status-row="true"][data-sdh-ludusavi-tone="error"]) {
  background: hsla(0, 0%, 100%, 0.16);
}
:where([data-sdh-ludusavi-status-icon="true"]) {
  height: 16px;
  display: inline-flex;
  align-items: center;
  margin-inline-end: 8px;
  color: #dcdedf;
}
:where([data-sdh-ludusavi-status-icon="true"] svg) {
  width: 16px;
  height: 16px;
  display: block;
}
@keyframes sdh-ludusavi-native-syncing {
  0%, 100% { color: #dcdedf; }
  50% { color: #3d4450; }
}
:where([data-sdh-ludusavi-status-row="true"][data-sdh-ludusavi-active="true"] [data-sdh-ludusavi-status-icon="true"]) {
  animation: sdh-ludusavi-native-syncing 1.5s infinite;
}
:where([data-sdh-ludusavi-status-label="true"]) {
  font-size: 12px;
  line-height: 12px;
  font-family: "Motiva Sans", Arial, Helvetica, sans-serif;
  letter-spacing: 0.015em;
  text-transform: uppercase;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.7);
}
:where([data-sdh-ludusavi-status-row="true"][data-sdh-ludusavi-active="true"]:not([data-sdh-ludusavi-tone="warning"]):not([data-sdh-ludusavi-tone="error"]) [data-sdh-ludusavi-status-label="true"] > span) {
  color: #1a9fff;
}
`;

let cachedClasses: NativeGameDetailsStatusClasses | null = null;
let translatedClasses: TranslatedGameDetailsStatusClasses | null = null;

function validClass(value: unknown): string | undefined {
  return typeof value === "string" && VALID_CSS_CLASS.test(value) ? value : undefined;
}

function isViteRuntime(): boolean {
  return (globalThis as { __DECKY_ESM__?: unknown }).__DECKY_ESM__ instanceof Map;
}

export function setTranslatedGameDetailsStatusClasses(
  classes: Record<string, unknown> | null | undefined,
): void {
  if (!classes || typeof classes !== "object") {
    translatedClasses = null;
    cachedClasses = null;
    return;
  }
  const next: TranslatedGameDetailsStatusClasses = {};
  for (const key of [
    "row",
    "icon",
    "iconSvg",
    "label",
    "problem",
    "syncing",
    "activeValue",
    "appDetailsInnerContainer",
    "playSection",
    "headerBackgroundImage",
  ] as const) {
    const candidate = validClass(classes[key]);
    if (candidate) next[key] = candidate;
  }
  translatedClasses = Object.keys(next).length > 0 ? next : null;
  cachedClasses = null;
}

export function ensureStatusRowFallbackStyles(doc: Document | null | undefined): void {
  if (!doc?.head || doc.getElementById(FALLBACK_STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = FALLBACK_STYLE_ID;
  style.textContent = FALLBACK_STATUS_CSS;
  doc.head.appendChild(style);
}

export function getNativeHeaderBackgroundClass(): string | null {
  const native = validClass(
    (appDetailsHeaderClasses as Record<string, unknown> | undefined)?.HeaderBackgroundImage,
  );
  return native ?? translatedClasses?.headerBackgroundImage ?? null;
}

export function getNativeGameDetailsStatusClasses(): NativeGameDetailsStatusClasses | null {
  const play = playSectionClasses as Record<string, string | undefined> | undefined;
  const details = appDetailsClasses as Record<string, string | undefined> | undefined;
  const basic = basicAppDetailsSectionStylerClasses as Record<string, string | undefined> | undefined;
  const allowFallback = isViteRuntime() || translatedClasses !== null;

  const pick = (
    nativeValue: string | undefined,
    translatedValue: string | undefined,
    fallbackValue: string,
  ): string | undefined => {
    const resolved = validClass(nativeValue) ?? translatedValue;
    if (resolved) return resolved;
    return allowFallback ? fallbackValue : undefined;
  };

  const row = pick(play?.CloudStatusRow, translatedClasses?.row, FALLBACK_CLASSES.row);
  const icon = pick(play?.CloudStatusIcon, translatedClasses?.icon, FALLBACK_CLASSES.icon);
  const iconSvg = pick(play?.CloudIconSVG, translatedClasses?.iconSvg, FALLBACK_CLASSES.iconSvg);
  const label = pick(play?.CloudStatusLabel, translatedClasses?.label, FALLBACK_CLASSES.label);
  const problem = pick(play?.CloudSyncProblem, translatedClasses?.problem, FALLBACK_CLASSES.problem);
  const syncing = pick(play?.CloudSynching, translatedClasses?.syncing, FALLBACK_CLASSES.syncing);
  const activeValue = pick(play?.CloudStatusUploading, translatedClasses?.activeValue, FALLBACK_CLASSES.activeValue);
  const appDetailsInnerContainer = validClass(details?.InnerContainer) ?? translatedClasses?.appDetailsInnerContainer ?? null;
  const playSection = pick(basic?.PlaySection, translatedClasses?.playSection, FALLBACK_CLASSES.playSection);

  if (!row || !icon || !iconSvg || !label || !problem || !syncing || !activeValue || !playSection) return null;
  if (cachedClasses?.row === row && cachedClasses.icon === icon && cachedClasses.iconSvg === iconSvg
    && cachedClasses.label === label && cachedClasses.problem === problem && cachedClasses.syncing === syncing
    && cachedClasses.activeValue === activeValue
    && cachedClasses.appDetailsInnerContainer === appDetailsInnerContainer
    && cachedClasses.playSection === playSection) return cachedClasses;
  cachedClasses = {
    row, icon, iconSvg, label, problem, syncing, activeValue,
    appDetailsInnerContainer,
    playSection,
  };
  return cachedClasses;
}
