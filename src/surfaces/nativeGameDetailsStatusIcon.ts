import type { AutoSyncStatusKind } from "../types";

// Game-details rows inherit their canvas, color, and motion from Steam's
// Cloud classes. These compact paths deliberately carry no BrowserView paint
// treatment (fixed size, background colors, or animated fill overlays).
function svg(className: string, content: string, viewBoxSize = 16): string {
  return `<svg class="${className}" viewBox="0 0 ${viewBoxSize} ${viewBoxSize}" fill="none" aria-hidden="true" focusable="false">${content}</svg>`;
}

// Keep the native cloud's 36-unit geometry. The entire canvas scales uniformly
// into Steam's icon slot; neither the cloud nor its cutouts need a stretch.
const cloud = "M25.2377 7.0939C26.902 8.83356 27.8828 11.1153 28 13.52C29.998 14.2303 31.6809 15.6232 32.7522 17.4532C33.8234 19.2831 34.2142 21.4325 33.8555 23.5224C33.4968 25.6122 32.4118 27.5084 30.7917 28.8764C29.1716 30.2444 27.1205 30.9965 25 31H11C8.87962 30.9965 6.82852 30.2444 5.20842 28.8764C3.58833 27.5084 2.50327 25.6122 2.1446 23.5224C1.78593 21.4325 2.17666 19.2831 3.24792 17.4532C4.31917 15.6232 6.00213 14.2303 8.00005 13.52C8.11845 11.109 9.10495 8.82222 10.7775 7.08168C12.45 5.34114 14.6957 4.26433 17.1 4.04999H18.0201H18.9401C21.3372 4.27345 23.5733 5.35425 25.2377 7.0939Z";
const cloudPaint = (cutout: string) => `<path d="${cloud}${cutout}" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd"/>`;
const cloudCutout = (className: string, cutout: string) => svg(className, cloudPaint(cutout), 36);
const uploadCutout = "M16 26V18.8L12.4 22.4 9.6 19.6 18 11.2l8.4 8.4-2.8 2.8-3.6-3.6V26Z";
const downloadCutout = "M16 12.5V19.7L12.4 16.1 9.6 18.9 18 27.3l8.4-8.4-2.8-2.8-3.6 3.6V12.5Z";
const completeCutout = "M10 19.6L15.41 25L25.03 15.38L22.64 13L15.41 20.23L12.39 17.21L10 19.6Z";
const unavailableCutout = "M11.7 15l3.3-3.3 3 3.1 3-3.1 3.3 3.3-3.1 3 3.1 3-3.3 3.3-3-3.1-3 3.1-3.3-3.3 3.1-3Z";
const clockCutout = "M18 13a7 7 0 1 1 0 14 7 7 0 0 1 0-14Z";
const localCircle = "M8 1.15a6.85 6.85 0 1 1 0 13.7 6.85 6.85 0 0 1 0-13.7Z";
const localArrow = "M7 11.7V7.3L5.35 8.95 3.95 7.55 8 3.5l4.05 4.05-1.4 1.4L9 7.3v4.4Z";

/**
 * Returns the static, native-row glyph for a status. Steam owns the outer
 * icon-slot dimensions and any active-row animation.
 */
export function nativeIconSvgForAutoSyncStatus(status: AutoSyncStatusKind, className: string): string {
  if (status === "game_sync_disabled") {
    return svg(className, '<circle cx="8" cy="8" r="6.05" stroke="currentColor" stroke-width="1.7"/><path d="m3.7 3.7 8.6 8.6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>');
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
    return svg(className, '<path d="M6.75 1.6a5.15 5.15 0 1 1 0 10.3 5.15 5.15 0 0 1 0-10.3ZM6.75 3.7a3.05 3.05 0 1 1 0 6.1 3.05 3.05 0 0 1 0-6.1Z" fill="currentColor" fill-rule="evenodd"/><path d="m10.5 10.5 3.75 3.75" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/>');
  }
  if (status === "syncthing_pending_upload") {
    return svg(className, `${cloudPaint(clockCutout)}<path d="M18 15.5V20l3.5 2.1" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/>`, 36);
  }
  if (status === "syncthing_uploading") {
    return cloudCutout(className, uploadCutout);
  }
  if (status === "syncthing_downloading") {
    return cloudCutout(className, downloadCutout);
  }
  if (status === "syncthing_complete") {
    return cloudCutout(className, completeCutout);
  }
  if (status === "syncthing_unavailable" || status === "syncthing_folder_not_found"
    || status === "syncthing_no_peers" || status === "syncthing_upload_incomplete") {
    return cloudCutout(className, unavailableCutout);
  }
  if (status === "backing_up" || status === "restoring") {
    const direction = status === "restoring" ? ' transform="rotate(180 8 8)"' : "";
    return svg(className, `<g${direction}><path d="${localCircle}${localArrow}" fill="currentColor" fill-rule="evenodd"/></g>`);
  }
  return svg(className, '<circle cx="8" cy="8" r="6.1" stroke="currentColor" stroke-width="1.5"/><path d="M5.9 5.8a2.1 2.1 0 0 1 4.2 0c0 1.2-1.5 1.55-2.1 2.45v.65" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="11.3" r=".8" fill="currentColor"/>');
}
