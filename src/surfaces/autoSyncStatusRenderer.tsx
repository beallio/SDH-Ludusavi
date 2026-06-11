import { IoMdCloudDownload, IoMdCloudDone } from "react-icons/io";
import type { AutoSyncStatusKind, AutoSyncStatusState } from "../types";
import { log } from "../utils/logging";

export const autoSyncStatusText: Record<AutoSyncStatusKind, string> = {
  checking: "VERIFYING GAME SAVE",
  backing_up: "BACKING UP LOCAL SAVE",
  restoring: "RESTORING BACKUP SAVE",
  conflict: "SAVE CONFLICT",
  has_backup: "GAME SAVE UP TO DATE",
  unknown: "UNKNOWN",
  error: "UNABLE TO SYNC",
  syncthing_pending_upload: "SYNCTHING PREPARING",
  syncthing_downloading: "SYNCTHING DOWNLOADING",
  syncthing_uploading: "SYNCTHING UPLOADING",
  syncthing_complete: "SYNCTHING COMPLETE",
  syncthing_unavailable: "LOCAL BACKUP SAVED - SYNCTHING UNAVAILABLE",
  syncthing_folder_not_found: "LOCAL BACKUP SAVED - PATH NOT SHARED",
  syncthing_no_peers: "LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE"
};
export function isLudusaviRunningStatus(status: AutoSyncStatusKind): boolean {
  return status === "checking" || status === "backing_up" || status === "restoring";
}

export function isSyncthingActiveStatus(status: AutoSyncStatusKind): boolean {
  return (
    status === "syncthing_pending_upload" ||
    status === "syncthing_downloading" ||
    status === "syncthing_uploading"
  );
}

export function shouldAutoHideStatus(status: AutoSyncStatusKind): boolean {
  return !isSyncthingActiveStatus(status);
}

const svgAttributeMapping: Record<string, string> = {
  fillRule: "fill-rule",
  clipRule: "clip-rule",
  strokeWidth: "stroke-width",
  strokeLinecap: "stroke-linecap",
  strokeLinejoin: "stroke-linejoin",
};

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function serializeSvgNode(node: any): string {
  if (!node || typeof node !== "object") {
    return "";
  }
  const tag = node.type;
  if (tag !== "path" && tag !== "g") {
    log("warning", `Unsupported SVG tag: ${tag}`, "autosync_status");
    return "";
  }

  const props = node.props || {};
  let attributes = "";
  const allowedAttributes = [
    "d",
    "fill",
    "fillRule",
    "clipRule",
    "stroke",
    "strokeWidth",
    "strokeLinecap",
    "strokeLinejoin",
    "opacity",
    "transform",
  ];

  for (const attr of allowedAttributes) {
    if (props[attr] !== undefined && props[attr] !== null) {
      const svgAttr = svgAttributeMapping[attr] || attr;
      attributes += ` ${svgAttr}="${escapeHtml(String(props[attr]))}"`;
    }
  }

  let childrenMarkup = "";
  if (props.children) {
    if (Array.isArray(props.children)) {
      childrenMarkup = props.children.map(serializeSvgNode).join("");
    } else {
      childrenMarkup = serializeSvgNode(props.children);
    }
  }

  return `<${tag}${attributes}>${childrenMarkup}</${tag}>`;
}

function serializeIcon(Icon: any): string {
  try {
    const element = Icon({
      size: 18,
      "aria-hidden": true,
      focusable: false,
    });
    if (!element || typeof element !== "object" || !element.props) {
      return "";
    }
    const viewBox = element.props.attr?.viewBox || "0 0 512 512";
    let childrenMarkup = "";
    const children = element.props.children;
    if (children) {
      if (Array.isArray(children)) {
        childrenMarkup = children.map(serializeSvgNode).join("");
      } else {
        childrenMarkup = serializeSvgNode(children);
      }
    }
    return `<svg viewBox="${escapeHtml(viewBox)}" width="18" height="18" fill="currentColor" aria-hidden="true" focusable="false">${childrenMarkup}</svg>`;
  } catch (err) {
    log("warning", `Failed to serialize icon: ${err}`, "autosync_status");
    return '<svg viewBox="0 0 512 512" width="18" height="18" fill="currentColor" aria-hidden="true" focusable="false"></svg>';
  }
}

const serializedIconsCache: Record<string, string> = {};

function getSerializedIcon(status: AutoSyncStatusKind): string {
  if (serializedIconsCache[status]) {
    return serializedIconsCache[status];
  }

  let icon: any;
  if (status === "syncthing_downloading") {
    icon = IoMdCloudDownload;
  } else if (status === "syncthing_complete") {
    icon = IoMdCloudDone;
  } else {
    return "";
  }

  const serialized = serializeIcon(icon);
  serializedIconsCache[status] = serialized;
  return serialized;
}

export function iconSvgForAutoSyncStatus(status: AutoSyncStatusKind): string {
  if (status === "has_backup") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M6 10.2 8.5 12.7 14.2 7" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  if (status === "unknown") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M6 5h7l2 2v8H6z" fill="#0b151f"/><path d="M8 5h5v4H8z" fill="currentColor"/><path d="M8 12h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
  }
  if (status === "error") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="currentColor"/><path d="M10 5.2v6.4" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/><circle cx="10" cy="15" r="1.2" fill="#0b151f"/></svg>';
  }
  if (status === "checking") {
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="3" opacity="0.8"/><path d="M10 2a8 8 0 0 1 8 8" fill="none" stroke="#0b151f" stroke-width="3" stroke-linecap="round"/></svg>';
  }
  if (status === "syncthing_pending_upload") {
    return '<svg viewBox="0 0 512 512" width="18" height="18" aria-hidden="true"><g class="spinner-ring"><path d="M448 256c0-106-86-192-192-192S64 150 64 256s86 192 192 192 192-86 192-192z" fill="none" stroke="currentColor" stroke-miterlimit="10" stroke-width="32" opacity="0.8"/><path d="M256 64a192 192 0 0 1 192 192" fill="none" stroke="#0b151f" stroke-width="32" stroke-linecap="round"/></g><path d="M333.88 240.59a8 8 0 0 1-6.66-6.66C320.68 192.78 290.82 168 256 168c-32.37 0-53.93 21.22-62.48 43.58a7.92 7.92 0 0 1-6.16 5c-27.67 4.35-50.82 22.56-51.35 54.3-.52 31.53 25.51 57.11 57 57.11H326c27.5 0 50-13.72 50-44 0-27.22-22-40.41-42.12-43.4z" fill="currentColor"/></svg>';
  }
  if (status === "syncthing_uploading") {
    return '<svg viewBox="0 0 512 512" width="18" height="18" aria-hidden="true"><defs><clipPath id="upload-arrow-clip"><path d="M288 276v76h-64v-76h-68l100-100 100 100h-68z"/></clipPath></defs><path d="M403.002 217.001C388.998 148.002 328.998 96 256 96c-57.998 0-107.998 32.998-132.998 81.001C63.002 183.002 16 233.998 16 296c0 65.996 53.999 120 120 120h260c55 0 100-45 100-100 0-52.998-40.996-96.001-92.998-98.999zM288 276v76h-64v-76h-68l100-100 100 100h-68z" fill="currentColor"/><rect class="upload-arrow-fill" x="156" y="176" width="200" height="176" fill="#f8fafc" clip-path="url(#upload-arrow-clip)"/></svg>';
  }
  if (
    status === "syncthing_downloading" ||
    status === "syncthing_complete"
  ) {
    return getSerializedIcon(status);
  }

  if (status === "backing_up" || status === "restoring") {
    const rotation =
      status === "restoring"
        ? ' style="transform: rotate(180deg); transform-origin: 50% 50%;"'
        : "";
    return `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"${rotation}><defs><clipPath id="backup-arrow-clip"><path d="M11.6 15.2h-3.2v-4.8H5.9L10 4.8l4.1 5.6h-2.5z"/></clipPath></defs><path d="M10 1.2a8.8 8.8 0 1 0 0 17.6 8.8 8.8 0 0 0 0-17.6zM11.6 15.2h-3.2v-4.8H5.9L10 4.8l4.1 5.6h-2.5z" fill="currentColor" fill-rule="evenodd"/><rect class="backup-arrow-fill" x="5.5" y="4.8" width="9" height="10.4" fill="#f8fafc" clip-path="url(#backup-arrow-clip)"/></svg>`;
  }

  const rotation = (status as string) === "restoring" ? ' style="transform: rotate(180deg); transform-origin: 50% 50%;"' : "";
  return `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"${rotation}><circle cx="10" cy="10" r="8.8" fill="currentColor"/><path d="M10 5.3v8.3" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/><path d="M6.8 8.4 10 5.2l3.2 3.2" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

export function renderAutoSyncStatusHtml(state: AutoSyncStatusState) {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; }
body {
  color: #f8fafc;
  font-family: "Motiva Sans", Arial, sans-serif;
  font-size: 13px;
  font-weight: 800;
  text-transform: uppercase;
}
.bar {
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(0, 0, 0, 0.34);
  border-top: 1px solid rgba(255, 255, 255, 0.10);
  padding: 0 18px;
  box-sizing: border-box;
}
.text { display: flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-width: 245px; }
.icon { width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; color: ${state.status === "error" ? "#ef4444" : state.status === "unknown" ? "#f59e0b" : state.status === "syncthing_unavailable" || state.status === "syncthing_folder_not_found" || state.status === "syncthing_no_peers" ? "#f59e0b" : "#1a9fff"}; }
@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
.icon-spin svg {
  animation: spin 1s linear infinite;
  transform-origin: 50% 50%;
}
.icon-spin-ring .spinner-ring {
  animation: spin 1s linear infinite;
  transform-origin: 256px 256px;
}
@keyframes arrow-fill-up {
  0% { transform: translateY(176px); }
  75% { transform: translateY(0); }
  100% { transform: translateY(0); }
}
.upload-arrow-fill {
  animation: arrow-fill-up 1.6s ease-out infinite;
}
@keyframes backup-arrow-fill-up {
  0% { transform: translateY(10.4px); }
  75% { transform: translateY(0); }
  100% { transform: translateY(0); }
}
.backup-arrow-fill {
  animation: backup-arrow-fill-up 1.6s ease-out infinite;
}
</style>
</head>
<body>
<div class="bar">
  <div class="text"><span class="icon${state.status === "checking" ? " icon-spin" : state.status === "syncthing_pending_upload" ? " icon-spin-ring" : ""}">${iconSvgForAutoSyncStatus(state.status)}</span>${autoSyncStatusText[state.status]}</div>
</div>
</body>
</html>`;
}