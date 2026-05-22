import { Router } from "@decky/ui";
import { GameStatus, RunningSession } from "../types";
import { log } from "./logging";

let lastSteamUiGameContext: RunningSession | null = null;
let lastSteamUiGameContextCapturedAt = 0;
const STEAM_UI_GAME_CONTEXT_TTL_MS = 10_000;
const QUICK_ACCESS_TOP_EPSILON_PX = 1;

const STATUS_STRIP_HEIGHT_RATIO = 0.0475;
const STEAM_BOTTOM_MENU_HEIGHT_RATIO = 0.02625;

/** Normalize a game name for fuzzy matching, mirroring backend _normalize. */
export function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9.-]+/g, " ").trim();
}

export const getInstalledAppIdsString = async (): Promise<string | undefined> => {
  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    if (!steamClient?.Apps?.GetInstalledApps) {
      return undefined;
    }
    const appsResult = steamClient.Apps.GetInstalledApps();
    const apps = appsResult instanceof Promise ? await appsResult : appsResult;
    
    if (!Array.isArray(apps)) return undefined;
    
    const appIds = apps
      .map((app: any) => parseInt(app?.appid ?? app?.nAppID ?? app?.unAppID ?? app?.id, 10))
      .filter((id: number) => !isNaN(id));
      
    appIds.sort((a, b) => a - b);
    return appIds.join(",");
  } catch (err) {
    return undefined;
  }
};

export const sessionFromAppOverview = (app: any): RunningSession | null => {
  const appID = app?.appid ?? app?.m_unAppID ?? app?.nAppID ?? app?.m_nAppID ?? null;
  const name =
    app?.display_name ??
    app?.m_strDisplayName ??
    app?.strAppName ??
    app?.name ??
    app?.title ??
    "";
  if (!appID || !name) {
    return null;
  }
  return { appID: String(appID), name: String(name) };
};

export function getMainRunningSession(): RunningSession | null {
  const session = sessionFromAppOverview((Router as any).MainRunningApp);
  return session ? { ...session, source: "running" } : null;
}

export function getMainSteamWindow(): Window | null {
  return (Router as any).WindowStore?.GamepadUIMainWindowInstance?.BrowserWindow ?? null;
}

export function getSteamAppNameFromStores(appID: string): string | null {
  const numericAppID = Number(appID);
  const appStore = (globalThis as any).appStore ?? (window as any).appStore;
  const overview = Number.isFinite(numericAppID)
    ? appStore?.GetAppOverviewByAppID?.(numericAppID)
    : null;
  const overviewSession = sessionFromAppOverview(overview);
  if (overviewSession?.name) {
    return overviewSession.name;
  }

  const collectionApps = (globalThis as any).collectionStore?.allGamesCollection?.allApps
    ?? (window as any).collectionStore?.allGamesCollection?.allApps;
  if (collectionApps && typeof collectionApps.forEach === "function") {
    let foundName: string | null = null;
    collectionApps.forEach((app: any) => {
      if (foundName) {
        return;
      }
      const candidateID = app?.appid ?? app?.nAppID ?? app?.m_unAppID;
      if (String(candidateID) === appID) {
        foundName = app?.display_name ?? app?.strAppName ?? app?.m_strDisplayName ?? null;
      }
    });
    if (foundName) {
      return foundName;
    }
  }

  return null;
}

export function sessionFromRoutePath(path: string): RunningSession | null {
  const match = path.match(/(?:\/routes)?\/library\/app\/(\d+)/);
  const appID = match?.[1];
  if (!appID) {
    return null;
  }
  const name = getSteamAppNameFromStores(appID) ?? "";
  return { appID, name, source: "route" };
}

export function getRouteSteamGameSession(): RunningSession | null {
  const mainWindow = getMainSteamWindow();
  return (
    sessionFromRoutePath(mainWindow?.location?.pathname ?? "") ??
    sessionFromRoutePath(mainWindow?.location?.hash ?? "") ??
    sessionFromRoutePath(window.location.pathname) ??
    sessionFromRoutePath(window.location.hash)
  );
}

export function sessionFromSteamUiCandidate(candidate: any): RunningSession | null {
  if (!candidate) {
    return null;
  }

  const direct = sessionFromAppOverview(candidate);
  if (direct) {
    return direct;
  }

  const nestedCandidates = [
    candidate.app,
    candidate.overview,
    candidate.game,
    candidate.props?.app,
    candidate.props?.overview,
    candidate.props?.game,
    candidate.pendingProps?.app,
    candidate.pendingProps?.overview,
    candidate.pendingProps?.game,
    candidate.memoizedProps?.app,
    candidate.memoizedProps?.overview,
    candidate.memoizedProps?.game,
    candidate.stateNode?.props?.app,
    candidate.stateNode?.props?.overview,
    candidate.stateNode?.props?.game
  ];

  for (const nested of nestedCandidates) {
    const session = sessionFromAppOverview(nested);
    if (session) {
      return session;
    }
  }

  return null;
}

export function getSteamUiReactPropCandidates(element: Element | null): any[] {
  if (!element) {
    return [];
  }

  const candidates: any[] = [];
  for (const key of Object.keys(element as any)) {
    if (key.startsWith("__reactProps$")) {
      candidates.push((element as any)[key]);
    }
    if (key.startsWith("__reactFiber$") || key.startsWith("__reactInternalInstance$")) {
      let fiber = (element as any)[key];
      for (let depth = 0; fiber && depth < 12; depth += 1) {
        candidates.push(fiber.pendingProps, fiber.memoizedProps, fiber.stateNode?.props);
        fiber = fiber.return;
      }
    }
  }
  return candidates.filter(Boolean);
}

export function getFocusedSteamGameSession(): RunningSession | null {
  const mainWindow = getMainSteamWindow();
  const doc = mainWindow?.document ?? document;
  const focusedElements = [
    doc.activeElement,
    doc.querySelector(".gpfocus, .gpfocuswithin, :focus"),
    ...Array.from(doc.querySelectorAll(":hover")).reverse()
  ];

  for (const element of focusedElements) {
    for (const candidate of getSteamUiReactPropCandidates(element)) {
      const session = sessionFromSteamUiCandidate(candidate);
      if (session) {
        return { ...session, source: "focused" };
      }
    }
  }

  return null;
}

export function captureSteamUiGameContext(): RunningSession | null {
  const session = getFocusedSteamGameSession() ?? getRouteSteamGameSession();
  if (session) {
    if (
      lastSteamUiGameContext?.appID !== session.appID ||
      lastSteamUiGameContext?.name !== session.name ||
      lastSteamUiGameContext?.source !== session.source
    ) {
      log(
        "debug",
        `QAM context captured: ${describeSteamGameSession(session)}`,
        "qam_context",
        session.name
      );
    }
    lastSteamUiGameContext = session;
    lastSteamUiGameContextCapturedAt = Date.now();
  }
  return session;
}

export function getRecentSteamUiGameContext(): RunningSession | null {
  if (!lastSteamUiGameContext) {
    return null;
  }
  if (Date.now() - lastSteamUiGameContextCapturedAt > STEAM_UI_GAME_CONTEXT_TTL_MS) {
    return null;
  }
  return { ...lastSteamUiGameContext, source: "cached" };
}

export function getPreferredSteamGameSession(): RunningSession | null {
  return (
    captureSteamUiGameContext() ??
    getRecentSteamUiGameContext() ??
    getMainRunningSession()
  );
}

export function getGameSteamAppID(game: GameStatus): string | null {
  const steamID = game.steam_id;
  if (steamID === undefined || steamID === null || steamID === "") {
    return null;
  }
  return String(steamID);
}

export function findAliasTargetForSession(
  session: RunningSession,
  currentAliases: Record<string, string>
): string | null {
  const normalizedSessionName = normalize(session.name);
  for (const [alias, target] of Object.entries(currentAliases)) {
    if (normalize(alias) === normalizedSessionName || normalize(target) === normalizedSessionName) {
      return target;
    }
  }
  return null;
}

export function findGameForRunningSession(
  currentGames: GameStatus[],
  session: RunningSession,
  currentAliases: Record<string, string>
): { game: GameStatus; reason: "steam_id" | "name" | "alias" } | null {
  const appIDMatch = currentGames.find((game) => {
    const gameAppID = getGameSteamAppID(game);
    return gameAppID === session.appID;
  });
  if (appIDMatch) {
    return { game: appIDMatch, reason: "steam_id" };
  }

  if (!session.name) {
    return null;
  }

  const nameMatch = currentGames.find((game) => normalize(game.name) === normalize(session.name));
  if (nameMatch) {
    return { game: nameMatch, reason: "name" };
  }

  const aliasTarget = findAliasTargetForSession(session, currentAliases);
  if (!aliasTarget) {
    return null;
  }

  const aliasMatch = currentGames.find((game) => normalize(game.name) === normalize(aliasTarget));
  if (aliasMatch) {
    return { game: aliasMatch, reason: "alias" };
  }

  return null;
}

export function describeSteamGameSession(session: RunningSession): string {
  return `source=${session.source ?? "unknown"} appID=${session.appID || "unknown"} name=${session.name || "unknown"} normalized=${normalize(session.name || "")}`;
}

export function logCurrentGameSelection(
  session: RunningSession,
  runningGame: GameStatus,
  reason: string,
  currentGames: GameStatus[],
  currentAliases: Record<string, string>
) {
  log(
    "info",
    `QAM current game selected: context=${describeSteamGameSession(session)} match=${runningGame.name} reason=${reason} games=${currentGames.length} aliasKeys=${Object.keys(currentAliases).length}`,
    "qam_context",
    runningGame.name
  );
}

export function logCurrentGameNoMatch(
  session: RunningSession | null,
  currentGames: GameStatus[],
  currentAliases: Record<string, string>
) {
  log(
    session ? "warning" : "debug",
    `QAM current game not selected: context=${session ? describeSteamGameSession(session) : "none"} games=${currentGames.length} aliasKeys=${Object.keys(currentAliases).length}`,
    "qam_context",
    session?.name
  );
}

export function findScrollableParent(element: HTMLElement | null): HTMLElement | null {
  let current = element?.parentElement ?? null;
  while (current) {
    const style = window.getComputedStyle(current);
    if (
      ["auto", "scroll", "overlay"].includes(style.overflowY) &&
      current.scrollHeight > current.clientHeight
    ) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

export function resetQuickAccessScroll(container: HTMLElement | null, reason = "qam_open") {
  window.requestAnimationFrame(() => {
    const scrollable = findScrollableParent(container);
    const beforeTop = scrollable?.scrollTop ?? -1;
    const beforeContainerTop = container?.getBoundingClientRect?.().top ?? -1;
    if (scrollable) {
      scrollable.scrollTo({ top: 0, left: 0, behavior: "auto" });
    }
    if (container) {
      container.scrollIntoView({ block: "start" });
    }
    const afterTop = scrollable?.scrollTop ?? -1;
    const containerTop = container?.getBoundingClientRect?.().top ?? -1;
    if (
      beforeTop === afterTop &&
      Math.abs(beforeContainerTop - containerTop) <= QUICK_ACCESS_TOP_EPSILON_PX
    ) {
      return;
    }
    const scrollableTag = scrollable
      ? `${scrollable.tagName.toLowerCase()}${scrollable.id ? `#${scrollable.id}` : ""}`
      : "none";
    log(
      "debug",
      `QAM scroll reset (${reason}): before=${beforeTop}, after=${afterTop}, containerTop=${containerTop}, scrollable=${scrollableTag}`,
      "qam_scroll"
    );
  });
}

export function getAutoSyncStatusBounds() {
  const rootWindow = (Router as any).WindowStore?.GamepadUIMainWindowInstance?.BrowserWindow;
  const viewWindow = rootWindow ?? window;
  const pixelRatio = window.devicePixelRatio || 1;
  const rawWidth = viewWindow?.innerWidth || viewWindow?.outerWidth || 1280;
  const rawHeight = viewWindow?.innerHeight || viewWindow?.outerHeight || 800;
  
  log("debug", `Window dimensions: raw=${rawWidth}x${rawHeight}, ratio=${pixelRatio}`, "autosync_status");

  const width = Math.round(rawWidth);
  const height = Math.round(rawHeight * STATUS_STRIP_HEIGHT_RATIO);
  const bottomOffset = Math.round(rawHeight * STEAM_BOTTOM_MENU_HEIGHT_RATIO);

  return {
    x: 0,
    y: Math.max(0, Math.round(rawHeight - height - bottomOffset)),
    width,
    height,
    pixelRatio
  };
}

export function objectKeys(value: unknown): string {
  if (typeof value !== "object" || value === null) {
    return "none";
  }
  try {
    return Object.keys(value).join(",");
  } catch (err) {
    return "error";
  }
}
