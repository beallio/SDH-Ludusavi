import { IoMdCloudDownload, IoMdCloudUpload, IoMdCloudDone } from "react-icons/io";
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
  } else if (status === "syncthing_uploading" || status === "syncthing_pending_upload") {
    icon = IoMdCloudUpload;
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
  if (
    status === "syncthing_downloading" ||
    status === "syncthing_uploading" ||
    status === "syncthing_pending_upload" ||
    status === "syncthing_complete"
  ) {
    return getSerializedIcon(status);
  }

  const rotation = status === "restoring" ? ' style="transform: rotate(180deg); transform-origin: 50% 50%;"' : "";
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
</style>
</head>
<body>
<div class="bar">
  <div class="text"><span class="icon${state.status === "checking" ? " icon-spin" : ""}">${iconSvgForAutoSyncStatus(state.status)}</span>${autoSyncStatusText[state.status]}</div>
</div>
</body>
</html>`;
}