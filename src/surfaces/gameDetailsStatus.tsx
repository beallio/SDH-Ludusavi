import { routerHook } from "@decky/api";
import { cloneElement, createElement, isValidElement, useEffect, useState, useSyncExternalStore, type ReactElement } from "react";

import type { LudusaviStateStore } from "../state/ludusaviState";
import { getAppDetailsForAppID, getAppOverviewForAppID, subscribeToAppDetails } from "../utils/steamRuntime";
import { selectGameDetailsStatus, getSteamCloudEligibility } from "./gameDetailsStatusModel";
import type { createAutoSyncStatusSurface } from "./autoSyncStatusSurface";

const GAME_DETAILS_ROUTE = "/library/app/:appid";

type DetailsStatusSurface = Pick<ReturnType<typeof createAutoSyncStatusSurface>, "registerDetailsOwner">;
type RouteRecord = Record<string, unknown>;

export function createGameDetailsStatusSurface(store: LudusaviStateStore, statusSurface: DetailsStatusSurface) {
  let disposed = false;
  const patch = (route: unknown) => {
    const record = asRecord(route);
    const children = asRecord(record?.children);
    const renderFunc = children?.renderFunc;
    if (!record || !children || typeof renderFunc !== "function") return route as any;

    return {
      ...record,
      children: {
        ...children,
        renderFunc(...args: unknown[]) {
          const rendered = renderFunc(...args);
          if (!isValidElement(rendered) || disposed) return rendered;
          const providerProps = asRecord(rendered.props);
          const header = providerProps?.value;
          if (typeof header !== "function") return rendered;
          const appID = routeAppID(args) ?? routeAppID([record]);
          if (!appID) return rendered;
          const WrappedHeader = (headerProps: unknown) => createElement(
            GameDetailsStatusHeader,
            { appID, header: header as (props: unknown) => unknown, headerProps, store, statusSurface },
          );
          return cloneElement(rendered as ReactElement<any>, { ...providerProps, value: WrappedHeader } as any);
        },
      },
    };
  };

  const installedPatch = routerHook.addPatch(GAME_DETAILS_ROUTE, patch as any);
  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      routerHook.removePatch(GAME_DETAILS_ROUTE, installedPatch);
    },
  };
}

function GameDetailsStatusHeader({ appID, header, headerProps, store, statusSurface }: {
  appID: string;
  header: (props: unknown) => unknown;
  headerProps: unknown;
  store: LudusaviStateStore;
  statusSurface: DetailsStatusSurface;
}) {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [details, setDetails] = useState<unknown>(() => getAppDetailsForAppID(appID));
  useEffect(() => {
    setDetails(getAppDetailsForAppID(appID));
    return subscribeToAppDetails(appID, setDetails);
  }, [appID]);

  const overview = getAppOverviewForAppID(appID);
  const gameName = typeof overview?.m_strDisplayName === "string" ? overview.m_strDisplayName : "";
  const eligibility = getSteamCloudEligibility(appID, details);
  const model = selectGameDetailsStatus({
    snapshot,
    appID,
    gameName,
    canonicalGameName: gameName ? store.resolveCanonicalGameName(gameName, appID) : null,
    eligibility,
  });
  const nativeHeader = header(headerProps);
  return createElement(
    "div",
    { style: { display: "contents" } },
    nativeHeader as any,
    model.showRow ? createElement(GameDetailsStatusRow, { appID, model, statusSurface }) : null,
  );
}

function GameDetailsStatusRow({ appID, model, statusSurface }: {
  appID: string;
  model: ReturnType<typeof selectGameDetailsStatus>;
  statusSurface: DetailsStatusSurface;
}) {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const layoutValid = Boolean(element && element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height >= 20);
  useEffect(() => {
    if (!model.canOwnStatusArea || !layoutValid) return;
    return statusSurface.registerDetailsOwner({ appID, visible: true, layoutValid: true });
  }, [appID, layoutValid, model.canOwnStatusArea, statusSurface]);

  return createElement("div", {
    ref: setElement,
    role: "status",
    "aria-label": model.description,
    style: {
      width: "100%", minHeight: 30, boxSizing: "border-box", display: "flex", alignItems: "center",
      gap: 8, padding: "4px 12px", color: toneColor(model.tone), background: "rgba(0, 0, 0, 0.18)",
      fontFamily: "Motiva Sans, Arial, sans-serif", fontSize: 13, fontWeight: 700,
      overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis",
    },
  }, createElement("span", { style: { overflow: "hidden", textOverflow: "ellipsis" } }, model.label));
}

function toneColor(tone: ReturnType<typeof selectGameDetailsStatus>["tone"]) {
  if (tone === "error") return "#ef4444";
  if (tone === "warning") return "#f59e0b";
  if (tone === "success") return "#1a9fff";
  return "#d6e6f5";
}

function routeAppID(values: unknown[]): string | null {
  for (const value of values) {
    const record = asRecord(value);
    const params = asRecord(record?.params);
    const candidate = params?.appid ?? record?.appid;
    if (typeof candidate === "string" || typeof candidate === "number") return String(candidate);
  }
  return null;
}

function asRecord(value: unknown): RouteRecord | null {
  return typeof value === "object" && value !== null ? value as RouteRecord : null;
}
