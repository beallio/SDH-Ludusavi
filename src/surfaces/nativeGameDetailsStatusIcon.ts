import type { AutoSyncStatusKind } from "../types";

// Game-details rows inherit their canvas, color, and motion from Steam's
// Cloud classes. These compact paths deliberately carry no BrowserView paint
// treatment (fixed size, background colors, or animated fill overlays).
function svg(className: string, content: string): string {
  return `<svg class="${className}" viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false">${content}</svg>`;
}

const cloud = "M4.3 12.6h7.15a2.45 2.45 0 0 0 .44-4.86A3.88 3.88 0 0 0 4.78 6.5 3.05 3.05 0 0 0 4.3 12.6Z";

/**
 * Returns the static, native-row glyph for a status. Steam owns the outer
 * icon-slot dimensions and any active-row animation.
 */
export function nativeIconSvgForAutoSyncStatus(status: AutoSyncStatusKind, className: string): string {
  if (status === "game_sync_disabled") {
    return svg(className, '<path d="M4 3.25h6.1l1.9 1.9v7.6H4zM6 3.25v3h3" stroke="currentColor" stroke-width="1.45" stroke-linejoin="round"/><path d="m2.7 2.7 10.6 10.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>');
  }
  if (status === "conflict" || status === "conflict_unresolved") {
    return svg(className, '<path d="M8 1.2 15 14.2H1zM7.2 5.3h1.6v4.1H7.2zM7.2 11.2h1.6v1.45H7.2z" fill="currentColor" fill-rule="evenodd"/>');
  }
  if (status === "has_backup") {
    return svg(className, '<circle cx="8" cy="8" r="6.2" stroke="currentColor" stroke-width="1.6"/><path d="m4.9 8 2 2.05 4.25-4.35" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>');
  }
  if (status === "error") {
    return svg(className, '<path d="M8 1.15a6.85 6.85 0 1 1 0 13.7 6.85 6.85 0 0 1 0-13.7ZM7.2 4.45h1.6v4.45H7.2zM7.2 11.25h1.6v1.55H7.2z" fill="currentColor" fill-rule="evenodd"/>');
  }
  if (status === "checking") {
    return svg(className, '<path d="M13.35 8A5.35 5.35 0 1 1 8 2.65" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M8 1.55v2.2h2.2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>');
  }
  if (status === "syncthing_pending_upload") {
    return svg(className, `<path d="${cloud}" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/><path d="M10.8 3.45a4.6 4.6 0 0 1 2.1 3.85" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>`);
  }
  if (status === "syncthing_uploading") {
    return svg(className, `<path d="${cloud}" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/><path d="M8 11.25V5.55m0 0L5.9 7.65M8 5.55l2.1 2.1" stroke="currentColor" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round"/>`);
  }
  if (status === "syncthing_downloading") {
    return svg(className, `<path d="${cloud}" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/><path d="M8 5.55v5.7m0 0 2.1-2.1M8 11.25l-2.1-2.1" stroke="currentColor" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round"/>`);
  }
  if (status === "syncthing_complete") {
    return svg(className, `<path d="${cloud}" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/><path d="m5.9 9.2 1.45 1.45 3.15-3.25" stroke="currentColor" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round"/>`);
  }
  if (status === "syncthing_unavailable" || status === "syncthing_folder_not_found"
    || status === "syncthing_no_peers" || status === "syncthing_upload_incomplete") {
    return svg(className, `<path d="${cloud}" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/><path d="m6.3 7.25 3.4 3.4m0-3.4-3.4 3.4" stroke="currentColor" stroke-width="1.55" stroke-linecap="round"/>`);
  }
  if (status === "backing_up" || status === "restoring") {
    const direction = status === "restoring" ? ' transform="rotate(180 8 8)"' : "";
    return svg(className, `<path d="M13.25 8a5.25 5.25 0 1 1-1.6-3.76" stroke="currentColor" stroke-width="1.55" stroke-linecap="round"/><path d="M10.25 2.8h2.95v2.95M8 11.5V5.2m0 0L5.85 7.35M8 5.2l2.15 2.15"${direction} stroke="currentColor" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round"/>`);
  }
  return svg(className, '<path d="M4.1 2.9h6.1l1.7 1.7v8.5H4.1zM6 2.9v3h3M6.4 10.25h3.2M8 7.75v1.35" stroke="currentColor" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round"/>');
}
