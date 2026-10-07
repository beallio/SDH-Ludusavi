import type { AutoSyncStatusKind } from "../types";

// Game-details rows inherit their canvas, color, and motion from Steam's
// Cloud classes. These compact paths deliberately carry no BrowserView paint
// treatment (fixed size, background colors, or animated fill overlays).
function svg(className: string, content: string): string {
  return `<svg class="${className}" viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false">${content}</svg>`;
}

const cloud = "M4.3 12.6h7.15a2.45 2.45 0 0 0 .44-4.86A3.88 3.88 0 0 0 4.78 6.5 3.05 3.05 0 0 0 4.3 12.6Z";
// The stock Cloud glyph uses the same native 16px canvas but a taller painted
// silhouette. Keep the familiar cloud, arrow, check, and cross in that canvas
// with one static normalization centred on its existing optical centre.
const cloudTransform = "translate(0 -1.84615) scale(1 1.23077)";
const cloudPaint = (cutout: string) => `<path d="${cloud}${cutout}" fill="currentColor" fill-rule="evenodd"/><path d="${cloud}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>`;
const cloudGlyph = (content: string) => `<g transform="${cloudTransform}">${content}</g>`;
const cloudCutout = (cutout: string) => cloudGlyph(cloudPaint(cutout));
const uploadCutout = "M7.05 11.55V8.7L5.8 9.95 4.35 8.5 8 4.85l3.65 3.65-1.45 1.45L8.95 8.7v2.85Z";
const downloadCutout = "M7.05 4.85V7.7L5.8 6.45 4.35 7.9 8 11.55l3.65-3.65-1.45-1.45L8.95 7.7V4.85Z";
const completeCutout = "M4.85 8.25 6.5 6.6l1.35 1.35 2.35-2.35 1.65 1.65-4 4Z";
const unavailableCutout = "M5.2 6.65l1.45-1.45L8 6.55 9.35 5.2l1.45 1.45L9.45 8l1.35 1.35-1.45 1.45L8 9.45l-1.35 1.35-1.45-1.45L6.55 8Z";

/**
 * Returns the static, native-row glyph for a status. Steam owns the outer
 * icon-slot dimensions and any active-row animation.
 */
export function nativeIconSvgForAutoSyncStatus(status: AutoSyncStatusKind, className: string): string {
  if (status === "game_sync_disabled") {
    return svg(className, '<path d="M4 3.25h6.1l1.9 1.9v7.6H4zM6 3.25v3h3" stroke="currentColor" stroke-width="1.45" stroke-linejoin="round"/><path d="m2.7 2.7 10.6 10.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>');
  }
  if (status === "conflict" || status === "conflict_unresolved") {
    return svg(className, '<path d="M8 1.7 14.4 13.9H1.6zM7.2 5.3h1.6v4.1H7.2zM7.2 11.2h1.6v1.45H7.2z" fill="currentColor" fill-rule="evenodd"/><path d="M8 1.7 14.4 13.9H1.6z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>');
  }
  if (status === "has_backup") {
    return svg(className, '<path d="M8 1.15a6.85 6.85 0 1 1 0 13.7 6.85 6.85 0 0 1 0-13.7ZM3.3 7.9l2.1-2.1 1.85 1.85 3.5-3.5 2.1 2.1-5.6 5.6Z" fill="currentColor" fill-rule="evenodd"/>');
  }
  if (status === "error") {
    return svg(className, '<path d="M8 1.15a6.85 6.85 0 1 1 0 13.7 6.85 6.85 0 0 1 0-13.7ZM7.2 4.45h1.6v4.45H7.2zM7.2 11.25h1.6v1.55H7.2z" fill="currentColor" fill-rule="evenodd"/>');
  }
  if (status === "checking") {
    return svg(className, '<path d="M13.35 8A5.35 5.35 0 1 1 8 2.65" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M8 1.55v2.2h2.2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>');
  }
  if (status === "syncthing_pending_upload") {
    return svg(className, cloudGlyph(`${cloudPaint("")}<path d="M10.8 3.45a4.6 4.6 0 0 1 2.1 3.85" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>`));
  }
  if (status === "syncthing_uploading") {
    return svg(className, cloudCutout(uploadCutout));
  }
  if (status === "syncthing_downloading") {
    return svg(className, cloudCutout(downloadCutout));
  }
  if (status === "syncthing_complete") {
    return svg(className, cloudCutout(completeCutout));
  }
  if (status === "syncthing_unavailable" || status === "syncthing_folder_not_found"
    || status === "syncthing_no_peers" || status === "syncthing_upload_incomplete") {
    return svg(className, cloudCutout(unavailableCutout));
  }
  if (status === "backing_up" || status === "restoring") {
    const direction = status === "restoring" ? ' transform="rotate(180 8 8)"' : "";
    return svg(className, `<g${direction}><path d="M13.25 8a5.25 5.25 0 1 1-1.6-3.76" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/><path d="M10.25 2.8h2.95v2.95M8 11.5V5.2m0 0L5.85 7.35M8 5.2l2.15 2.15" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></g>`);
  }
  return svg(className, '<circle cx="8" cy="8" r="6.1" stroke="currentColor" stroke-width="1.5"/><path d="M5.9 5.8a2.1 2.1 0 0 1 4.2 0c0 1.2-1.5 1.55-2.1 2.45v.65" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="11.3" r=".8" fill="currentColor"/>');
}
