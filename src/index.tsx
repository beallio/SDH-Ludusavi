import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  ToggleField,
  Spinner,
  Router
} from "@decky/ui";
import {
  callable,
  definePlugin,
  toaster,
  useQuickAccessVisible
} from "@decky/api";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FaSave, FaDownload, FaExclamationTriangle } from "react-icons/fa";
import { IoMdRefresh } from "react-icons/io";

import { launchLudusavi, LudusaviLaunchCommand } from "./ludusaviLauncher";

const qamPanelStyles = `
.sdh-ludusavi-full-width-toggle {
  display: block;
  margin-left: -32px;
  margin-right: -32px;
}

.sdh-ludusavi-full-width-toggle > * {
  box-sizing: border-box;
  width: 100%;
  padding-left: 32px;
  padding-right: 32px;
}
`;

type NotificationSettings = {
  enabled: boolean;
  auto_sync_progress: boolean;
  auto_sync_results: boolean;
  manual_operations: boolean;
  refresh_status: boolean;
  failures_errors: boolean;
};

type NotificationCategory = keyof Omit<NotificationSettings, "enabled">;

type Settings = {
  auto_sync_enabled: boolean;
  selected_game: string;
  notifications: NotificationSettings;
};

type GameOperationHistoryEntry = {
  operation: "backup" | "restore" | "start" | "exit";
  trigger: "manual_backup" | "manual_restore" | "auto_start" | "auto_exit";
  status: "backed_up" | "restored" | "skipped" | "failed";
  reason: string | null;
  message: string | null;
  timestamp: string;
};

type GameOperationHistory = {
  last_backup: GameOperationHistoryEntry | null;
  last_restore: GameOperationHistoryEntry | null;
  last_skip: GameOperationHistoryEntry | null;
  last_failure: GameOperationHistoryEntry | null;
  last_operation: GameOperationHistoryEntry | null;
};

type GameStatus = {
  name: string;
  steam_id?: string | number | null;
  configured: boolean;
  has_backup: boolean;
  needs_first_backup: boolean;
  error: string | null;
  status: "configured" | "has_backup" | "needs_first_backup" | "error";
};

type RefreshResult = {
  games: GameStatus[];
  aliases: Record<string, string>;
  history: Record<string, GameOperationHistory>;
  dependency_error: string | null;
};

type OperationStatus = {
  is_running: boolean;
  name: string | null;
  game_name: string | null;
  last_result: string | null;
  last_error: string | null;
};

type OperationResult = {
  status: "backed_up" | "restored" | "skipped" | "failed";
  game?: string;
  reason?: string;
  message?: string;
};

type ConflictResolution = "keep_local" | "restore_backup";

type LifecycleCheckResult = {
  status: "needed" | "conflict" | "skipped" | "failed";
  operation?: "backup" | "restore";
  game?: string;
  reason?: string;
  message?: string;
  localModifiedAt?: string | null;
  backupModifiedAt?: string | null;
  backupPath?: string | null;
  localLabel?: string;
  backupLabel?: string;
};

type ProcessSignalResult = {
  status: "paused" | "resumed" | "skipped" | "failed";
  pid?: number;
  reason?: string;
  message?: string;
};

type AppLifetimeNotification = {
  unAppID: number;
  nInstanceID: number;
  bRunning: boolean;
};

type RunningSession = {
  appID: string;
  name: string;
  source?: "focused" | "route" | "cached" | "running";
};

type RpcStatus = {
  status: "skipped" | "failed";
  reason?: string;
  message?: string;
};

type RpcResult<T> = T | RpcStatus;

type AutoSyncStatusKind = "checking" | "backing_up" | "restoring" | "conflict" | "has_backup" | "unknown" | "error";

type AutoSyncStatusSource = "lifecycle_start" | "lifecycle_exit" | "rpc_result" | "timeout" | "hide";

type AutoSyncStatusState = {
  status: AutoSyncStatusKind;
  visible: boolean;
  source: AutoSyncStatusSource;
  gameName?: string;
  appID?: string;
  tracked?: boolean;
  resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];
};

type AutoSyncStatusBrowserView = {
  LoadURL?: (url: string) => void;
  SetBounds?: (x: number, y: number, width: number, height: number) => void;
  SetFocus?: (value: boolean) => void;
  SetName?: (name: string) => void;
  SetVisible?: (value: boolean) => void;
  SetWindowStackingOrder?: (value: number) => void;
  Destroy?: () => void;
};

type AutoSyncStatusBrowserViewOwner = AutoSyncStatusBrowserView & {
  browserView?: AutoSyncStatusBrowserView;
  BrowserView?: AutoSyncStatusBrowserView;
  m_browserView?: AutoSyncStatusBrowserViewOwner;
};

type Versions = {
  sdh_ludusavi?: string;
  decky?: string;
  ludusavi?: string;
  pyludusavi?: string;
  rclone?: string;
  status?: string;
  message?: string;
};

type LogEntry = {
  level: string;
  message: string;
  timestamp: string;
  operation: string | null;
  game_name: string | null;
};

type LogModalProps = {
  logs: LogEntry[];
  closeModal?: () => void;
};

type LudusaviLogModalProps = {
  logs: string;
  closeModal?: () => void;
};

const getSettings = callable<[], RpcResult<Settings>>("get_settings");
const setAutoSyncEnabled = callable<[enabled: boolean], RpcResult<Settings>>("set_auto_sync_enabled");
const setNotificationSettings = callable<[settings: NotificationSettings], RpcResult<Settings>>("set_notification_settings");
const setSelectedGameCall = callable<[gameName: string], RpcResult<Settings>>("set_selected_game");
const refreshGamesCall = callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>("refresh_games");
const forceBackupCall = callable<[gameName: string], RpcResult<OperationResult>>("force_backup");
const forceRestoreCall = callable<[gameName: string], RpcResult<OperationResult>>("force_restore");
const getVersions = callable<[], RpcResult<Versions>>("get_versions");
const getOperationStatus = callable<[], OperationStatus>("get_operation_status");
const getRecentLogs = callable<[], LogEntry[]>("get_recent_logs");
const getLudusaviLogs = callable<[], RpcResult<string>>("get_ludusavi_logs");
const logCall = callable<[level: string, message: string, operation?: string, gameName?: string], void>("log");
const getLudusaviCommandCall = callable<[], RpcResult<LudusaviLaunchCommand | null>>("get_ludusavi_command");
const pauseGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("pause_game_process");
const resumeGameProcessCall = callable<[pid: number], RpcResult<ProcessSignalResult>>("resume_game_process");
const checkGameStartCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_start");
const restoreGameOnStartCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("restore_game_on_start");
const resolveGameStartConflictCall = callable<[gameName: string, app_id: string | undefined, resolution: ConflictResolution], RpcResult<OperationResult>>("resolve_game_start_conflict");
const checkGameExitCall = callable<[gameName: string, app_id?: string], RpcResult<LifecycleCheckResult>>("check_game_exit");
const backupGameOnExitCall = callable<[gameName: string, app_id?: string], RpcResult<OperationResult>>("backup_game_on_exit");

const getInstalledAppIdsString = async (): Promise<string | undefined> => {
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

const sessionFromAppOverview = (app: any): RunningSession | null => {
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

function getMainRunningSession(): RunningSession | null {
  const session = sessionFromAppOverview((Router as any).MainRunningApp);
  return session ? { ...session, source: "running" } : null;
}

function getMainSteamWindow(): Window | null {
  return (Router as any).WindowStore?.GamepadUIMainWindowInstance?.BrowserWindow ?? null;
}

function getSteamAppNameFromStores(appID: string): string | null {
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

function sessionFromRoutePath(path: string): RunningSession | null {
  const match = path.match(/(?:\/routes)?\/library\/app\/(\d+)/);
  const appID = match?.[1];
  if (!appID) {
    return null;
  }
  const name = getSteamAppNameFromStores(appID) ?? "";
  return { appID, name, source: "route" };
}

function getRouteSteamGameSession(): RunningSession | null {
  const mainWindow = getMainSteamWindow();
  return (
    sessionFromRoutePath(mainWindow?.location?.pathname ?? "") ??
    sessionFromRoutePath(mainWindow?.location?.hash ?? "") ??
    sessionFromRoutePath(window.location.pathname) ??
    sessionFromRoutePath(window.location.hash)
  );
}

function sessionFromSteamUiCandidate(candidate: any): RunningSession | null {
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

function getSteamUiReactPropCandidates(element: Element | null): any[] {
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

function getFocusedSteamGameSession(): RunningSession | null {
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

function captureSteamUiGameContext(): RunningSession | null {
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

function getRecentSteamUiGameContext(): RunningSession | null {
  if (!lastSteamUiGameContext) {
    return null;
  }
  if (Date.now() - lastSteamUiGameContextCapturedAt > STEAM_UI_GAME_CONTEXT_TTL_MS) {
    return null;
  }
  return { ...lastSteamUiGameContext, source: "cached" };
}

function getPreferredSteamGameSession(): RunningSession | null {
  return (
    captureSteamUiGameContext() ??
    getRecentSteamUiGameContext() ??
    getMainRunningSession()
  );
}

function getGameSteamAppID(game: GameStatus): string | null {
  const steamID = game.steam_id;
  if (steamID === undefined || steamID === null || steamID === "") {
    return null;
  }
  return String(steamID);
}

function findAliasTargetForSession(
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

function findGameForRunningSession(
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

function describeSteamGameSession(session: RunningSession): string {
  return `source=${session.source ?? "unknown"} appID=${session.appID || "unknown"} name=${session.name || "unknown"} normalized=${normalize(session.name || "")}`;
}

function logCurrentGameSelection(
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

function logCurrentGameNoMatch(
  session: RunningSession | null,
  currentGames: GameStatus[],
  currentAliases: Record<string, string>
) {
  log(
    "warning",
    `QAM current game not selected: context=${session ? describeSteamGameSession(session) : "none"} games=${currentGames.length} aliasKeys=${Object.keys(currentAliases).length}`,
    "qam_context",
    session?.name
  );
}

function findScrollableParent(element: HTMLElement | null): HTMLElement | null {
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

function resetQuickAccessScroll(container: HTMLElement | null, reason = "qam_open") {
  window.requestAnimationFrame(() => {
    const scrollable = findScrollableParent(container);
    const beforeTop = scrollable?.scrollTop ?? -1;
    if (scrollable) {
      scrollable.scrollTo({ top: 0, left: 0, behavior: "auto" });
    }
    if (container) {
      container.scrollIntoView({ block: "start" });
    }
    const afterTop = scrollable?.scrollTop ?? -1;
    const containerTop = container?.getBoundingClientRect?.().top ?? -1;
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

const log = (level: "info" | "debug" | "warning" | "error", message: string, operation?: string, gameName?: string) => {
  const prefix = `SDH-ludusavi${operation ? `:${operation}` : ""}${gameName ? ` [${gameName}]` : ""}`;
  const fullMsg = `${prefix}: ${message}`;
  
  console.log(fullMsg);

  void logCall(level, message, operation, gameName);
};

const statusLabels: Record<GameStatus["status"], string> = {
  configured: "Configured",
  has_backup: "Backup ready",
  needs_first_backup: "Needs first backup",
  error: "Error"
};

const defaultNotificationSettings: NotificationSettings = {
  enabled: true,
  auto_sync_progress: true,
  auto_sync_results: true,
  manual_operations: true,
  refresh_status: true,
  failures_errors: true
};

const defaultSettings = (): Settings => ({
  auto_sync_enabled: false,
  selected_game: "",
  notifications: { ...defaultNotificationSettings }
});

function normalizeNotificationSettings(settings?: Partial<NotificationSettings>): NotificationSettings {
  return {
    enabled: typeof settings?.enabled === "boolean" ? settings.enabled : true,
    auto_sync_progress: typeof settings?.auto_sync_progress === "boolean" ? settings.auto_sync_progress : true,
    auto_sync_results: typeof settings?.auto_sync_results === "boolean" ? settings.auto_sync_results : true,
    manual_operations: typeof settings?.manual_operations === "boolean" ? settings.manual_operations : true,
    refresh_status: typeof settings?.refresh_status === "boolean" ? settings.refresh_status : true,
    failures_errors: typeof settings?.failures_errors === "boolean" ? settings.failures_errors : true
  };
}

function normalizeSettings(settings: Settings): Settings {
  return {
    ...settings,
    notifications: normalizeNotificationSettings(settings.notifications)
  };
}

function SpinnerButton({ children, loading, ...props }: any) {
  return (
    <ButtonItem {...props} disabled={props.disabled || loading}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "10px" }}>
        {loading && <Spinner style={{ width: "18px", height: "18px", color: "#1a9fff" }} />}
        {children}
      </div>
    </ButtonItem>
  );
}

function PluginIcon() {
  return (
    <svg
      viewBox="0 0 1536 1536"
      role="img"
      aria-label="SDH-ludusavi"
      fill="currentColor"
      width="1em"
      height="1em"
      style={{ display: "block" }}
    >
      <circle cx="191" cy="192" r="71" />
      <circle cx="192" cy="478" r="71" />
      <rect x="120" y="708" width="144" height="707" rx="72" ry="72" />
      <rect x="120" y="1265" width="1332" height="150" rx="75" ry="75" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M496 216H1256C1304.6 216 1344 255.4 1344 304V1064C1344 1112.6 1304.6 1152 1256 1152H496C447.4 1152 408 1112.6 408 1064V304C408 255.4 447.4 216 496 216ZM552 360V1008H1200V360H552Z"
      />
      <circle cx="719" cy="527" r="71" />
      <circle cx="1031" cy="528" r="71" />
      <circle cx="719" cy="840" r="71" />
      <circle cx="1031" cy="840" r="71" />
    </svg>
  );
}

function FullWidthToggle({ children }: { children: ReactNode }) {
  return <div className="sdh-ludusavi-full-width-toggle">{children}</div>;
}

const autoSyncStatusText: Record<AutoSyncStatusKind, string> = {
  checking: "VERIFYING GAME SAVE",
  backing_up: "BACKING UP LOCAL SAVE",
  restoring: "RESTORING BACKUP SAVE",
  conflict: "SAVE CONFLICT",
  has_backup: "GAME SAVE UP TO DATE",
  unknown: "UNKNOWN",
  error: "UNABLE TO SYNC"
};

let currentAutoSyncStatusState: AutoSyncStatusState = {
  status: "has_backup",
  visible: false,
  source: "hide"
};
let autoSyncStatusTimedOut = false;
let autoSyncStatusHideTimeoutID: number | null = null;
let autoSyncStatusBrowserView: AutoSyncStatusBrowserView | null = null;
let autoSyncStatusBrowserViewOwner: AutoSyncStatusBrowserViewOwner | null = null;

const STATUS_STRIP_HEIGHT_RATIO = 0.0475;
const STEAM_BOTTOM_MENU_HEIGHT_RATIO = 0.02625;

function getAutoSyncStatusBounds() {
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

function objectKeys(value: unknown): string {
  if (typeof value !== "object" || value === null) {
    return "none";
  }
  return Object.keys(value).join(",");
}

function getPrototypeKeys(value: unknown): string {
  if (typeof value !== "object" || value === null) {
    return "none";
  }
  const prototype = Object.getPrototypeOf(value);
  if (typeof prototype !== "object" || prototype === null) {
    return "none";
  }
  return Object.getOwnPropertyNames(prototype).join(",");
}

function patchBrowserViewMethodAliases(view: AutoSyncStatusBrowserViewOwner) {
  const raw = view as any;
  if (!raw.LoadURL && raw.loadURL) raw.LoadURL = raw.loadURL;
  if (!raw.SetBounds && raw.setBounds) raw.SetBounds = raw.setBounds;
  if (!raw.SetVisible && raw.setVisible) raw.SetVisible = raw.setVisible;
  if (!raw.SetFocus && raw.setFocus) raw.SetFocus = raw.setFocus;
  if (!raw.SetName && raw.setName) raw.SetName = raw.setName;
  if (!raw.SetWindowStackingOrder && raw.setWindowStackingOrder) {
    raw.SetWindowStackingOrder = raw.setWindowStackingOrder;
  }
  if (!raw.Destroy && raw.destroy) raw.Destroy = raw.destroy;
}

function normalizeAutoSyncStatusBrowserView(
  candidate: AutoSyncStatusBrowserViewOwner | null,
): AutoSyncStatusBrowserView | null {
  const candidates: Array<[string, AutoSyncStatusBrowserViewOwner | undefined | null]> = [
    ["root", candidate],
    ["m_browserView", candidate?.m_browserView],
    ["browserView", candidate?.browserView],
    ["BrowserView", candidate?.BrowserView],
    ["m_browserView.m_browserView", candidate?.m_browserView?.m_browserView],
  ];

  for (const [source, view] of candidates) {
    if (!view) {
      continue;
    }
    patchBrowserViewMethodAliases(view);
    if (view.LoadURL && view.SetBounds && view.SetVisible) {
      log("info", `BrowserView normalized from ${source}`, "autosync_status");
      return view;
    }
    log(
      "debug",
      `BrowserView candidate ${source} missing methods; keys=${objectKeys(view)} prototype=${getPrototypeKeys(view)}`,
      "autosync_status",
    );
  }

  return null;
}

function ensureAutoSyncStatusBrowserView(): AutoSyncStatusBrowserView | null {
  if (autoSyncStatusBrowserView) {
    return autoSyncStatusBrowserView;
  }

  try {
    const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
    const rootWindow = (Router as any).WindowStore?.GamepadUIMainWindowInstance;

    if (rootWindow?.CreateBrowserView) {
      log("info", "Creating BrowserView via GamepadUIMainWindowInstance", "autosync_status");
      autoSyncStatusBrowserViewOwner = rootWindow.CreateBrowserView(
        "sdh-ludusavi-autosync-status-strip",
      ) as AutoSyncStatusBrowserViewOwner;
    } else if (steamClient?.BrowserView?.Create) {
      log("info", "Creating BrowserView via SteamClient.BrowserView.Create", "autosync_status");
      autoSyncStatusBrowserViewOwner = steamClient.BrowserView.Create({
        strInitialURL: "about:blank"
      }) as AutoSyncStatusBrowserViewOwner | null;
    }

    if (!autoSyncStatusBrowserViewOwner) {
      log("error", "Failed to create BrowserView surface", "autosync_status");
      return null;
    }

    log(
      "info",
      `BrowserView created: type=${typeof autoSyncStatusBrowserViewOwner}, keys=${objectKeys(autoSyncStatusBrowserViewOwner)} prototype=${getPrototypeKeys(autoSyncStatusBrowserViewOwner)}`,
      "autosync_status",
    );

    const normalized = normalizeAutoSyncStatusBrowserView(autoSyncStatusBrowserViewOwner);
    if (!normalized) {
      log("warning", "Status strip BrowserView is missing required methods", "autosync_status");
      return null;
    }

    normalized.SetName?.("sdh-ludusavi-autosync-status-strip");
    normalized.SetWindowStackingOrder?.(50);
    normalized.SetFocus?.(false);
    normalized.SetVisible?.(false);

    if (typeof (normalized as any).SetTopmost === "function") {
      (normalized as any).SetTopmost(true);
    }

    autoSyncStatusBrowserView = normalized;
    return autoSyncStatusBrowserView;
  } catch (err) {
    log("warning", `Could not create status strip BrowserView: ${err}`, "autosync_status");
    autoSyncStatusBrowserView = null;
    autoSyncStatusBrowserViewOwner = null;
    return null;
  }
}

function iconSvgForAutoSyncStatus(status: AutoSyncStatusKind) {
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
    return '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="2.2" opacity="0.55"/><path d="M10 2a8 8 0 0 1 8 8" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/></svg>';
  }

  const rotation = status === "restoring" ? ' style="transform: rotate(180deg); transform-origin: 50% 50%;"' : "";
  return `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"${rotation}><circle cx="10" cy="10" r="8.8" fill="currentColor"/><path d="M10 5.3v8.3" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round"/><path d="M6.8 8.4 10 5.2l3.2 3.2" fill="none" stroke="#0b151f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function renderAutoSyncStatusHtml(state: AutoSyncStatusState) {
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
.icon { width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; color: ${state.status === "error" ? "#ef4444" : state.status === "unknown" ? "#f59e0b" : "#66c0f4"}; }
</style>
</head>
<body>
<div class="bar">
  <div class="text"><span class="icon">${iconSvgForAutoSyncStatus(state.status)}</span>${autoSyncStatusText[state.status]}</div>
</div>
</body>
</html>`;
}

function syncAutoSyncStatusBrowserView(state: AutoSyncStatusState) {
  const browserView = ensureAutoSyncStatusBrowserView();
  if (!browserView) {
    return;
  }
  if (!browserView.LoadURL || !browserView.SetBounds || !browserView.SetVisible) {
    log("warning", "Status strip BrowserView is missing required methods", "autosync_status");
    return;
  }

  try {
    const bounds = getAutoSyncStatusBounds();
    const html = renderAutoSyncStatusHtml(state);
    const url = "data:text/html;charset=utf-8," + encodeURIComponent(html);
    
    log("debug", `Syncing BrowserView: visible=${state.visible}, bounds=${JSON.stringify(bounds)}`, "autosync_status");

    if (state.visible) {
      browserView.SetBounds(bounds.x, bounds.y, bounds.width, bounds.height);
      browserView.LoadURL(url);
      
      setTimeout(() => {
        browserView.SetVisible?.(true);
        browserView.SetWindowStackingOrder?.(50);
        browserView.SetFocus?.(false);
      }, 0);
    } else {
      browserView.SetVisible(false);
    }
  } catch (err) {
    log("warning", `Could not update status strip BrowserView: ${err}`, "autosync_status");
  }
}

function destroyAutoSyncStatusBrowserView() {
  try {
    const browserView = autoSyncStatusBrowserView;
    if (!browserView) {
      return;
    }
    browserView.SetVisible?.(false);
    if (typeof browserView.Destroy === "function") {
      browserView.Destroy();
    } else if (typeof autoSyncStatusBrowserViewOwner?.Destroy === "function") {
      autoSyncStatusBrowserViewOwner.Destroy();
    } else {
      const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
      steamClient?.BrowserView?.Destroy?.(autoSyncStatusBrowserViewOwner ?? browserView);
    }
  } catch (err) {
    log("warning", `Could not destroy status strip BrowserView: ${err}`, "autosync_status");
  } finally {
    autoSyncStatusBrowserView = null;
    autoSyncStatusBrowserViewOwner = null;
  }
}

type AutoSyncStatusPublishOptions = {
  source: AutoSyncStatusSource;
  gameName?: string;
  appID?: string;
  tracked?: boolean;
  resultStatus?: OperationResult["status"] | LifecycleCheckResult["status"] | RpcStatus["status"];
};

function logAutoSyncStatusChange(state: AutoSyncStatusState) {
  log(
    "info",
    `Status update: source=${state.source} status=${state.status} visible=${state.visible} game=${state.gameName ?? "unknown"} app_id=${state.appID ?? "unknown"} tracked=${state.tracked ?? "unknown"} result=${state.resultStatus ?? "none"}`,
    "autosync_status",
    state.gameName
  );
}

function clearAutoSyncStatusHideTimeout() {
  if (autoSyncStatusHideTimeoutID === null) {
    return;
  }
  window.clearTimeout(autoSyncStatusHideTimeoutID);
  autoSyncStatusHideTimeoutID = null;
}

function scheduleAutoSyncStatusHide(state: AutoSyncStatusState) {
  clearAutoSyncStatusHideTimeout();
  if (!state.visible) {
    return;
  }

  const isRunning = state.status === "checking" || state.status === "backing_up" || state.status === "restoring";
  autoSyncStatusHideTimeoutID = window.setTimeout(() => {
    if (isRunning) {
      autoSyncStatusTimedOut = true;
    }
    hideAutoSyncStatus({
      source: "timeout",
      gameName: currentAutoSyncStatusState.gameName,
      appID: currentAutoSyncStatusState.appID,
      tracked: currentAutoSyncStatusState.tracked,
      resultStatus: currentAutoSyncStatusState.resultStatus
    });
  }, isRunning ? 10000 : 2000);
}

function publishAutoSyncStatus(status: AutoSyncStatusKind, options: AutoSyncStatusPublishOptions) {
  if (status === "backing_up" || status === "restoring") {
    autoSyncStatusTimedOut = false;
  }

  currentAutoSyncStatusState = {
    status,
    visible: true,
    source: options.source,
    gameName: options.gameName,
    appID: options.appID,
    tracked: options.tracked,
    resultStatus: options.resultStatus
  };
  logAutoSyncStatusChange(currentAutoSyncStatusState);
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
  scheduleAutoSyncStatusHide(currentAutoSyncStatusState);
}

function hideAutoSyncStatus(options: Partial<AutoSyncStatusPublishOptions> = {}) {
  clearAutoSyncStatusHideTimeout();
  currentAutoSyncStatusState = {
    ...currentAutoSyncStatusState,
    visible: false,
    source: options.source ?? "hide",
    gameName: options.gameName ?? currentAutoSyncStatusState.gameName,
    appID: options.appID ?? currentAutoSyncStatusState.appID,
    tracked: options.tracked ?? currentAutoSyncStatusState.tracked,
    resultStatus: options.resultStatus ?? currentAutoSyncStatusState.resultStatus
  };
  logAutoSyncStatusChange(currentAutoSyncStatusState);
  syncAutoSyncStatusBrowserView(currentAutoSyncStatusState);
}

function completeAutoSyncStatus(
  result: OperationResult | LifecycleCheckResult,
  options: Omit<AutoSyncStatusPublishOptions, "source" | "resultStatus">
) {
  if (result.status === "failed") {
    publishAutoSyncStatus("error", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
    return;
  }

  if (result.status === "conflict") {
    publishAutoSyncStatus("conflict", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
    return;
  }

  if (autoSyncStatusTimedOut) {
    return;
  }

  if (result.status === "backed_up" || result.status === "restored") {
    publishAutoSyncStatus("has_backup", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
    return;
  }

  if (result.status === "skipped") {
    if (result.reason === "local_current") {
      publishAutoSyncStatus("has_backup", {
        ...options,
        source: "rpc_result",
        resultStatus: result.status
      });
      return;
    }

    if (["ambiguous_recency", "game_error", "preview_failed"].includes(result.reason ?? "")) {
      publishAutoSyncStatus("error", {
        ...options,
        source: "rpc_result",
        resultStatus: result.status
      });
      return;
    }

    publishAutoSyncStatus("unknown", {
      ...options,
      source: "rpc_result",
      resultStatus: result.status
    });
  }
}

function LogModal({ logs, closeModal }: LogModalProps) {
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Plugin Logs"
      onOK={closeModal}
      onCancel={closeModal}
    >
      <div
        style={{
          maxHeight: "60vh",
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          backgroundColor: "rgba(0, 0, 0, 0.3)",
          padding: "10px",
          borderRadius: "4px",
          userSelect: "text",
        }}
      >
        {logs.length === 0 ? "No recent logs" : logs.map(formatLogEntry).join("\n")}
      </div>
    </ConfirmModal>
  );
}

type ConflictResolutionModalProps = {
  conflict: LifecycleCheckResult;
  onChoose: (resolution: ConflictResolution) => void;
  onDismiss: () => void;
  closeModal?: () => void;
};

function formatConflictTime(value?: string | null) {
  return value || "Unknown time";
}

function ConflictResolutionModal({ conflict, onChoose, onDismiss, closeModal }: ConflictResolutionModalProps) {
  const choose = (resolution: ConflictResolution) => {
    closeModal?.();
    onChoose(resolution);
  };
  const dismiss = () => {
    closeModal?.();
    onDismiss();
  };
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Conflict Detected"
      onOK={() => choose("restore_backup")}
      onCancel={dismiss}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px" }}>
        <div>
          Both your local save and backup save appear to have changed. Choose which version
          should be used before the game continues loading.
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <div>Keep Local Save: {formatConflictTime(conflict.localModifiedAt)}</div>
          <div>Restore Backup Save: {formatConflictTime(conflict.backupModifiedAt)}</div>
          {conflict.backupPath && <div>Backup path: {conflict.backupPath}</div>}
        </div>
        <ButtonItem layout="below" onClick={() => choose("keep_local")}>
          Keep Local Save
        </ButtonItem>
        <ButtonItem layout="below" onClick={() => choose("restore_backup")}>
          Restore Backup Save
        </ButtonItem>
      </div>
    </ConfirmModal>
  );
}

function showConflictResolutionModal(
  conflict: LifecycleCheckResult
): Promise<ConflictResolution | null> {
  return new Promise((resolve) => {
    let settled = false;
    const settle = (resolution: ConflictResolution | null) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(resolution);
    };
    showModal(
      <ConflictResolutionModal
        conflict={conflict}
        onChoose={(resolution) => settle(resolution)}
        onDismiss={() => settle(null)}
      />
    );
  });
}

function LudusaviLogModal({ logs, closeModal }: LudusaviLogModalProps) {
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Ludusavi Logs"
      onOK={closeModal}
      onCancel={closeModal}
    >
      <div
        style={{
          maxHeight: "60vh",
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          backgroundColor: "rgba(0, 0, 0, 0.3)",
          padding: "10px",
          borderRadius: "4px",
          userSelect: "text",
        }}
      >
        {logs || "No Ludusavi logs available"}
      </div>
    </ConfirmModal>
  );
}

let trackedAppIDs = new Set<string>();
let trackedNames = new Set<string>();
let autoSyncNotificationsEnabled = false;
let notificationSettingsMirror: NotificationSettings = { ...defaultNotificationSettings };
let lastSteamUiGameContext: RunningSession | null = null;
let lastSteamUiGameContextCapturedAt = 0;
const STEAM_UI_GAME_CONTEXT_TTL_MS = 10_000;

/** Normalize a game name for fuzzy matching, mirroring backend _normalize. */
function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9.-]+/g, " ").trim();
}

function shouldShowNotification(category: NotificationCategory): boolean {
  return notificationSettingsMirror.enabled && notificationSettingsMirror[category];
}

function notify(category: NotificationCategory, title: string, body: string, logo?: any) {
  log("debug", `notify call: category=${category}, title=${title}, body=${body}`, "autosync_status");
  if (!shouldShowNotification(category)) {
    log("debug", "notify skipped: disabled by settings", "autosync_status");
    return;
  }
  try {
    const toastObj = { 
      title, 
      body, 
      duration: 3000,
      ...(logo ? { logo } : {})
    };
    toaster.toast(toastObj);
    log("debug", "notify successful: toast dispatched", "autosync_status");
  } catch (err) {
    log("error", `notify failed: ${err}`, "autosync_status");
  }
}

function isRpcStatus<T>(result: RpcResult<T>): result is RpcStatus {
  return (
    typeof result === "object" &&
    result !== null &&
    "status" in result &&
    ((result as RpcStatus).status === "skipped" || (result as RpcStatus).status === "failed")
  );
}

function logRpcStatus(result: RpcStatus, operation: string) {
  const level = result.status === "failed" ? "error" : "warning";
  const reason = result.reason ? ` (${result.reason})` : "";
  const message = result.message ?? `${operation} ${result.status}${reason}`;
  log(level, message, operation);
}

let globalSettings: Settings | null = null;
let globalGames: GameStatus[] | null = null;
let globalGameAliases: Record<string, string> | null = null;
let globalGameHistory: Record<string, GameOperationHistory> | null = null;
let globalVersions: Versions | null = null;
let globalLudusaviCommand: LudusaviLaunchCommand | null = null;

function Content() {
  const isQuickAccessVisible = useQuickAccessVisible();
  const qamContentRef = useRef<HTMLDivElement | null>(null);
  const wasQuickAccessVisible = useRef(false);
  const pendingCurrentGameSelection = useRef(false);
  const [settings, setSettings] = useState<Settings>(globalSettings ?? defaultSettings());
  const [games, setGames] = useState<GameStatus[]>(globalGames ?? []);
  const [gameAliases, setGameAliases] = useState<Record<string, string>>(globalGameAliases ?? {});
  const [gameHistory, setGameHistory] = useState<Record<string, GameOperationHistory>>(globalGameHistory ?? {});
  const [selectedGame, setSelectedGame] = useState(globalSettings?.selected_game ?? "");
  const [versions, setVersions] = useState<Versions>(globalVersions ?? {});
  const [operation, setOperation] = useState<OperationStatus>({
    is_running: false,
    name: null,
    game_name: null,
    last_result: null,
    last_error: null
  });
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [backgroundRefreshBusy, setBackgroundRefreshBusy] = useState(false);
  const [ludusaviCommand, setLudusaviCommand] = useState<LudusaviLaunchCommand | null>(globalLudusaviCommand);

  const applySettings = (nextSettings: Settings) => {
    const normalized = normalizeSettings(nextSettings);
    setSettings(normalized);
    globalSettings = normalized;
    autoSyncNotificationsEnabled = normalized.auto_sync_enabled;
    notificationSettingsMirror = normalized.notifications;
    return normalized;
  };

  const syncSelectedGameCache = (nextSelectedGame: string) => {
    setSettings((current) => {
      const nextSettings = { ...current, selected_game: nextSelectedGame };
      globalSettings = globalSettings
        ? { ...globalSettings, selected_game: nextSelectedGame }
        : nextSettings;
      return nextSettings;
    });
  };

  const selectedStatus = useMemo(
    () => games.find((game) => game.name === selectedGame) ?? null,
    [games, selectedGame]
  );
  const selectedHistory = useMemo(() => {
    const history = gameHistory[selectedGame];
    return history?.last_operation ?? null;
  }, [gameHistory, selectedGame]);
  const isBusy = operation.is_running || busyLabel !== null || backgroundRefreshBusy;

  function selectCurrentSteamGameIfAvailable(
    currentGames: GameStatus[],
    currentAliases: Record<string, string>
  ): boolean {
    const runningSession = getPreferredSteamGameSession();
    if (!runningSession) {
      logCurrentGameNoMatch(null, currentGames, currentAliases);
      return false;
    }

    const runningGame = findGameForRunningSession(currentGames, runningSession, currentAliases);
    if (!runningGame) {
      logCurrentGameNoMatch(runningSession, currentGames, currentAliases);
      return false;
    }

    setSelectedGame(runningGame.game.name);
    logCurrentGameSelection(
      runningSession,
      runningGame.game,
      runningGame.reason,
      currentGames,
      currentAliases
    );
    return true;
  }

  useEffect(() => {
    log("info", "Plugin mounted, starting initial load");
    void loadInitial();
  }, []);

  useEffect(() => {
    if (isQuickAccessVisible && !wasQuickAccessVisible.current) {
      pendingCurrentGameSelection.current = true;
      const resetDelays = [0, 50, 150, 350];
      resetQuickAccessScroll(qamContentRef.current);
      resetDelays.forEach((delay) => {
        window.setTimeout(() => resetQuickAccessScroll(qamContentRef.current, `qam_open_retry_${delay}`), delay);
      });
    }
    wasQuickAccessVisible.current = isQuickAccessVisible;
  }, [isQuickAccessVisible]);

  useEffect(() => {
    if (!isQuickAccessVisible || !pendingCurrentGameSelection.current || games.length === 0) {
      return;
    }

    selectCurrentSteamGameIfAvailable(games, gameAliases);
    pendingCurrentGameSelection.current = false;
  }, [gameAliases, games, isQuickAccessVisible]);

  useEffect(() => {
    if (isQuickAccessVisible) {
      return;
    }

    captureSteamUiGameContext();
    const contextIntervalID = window.setInterval(captureSteamUiGameContext, 500);
    return () => window.clearInterval(contextIntervalID);
  }, [isQuickAccessVisible]);

  const loadInitial = async () => {
    const isWarmed = globalSettings !== null && globalGames !== null;
    if (!isWarmed) {
      setBusyLabel("Loading");
    }
    setBackgroundRefreshBusy(isWarmed);

    try {
      log("debug", `Starting initial load (warmed=${isWarmed})`);
      const [loadedSettings, loadedVersions, loadedCommand] = await Promise.all([
        getSettings(),
        getVersions(),
        getLudusaviCommandCall()
      ]);

      log("debug", `Loaded settings: ${JSON.stringify(loadedSettings)}`);
      if (isRpcStatus(loadedSettings)) {
        logRpcStatus(loadedSettings, "settings");
      } else {
        const normalizedSettings = applySettings(loadedSettings);
        if (normalizedSettings.selected_game) {
          setSelectedGame(normalizedSettings.selected_game);
        }
      }

      log("debug", `Loaded versions: ${JSON.stringify(loadedVersions)}`);
      if (isRpcStatus(loadedVersions)) {
        logRpcStatus(loadedVersions, "versions");
      } else {
        setVersions(loadedVersions);
        globalVersions = loadedVersions;
      }

      log("debug", `Loaded command: ${JSON.stringify(loadedCommand)}`);
      if (isRpcStatus(loadedCommand)) {
        // If discovery failed, keep existing cached command if any.
        logRpcStatus(loadedCommand, "command discovery");
      } else {
        globalLudusaviCommand = loadedCommand;
        setLudusaviCommand(loadedCommand);
      }

      log("debug", "Initializing game list (cached)");
      const installedAppIds = await getInstalledAppIdsString();
      const refreshed = await refreshGamesCall(false, installedAppIds);
      applyRefreshResult(refreshed, isRpcStatus(loadedSettings) ? undefined : loadedSettings.selected_game);

      const loadedOperation = await getOperationStatus();
      setOperation(loadedOperation);
      const loadedLogs = await getRecentLogs();
      setLogs(loadedLogs);
    } catch (error) {
      log("error", `Initial load failed: ${error}`);
      setLogs(await getRecentLogs().catch(() => []));
    } finally {
      setBackgroundRefreshBusy(false);
      setBusyLabel(null);
    }
  };

  const applyRefreshResult = (result: RpcResult<RefreshResult>, preferredGame?: string): boolean => {
    if (isRpcStatus(result)) {
      logRpcStatus(result, "refresh");
      return false;
    }

    if (result.dependency_error) {
      log("error", `Ludusavi refresh failed: ${result.dependency_error}`, "refresh");
      notify("failures_errors", "SDH-ludusavi refresh failed", result.dependency_error, <FaExclamationTriangle />);
      return false;
    }

    log("debug", `Applying refresh result (${result.games.length} games, ${Object.keys(result.aliases || {}).length} aliases)`);
    setGames(result.games);
    setGameAliases(result.aliases || {});
    setGameHistory(result.history ?? {});
    globalGames = result.games;
    globalGameAliases = result.aliases || {};
    globalGameHistory = result.history ?? {};
    
    // Update global tracking sets for toast filtering
    trackedAppIDs = new Set(result.games.map(g => (g as any).steam_id).filter(id => !!id) as string[]);
    
    const names = new Set<string>();
    result.games.forEach(g => names.add(normalize(g.name)));
    Object.entries(result.aliases || {}).forEach(([alias, target]) => {
      names.add(normalize(alias));
      names.add(normalize(target));
    });
    trackedNames = names;
    
    log("info", `Tracked ${trackedNames.size} game names/aliases`);

    if (selectCurrentSteamGameIfAvailable(result.games, result.aliases || {})) {
      return true;
    }

    const target = preferredGame || selectedGame;
    if (target && result.games.some((game) => game.name === target)) {
      setSelectedGame(target);
      syncSelectedGameCache(target);
    } else {
      const firstGame = result.games[0]?.name ?? "";
      log("debug", `Defaulting selected game to ${firstGame}`);
      setSelectedGame(firstGame);
      syncSelectedGameCache(firstGame);
    }

    return true;
  };

  const refreshGames = async () => {
    log("info", "Manual refresh triggered");
    setBusyLabel("Refreshing games");
    try {
      const installedAppIds = await getInstalledAppIdsString();
      const result = await refreshGamesCall(true, installedAppIds);
      if (applyRefreshResult(result)) {
        setOperation(await getOperationStatus());
        setLogs(await getRecentLogs());
        notify("refresh_status", "SDH-ludusavi", "Ludusavi game status refreshed", <IoMdRefresh />);
      }
    } catch (error) {
      log("error", `Manual refresh failed: ${error}`);
    } finally {
      setBusyLabel(null);
    }
  };

  const showLudusaviLogs = async () => {
    log("info", "Showing Ludusavi logs");
    try {
      const result = await getLudusaviLogs();
      const logs = typeof result === "string" ? result : result.message || `Failed to fetch logs: ${result.status}`;
      showModal(<LudusaviLogModal logs={logs} />);
    } catch (error) {
      log("error", `Failed to fetch Ludusavi logs: ${error}`);
      notify("failures_errors", "SDH-ludusavi", "Failed to fetch Ludusavi logs", <FaExclamationTriangle />);
    }
  };

  const toggleAutoSync = async (enabled: boolean) => {
    log("info", `Toggling auto-sync to ${enabled}`);
    const previous = settings.auto_sync_enabled;
    setBusyLabel("Updating settings");
    
    // Optimistic update
    setSettings(s => ({ ...s, auto_sync_enabled: enabled }));
    autoSyncNotificationsEnabled = enabled;

    try {
      const result = await setAutoSyncEnabled(enabled);
      if (isRpcStatus(result)) {
        throw new Error(result.message || result.status);
      }
      applySettings(result);
    } catch (error) {
      log("error", `Failed to toggle auto-sync: ${error}`);
      // Rollback
      setSettings(s => ({ ...s, auto_sync_enabled: previous }));
      autoSyncNotificationsEnabled = previous;
      notify("failures_errors", "SDH-ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

  const toggleNotificationSetting = async (key: keyof NotificationSettings, enabled: boolean) => {
    log("info", `Toggling notification setting ${key} to ${enabled}`);
    const previous = settings.notifications;
    const nextNotifications = { ...previous, [key]: enabled };
    setBusyLabel("Updating settings");
    setSettings(s => ({ ...s, notifications: nextNotifications }));
    notificationSettingsMirror = nextNotifications;

    try {
      const result = await setNotificationSettings(nextNotifications);
      if (isRpcStatus(result)) {
        throw new Error(result.message || result.status);
      }
      applySettings(result);
    } catch (error) {
      log("error", `Failed to update notification settings: ${error}`);
      setSettings(s => ({ ...s, notifications: previous }));
      notificationSettingsMirror = previous;
      notify("failures_errors", "SDH-ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

  const onGameChange = async (data: any) => {
    const value = typeof data === 'object' ? data?.data : data;
    log("info", `Selected game changed to ${value}`);
    const previous = selectedGame;
    setBusyLabel("Updating settings");
    
    // Optimistic update
    setSelectedGame(value);

    try {
      const result = await setSelectedGameCall(value);
      if (isRpcStatus(result)) {
        throw new Error(result.message || result.status);
      }
      applySettings(result);
      setSelectedGame(result.selected_game);
    } catch (error) {
      log("error", `Failed to persist selected game: ${error}`);
      // Rollback
      setSelectedGame(previous);
      notify("failures_errors", "SDH-ludusavi settings failed", error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

  const runForceOperation = async (
    label: "Backup" | "Restore",
    operationCall: (gameName: string) => Promise<RpcResult<OperationResult>>
  ) => {
    if (!selectedGame) {
      return;
    }
    log("info", `Triggering force ${label} for ${selectedGame}`, label, selectedGame);
    setBusyLabel(`${label} running`);
    const icon = label === "Backup" ? <FaSave /> : <FaDownload />;
    notify("manual_operations", `SDH-ludusavi ${label}`, `${label} started for ${selectedGame}`, icon);
    try {
      const result = await operationCall(selectedGame);
      log("info", `Force ${label} completed: ${JSON.stringify(result)}`, label, selectedGame);
      const resultIcon = result.status === "failed" ? <FaExclamationTriangle /> : icon;
      const category = result.status === "failed" ? "failures_errors" : "manual_operations";
      notify(category, `SDH-ludusavi ${label}`, summarizeOperationResult(result, label), resultIcon);
      const refreshed = await refreshGamesCall(false);
      applyRefreshResult(refreshed);
      setOperation(await getOperationStatus());
      setLogs(await getRecentLogs());
    } catch (error) {
      log("error", `Force ${label} failed: ${error}`, label, selectedGame);
      notify("failures_errors", `SDH-ludusavi ${label} failed`, error instanceof Error ? error.message : String(error), <FaExclamationTriangle />);
    } finally {
      setBusyLabel(null);
    }
  };

  return (
    <div ref={qamContentRef}>
      <style>{qamPanelStyles}</style>
      <PanelSection title="GLOBAL">
        <FullWidthToggle>
          <ToggleField
            label="Automatic Sync"
            highlightOnFocus={true}
            checked={settings.auto_sync_enabled}
            disabled={isBusy}
            onChange={(enabled: boolean) => void toggleAutoSync(enabled)}
          />
        </FullWidthToggle>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            highlightOnFocus={true}
            disabled={isBusy}
            loading={busyLabel === "Refreshing games"}
            onClick={() => void refreshGames()}
          >
            Refresh Games
          </SpinnerButton>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="GAME">
        <PanelSectionRow>
          <DropdownItem
            menuLabel="Select Game"
            highlightOnFocus={true}
            focusable={true}
            disabled={isBusy}
            rgOptions={games.map((game) => ({
              label: game.name,
              data: game.name
            }))}
            selectedOption={selectedGame}
            onChange={(data: any) => void onGameChange(data)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <Field
            label="Status:"
            highlightOnFocus={true}
            focusable={true}
            childrenLayout="inline"
            padding="standard"
          >
            <div style={{ color: "#cbd5e1", fontSize: "14px", minWidth: 0 }}>
              {isBusy && busyLabel === "Loading" ? (
                <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Loading game list...</span>
              ) : isBusy && busyLabel === "Refreshing games" ? (
                <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Game refresh in progress...</span>
              ) : isBusy && busyLabel === "Backup running" ? (
                <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Backup in progress...</span>
              ) : isBusy && busyLabel === "Restore running" ? (
                <span style={{ color: "#60a5fa", fontWeight: "bold" }}>Restore in progress...</span>
              ) : (
                selectedStatus ? statusLabels[selectedStatus.status] : "No Ludusavi games found"
              )}
            </div>
          </Field>
        </PanelSectionRow>

        {selectedHistory && !isBusy && (
          <PanelSectionRow>
            <Field
              label="Last Operation:"
              highlightOnFocus={true}
              focusable={true}
              childrenLayout="inline"
              padding="standard"
            >
              <div style={{ color: "#cbd5e1", fontSize: "14px", minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", textAlign: "right" }}>
                <span style={{ 
                  color: selectedHistory.status === "failed" ? "#f87171" : "#cbd5e1" 
                }}>
                  {selectedHistory.status === "failed" ? "Failed" : 
                   selectedHistory.status === "backed_up" ? "Backed up" :
                   selectedHistory.status === "restored" ? "Restored" :
                   `Skipped${selectedHistory.reason ? ` (${selectedHistory.reason.replace(/_/g, " ")})` : ""}`}
                </span>
                <span style={{ marginLeft: "8px", fontSize: "12px", opacity: 0.65 }}>
                  {selectedHistory.timestamp.split(/[T ]/)[1]?.split(".")[0]}
                </span>
              </div>
            </Field>
          </PanelSectionRow>
        )}

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            highlightOnFocus={true}
            disabled={isBusy || !selectedStatus}
            loading={busyLabel === "Backup running"}
            onClick={() => void runForceOperation("Backup", forceBackupCall)}
          >
            Force Backup
          </SpinnerButton>
        </PanelSectionRow>

        <PanelSectionRow>
          <SpinnerButton
            layout="below"
            highlightOnFocus={true}
            disabled={isBusy || selectedStatus?.status !== "has_backup"}
            loading={busyLabel === "Restore running"}
            onClick={() => void runForceOperation("Restore", forceRestoreCall)}
          >
            Force Restore
          </SpinnerButton>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Notifications">
        <FullWidthToggle>
          <ToggleField
            label="All Notifications"
            highlightOnFocus={true}
            checked={settings.notifications.enabled}
            disabled={isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("enabled", enabled)}
          />
        </FullWidthToggle>
        <FullWidthToggle>
          <ToggleField
            label="Manual Operations"
            highlightOnFocus={true}
            checked={settings.notifications.manual_operations}
            disabled={!settings.notifications.enabled || isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("manual_operations", enabled)}
          />
        </FullWidthToggle>
        <FullWidthToggle>
          <ToggleField
            label="Refresh Status"
            highlightOnFocus={true}
            checked={settings.notifications.refresh_status}
            disabled={!settings.notifications.enabled || isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("refresh_status", enabled)}
          />
        </FullWidthToggle>
        <FullWidthToggle>
          <ToggleField
            label="Failures and Errors"
            highlightOnFocus={true}
            checked={settings.notifications.failures_errors}
            disabled={!settings.notifications.enabled || isBusy}
            onChange={(enabled: boolean) => void toggleNotificationSetting("failures_errors", enabled)}
          />
        </FullWidthToggle>
      </PanelSection>

      <LudusaviPanel ludusaviCommand={ludusaviCommand} isLoading={busyLabel === "Loading"} />

      <PanelSection title="Logs">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<LogModal logs={logs} />)}>
            View Logs
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void showLudusaviLogs()}>
            View Ludusavi Logs
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Versions">
        <PanelSectionRow>
          <Field highlightOnFocus={true} focusable={true} padding="standard">
            <div style={{ color: "#cbd5e1", fontSize: "14px", display: "flex", flexDirection: "column", gap: "4px", minWidth: 0 }}>
              <div>SDH-ludusavi: {versions.sdh_ludusavi ?? "Unknown"}</div>
              <div>Ludusavi: {versions.ludusavi ?? versions.message ?? "Unknown"}</div>
              <div>pyludusavi: {versions.pyludusavi ?? "Unknown"}</div>
              <div>Decky: {versions.decky ?? "Unknown"}</div>
            </div>
          </Field>
        </PanelSectionRow>
      </PanelSection>
    </div>
  );
};

function summarizeOperationResult(result: OperationResult | LifecycleCheckResult, label: string) {
  if (result.status === "conflict") {
    return `Auto-sync needs a save conflict decision for ${result.game ?? "this game"}`;
  }
  if (result.status === "skipped") {
    switch (result.reason) {
      case "auto_sync_disabled": return `Auto-sync skipped: feature disabled`;
      case "operation_running": return `Auto-sync skipped: another operation is running`;
      case "unmatched_game": return `Auto-sync skipped: could not match game name`;
      case "not_processed": return `Auto-sync skipped: game is deselected in Ludusavi`;
      case "no_backup": return `Auto-sync skipped: no backup found for ${result.game}`;

      case "local_current": return `Auto-sync skipped: local save is already current`;
      case "ambiguous_recency": return `Auto-sync skipped: recency is ambiguous`;
      case "conflict_unresolved": return `Auto-sync skipped: save conflict was not resolved`;
      default: return `${label} skipped: ${result.reason ?? "unknown reason"}`;
    }
  }
  if (result.status === "failed") {
    return `${label} failed: ${result.message ?? "unknown error"}`;
  }
  const action = result.status === "backed_up" ? "Backup" : "Restore";
  return `${action} completed for ${result.game}`;
}

function formatLogEntry(entry: LogEntry) {
  const game = entry.game_name ? ` ${entry.game_name}` : "";
  return `[${entry.timestamp}] [${entry.level}]${game} ${entry.message}`;
}

function LudusaviPanel({ 
  ludusaviCommand,
  isLoading
}: { 
  ludusaviCommand: LudusaviLaunchCommand | null,
  isLoading: boolean
}) {
  const [status, setStatus] = useState<string | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);

  async function onLaunch() {
    try {
      setIsLaunching(true);
      setStatus("Launching Ludusavi...");

      if (!ludusaviCommand) {
        throw new Error("Ludusavi not found on system.");
      }

      await launchLudusavi(ludusaviCommand, { logger: log });

      setStatus("Ludusavi launch requested.");
      // Best-effort clear status after 3s
      setTimeout(() => setStatus(null), 3000);
    } catch (err) {
      console.error(err);
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLaunching(false);
    }
  }

  return (
    <PanelSection title="Ludusavi">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={onLaunch}
          disabled={isLaunching || !ludusaviCommand}
        >
          Launch
        </ButtonItem>
      </PanelSectionRow>

      {status && (
        <PanelSectionRow>
          <div style={{ color: "#60a5fa", fontSize: "14px", fontWeight: "bold", padding: "0 4px" }}>
            {status}
          </div>
        </PanelSectionRow>
      )}
      
      {!ludusaviCommand && !isLaunching && !isLoading && (
        <PanelSectionRow>
          <div style={{ color: "#ef4444", fontSize: "12px", padding: "0 4px" }}>
            Ludusavi not found. Please install it via Flatpak or add to PATH.
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

export default definePlugin(() => {
  console.log("SDH-ludusavi plugin initializing");

  const activeSessions = new Map<number, RunningSession>();
  let fallbackIntervalID: number | null = null;
  let fallbackPreviousAppID: string | null = null;
  let fallbackPreviousAppName: string | null = null;
  let lifecycleRegistration: unknown = null;

  const isTracked = (name: string, appID: string) => {
    if (trackedAppIDs.has(appID)) {
      log("debug", `Match found via AppID: ${appID}`);
      return true;
    }
    
    const normalizedInput = normalize(name);
    if (trackedNames.has(normalizedInput)) {
      log("debug", `Match found via exact name: ${normalizedInput}`);
      return true;
    }

    // Substring matching (mirroring backend fuzzy logic)
    for (const trackedName of Array.from(trackedNames)) {
      if (
        (normalizedInput.length > 4 && trackedName.includes(normalizedInput)) ||
        (trackedName.length > 4 && normalizedInput.includes(trackedName))
      ) {
        log("debug", `Match found via substring: ${normalizedInput} <-> ${trackedName}`);
        return true;
      }
    }

    log("debug", `No match for ${name} (${appID}) [normalized: ${normalizedInput}]`);
    return false;
  };

  function shouldPublishAutoSyncStatusBeforeRpc(tracked: boolean) {
    const trackingCacheEmpty = trackedAppIDs.size === 0 && trackedNames.size === 0;
    return (globalSettings === null || autoSyncNotificationsEnabled) && (tracked || trackingCacheEmpty);
  }

  const handleAppStart = async (name: string, appID: string, instanceID?: number) => {
    const tracked = isTracked(name, appID);
    log("info", `App started: ${name} (${appID}) tracked=${tracked}`);
    let paused = false;
    
    if (shouldPublishAutoSyncStatusBeforeRpc(tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_start",
        gameName: name,
        appID,
        tracked
      });
    }

    try {
      if (typeof instanceID === "number" && instanceID > 0) {
        const pauseResult = await pauseGameProcessCall(instanceID);
        if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
          paused = true;
        }
      }

      log("info", `Calling check_game_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const checkResult = await checkGameStartCall(name, appID);
      log("info", `check_game_start result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
      // Show result toast for all outcomes (restored, failed, conflict, or skipped)
      // unless auto-sync is completely disabled, another operation is running,
      // or the game simply isn't managed by Ludusavi (unmatched or ignored).
      const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
      if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
        hideAutoSyncStatus({
          source: "hide",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        return;
      }

      if (checkResult.status === "needed" && checkResult.operation === "restore") {
        if (!paused) {
          const result: OperationResult = {
            status: "failed",
            game: name,
            message: "Launch gate unavailable; restore skipped while game is loading."
          };
          completeAutoSyncStatus(result, { gameName: name, appID, tracked });
          notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
          return;
        }
        publishAutoSyncStatus("restoring", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked
        });
        log("info", `Calling restore_game_on_start for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
        const result = await restoreGameOnStartCall(name, appID);
        log("info", `restore_game_on_start result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      if (checkResult.status === "conflict") {
        publishAutoSyncStatus("conflict", {
          source: "lifecycle_start",
          gameName: name,
          appID,
          tracked,
          resultStatus: checkResult.status
        });
        if (!paused) {
          notify("failures_errors", "SDH-ludusavi Auto-sync", "Launch gate unavailable; conflict resolution skipped while game is loading.", <FaExclamationTriangle />);
          return;
        }
        const resolution = await showConflictResolutionModal(checkResult);
        if (!resolution) {
          completeAutoSyncStatus({ status: "skipped", game: name, reason: "conflict_unresolved" }, { gameName: name, appID, tracked });
          return;
        }
        const result = await resolveGameStartConflictCall(checkResult.game ?? name, appID, resolution);
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
        if (result.status === "failed") {
          notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
        }
        return;
      }

      completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
      if (checkResult.status === "failed") {
        notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"), <FaExclamationTriangle />);
      }
    } finally {
      if (paused && typeof instanceID === "number") {
        await resumeGameProcessCall(instanceID);
      }
    }
  };

  const handleAppExit = async (name: string, appID: string) => {
    const tracked = isTracked(name, appID);
    log("info", `App exited: ${name} (${appID}) tracked=${tracked}`);
    
    if (shouldPublishAutoSyncStatusBeforeRpc(tracked)) {
      publishAutoSyncStatus("checking", {
        source: "lifecycle_exit",
        gameName: name,
        appID,
        tracked
      });
    }
    
    log("info", `Calling check_game_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
    const checkResult = await checkGameExitCall(name, appID);
    log("info", `check_game_exit result for ${name} (${appID}): ${JSON.stringify(checkResult)}`, "lifecycle", name);
    const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
    if (checkResult.status === "skipped" && silentReasons.includes(checkResult.reason ?? "")) {
      hideAutoSyncStatus({
        source: "hide",
        gameName: name,
        appID,
        tracked,
        resultStatus: checkResult.status
      });
      return;
    }

    if (checkResult.status === "needed" && checkResult.operation === "backup") {
      publishAutoSyncStatus("backing_up", {
        source: "lifecycle_exit",
        gameName: name,
        appID,
        tracked
      });
      log("info", `Calling backup_game_on_exit for ${name} (${appID}) tracked=${tracked}`, "lifecycle", name);
      const result = await backupGameOnExitCall(name, appID);
      log("info", `backup_game_on_exit result for ${name} (${appID}): ${JSON.stringify(result)}`, "lifecycle", name);
      completeAutoSyncStatus(result, { gameName: name, appID, tracked });
      if (result.status === "failed") {
        notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(result, "Auto-sync"), <FaExclamationTriangle />);
      }
      return;
    }

    completeAutoSyncStatus(checkResult, { gameName: name, appID, tracked });
    if (checkResult.status === "failed") {
      notify("failures_errors", "SDH-ludusavi Auto-sync", summarizeOperationResult(checkResult, "Auto-sync"), <FaExclamationTriangle />);
    }
  };

  const findRunningSessionByAppID = (appID: string): RunningSession | null => {
    // Router.RunningApps lets Steam app lifetime events recover the display name.
    const runningApps = (Router as any).RunningApps;
    if (Array.isArray(runningApps)) {
      for (const app of runningApps) {
        const session = sessionFromAppOverview(app);
        if (session?.appID === appID) {
          return session;
        }
      }
    }

    const mainSession = getMainRunningSession();
    if (mainSession?.appID === appID) {
      return mainSession;
    }

    return null;
  };

  const findStartupSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const startupSession = activeSessions.get(-1) ?? null;
    if (!startupSession) {
      return null;
    }
    if (notification.unAppID === 0 || startupSession.appID === String(notification.unAppID)) {
      return startupSession;
    }
    return null;
  };

  const resolveLifetimeSession = (notification: AppLifetimeNotification): RunningSession | null => {
    const existingSession = activeSessions.get(notification.nInstanceID);
    if (existingSession) {
      return existingSession;
    }

    if (!notification.bRunning) {
      const startupSession = findStartupSession(notification);
      if (startupSession) {
        return startupSession;
      }
    }

    if (notification.unAppID > 0) {
      const appID = String(notification.unAppID);
      const runningSession = findRunningSessionByAppID(appID);
      if (runningSession) {
        return runningSession;
      }
      return { appID, name: "" };
    }

    // unAppID may be 0 for non-Steam shortcuts, so fall back to Router state.
    return getMainRunningSession();
  };

  const handleLifetimeNotification = (notification: AppLifetimeNotification) => {
    try {
      const session = resolveLifetimeSession(notification);
      if (!session?.name) {
        log(
          "warning",
          `Could not resolve app lifetime notification: ${JSON.stringify(notification)}`,
          "lifecycle"
        );
        return;
      }

      if (notification.bRunning) {
        const startupSession = findStartupSession(notification);
        if (startupSession?.appID === session.appID) {
          activeSessions.delete(-1);
          activeSessions.set(notification.nInstanceID, session);
          log(
            "debug",
            `Promoted startup session for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name
          );
          return;
        }

        if (activeSessions.has(notification.nInstanceID)) {
          log(
            "debug",
            `Duplicate app start ignored for ${session.name} (${session.appID})`,
            "lifecycle",
            session.name
          );
          return;
        }

        activeSessions.set(notification.nInstanceID, session);
        void handleAppStart(session.name, session.appID, notification.nInstanceID);
        return;
      }

      activeSessions.delete(notification.nInstanceID);
      const startupSession = activeSessions.get(-1);
      if (startupSession?.appID === session.appID) {
        activeSessions.delete(-1);
      }
      void handleAppExit(session.name, session.appID);
    } catch (err) {
      console.error("SDH-ludusavi: app lifetime notification failed", err);
    }
  };

  const checkMainApp = () => {
    try {
      const mainApp = (Router as any).MainRunningApp;
      const currentAppID = mainApp?.appid ? String(mainApp.appid) : null;
      const currentAppName = mainApp?.display_name || null;

      if (currentAppID !== fallbackPreviousAppID) {
        // Change detected
        if (fallbackPreviousAppID && fallbackPreviousAppName) {
          void handleAppExit(fallbackPreviousAppName, fallbackPreviousAppID);
        }
        if (currentAppID && currentAppName) {
          void handleAppStart(currentAppName, currentAppID);
        }
        
        fallbackPreviousAppID = currentAppID;
        fallbackPreviousAppName = currentAppName;
      }
    } catch (err) {
      console.error("SDH-ludusavi: watcher loop failed", err);
    }
  };

  const startFallbackPolling = () => {
    log("warning", "Steam app lifetime notifications unavailable; using Router polling", "lifecycle");
    fallbackIntervalID = window.setInterval(checkMainApp, 1000);
  };

  const reconcileStartupSession = () => {
    const session = getMainRunningSession();
    if (!session) {
      return;
    }

    activeSessions.set(-1, session);
    void handleAppStart(session.name, session.appID);
  };

  const unregisterLifecycleNotifications = () => {
    const registration = lifecycleRegistration as
      | { unregister?: () => void; Unregister?: () => void }
      | (() => void)
      | null;
    if (!registration) {
      return;
    }

    if (typeof registration === "function") {
      registration();
    } else if (typeof registration.unregister === "function") {
      registration.unregister();
    } else if (typeof registration.Unregister === "function") {
      registration.Unregister();
    }
  };

  const steamClient = (globalThis as any).SteamClient ?? (window as any).SteamClient;
  const gameSessions = steamClient?.GameSessions;
  const registerLifetime = gameSessions?.RegisterForAppLifetimeNotifications;
  if (typeof registerLifetime === "function") {
    lifecycleRegistration = registerLifetime.call(gameSessions, (notification: AppLifetimeNotification) => {
      handleLifetimeNotification(notification);
    });
    reconcileStartupSession();
  } else {
    startFallbackPolling();
  }

  return {
    name: "SDH-ludusavi",
    titleView: <div className="sdh-ludusavi-title">SDH-ludusavi</div>,
    content: <Content />,
    icon: <PluginIcon />,
    alwaysRender: true,
    onDismount() {
      unregisterLifecycleNotifications();
      if (fallbackIntervalID !== null) {
        window.clearInterval(fallbackIntervalID);
      }
      activeSessions.clear();
      currentAutoSyncStatusState = {
        status: "has_backup",
        visible: false,
        source: "hide"
      };
      clearAutoSyncStatusHideTimeout();
      destroyAutoSyncStatusBrowserView();
      console.log("SDH-ludusavi unloading");
    },
  };
});
