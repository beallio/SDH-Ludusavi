import { call } from "@decky/api";
import { SteamClientGlobal, AppStoreGlobal, SteamGameId } from "./types/steam-globals";
import { applyLudusaviArtworkToShortcut, ArtworkLogger } from "./shortcutArtwork";

export type LudusaviLaunchCommand = {
  commandPath: string;
  args?: string[];
  compatTool?: string;
};

export type LauncherShortcutState = {
  appId: number;
  gameId: string;
};

export type LaunchLudusaviOptions = {
  logger?: ArtworkLogger;
};

const SHORTCUT_NAME = "Ludusavi";
const PLACEHOLDER_EXE = "/usr/bin/ifyouseethisyoufoundabug";

/**
 * Runtime guard for SteamClient.
 */
function getSteamClient(): SteamClientGlobal {
  const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
  if (!client?.Apps) {
    throw new Error("SteamClient.Apps is unavailable in this frontend context.");
  }
  return client as SteamClientGlobal;
}

/**
 * Runtime guard for appStore.
 */
function getAppStore(): AppStoreGlobal {
  const store = (globalThis as any).appStore ?? (window as any).appStore;
  if (!store?.GetAppOverviewByAppID) {
    throw new Error("appStore.GetAppOverviewByAppID is unavailable in this frontend context.");
  }
  return store as AppStoreGlobal;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function quoteExe(path: string): string {
  const trimmed = path.trim();
  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    return trimmed;
  }
  return `"${trimmed.replace(/"/g, '\\"')}"`;
}

function escapeLaunchArg(arg: string): string {
  if (/^[A-Za-z0-9_./:=@%+-]+$/.test(arg)) {
    return arg;
  }
  return `"${arg.replace(/"/g, '\\"')}"`;
}

function buildLaunchOptions(args?: string[]): string {
  if (!args || args.length === 0) {
    return "";
  }
  return args.map(escapeLaunchArg).join(" ");
}

type RpcStatus = {
  status: "skipped" | "failed";
  reason?: string;
  message?: string;
};

type RpcResult<T> = T | RpcStatus;

function isRpcStatus<T>(result: RpcResult<T>): result is RpcStatus {
  return (
    typeof result === "object" &&
    result !== null &&
    "status" in result &&
    ((result as RpcStatus).status === "skipped" || (result as RpcStatus).status === "failed")
  );
}

async function getSavedShortcutAppId(): Promise<number> {
  try {
    const appId = await call<[], RpcResult<number>>("get_ludusavi_launcher_shortcut_id");
    if (isRpcStatus(appId)) {
      console.error("Failed to get saved shortcut ID:", appId.message || appId.status);
      return -1;
    }
    return typeof appId === "number" ? appId : -1;
  } catch (err) {
    console.error("Failed to get saved shortcut ID:", err);
    return -1;
  }
}

async function saveShortcutAppId(appId: number): Promise<void> {
  let result: RpcResult<boolean>;
  try {
    result = await call<[appId: number], RpcResult<boolean>>("set_ludusavi_launcher_shortcut_id", appId);
  } catch (err) {
    console.error("Failed to save shortcut ID:", err);
    throw new Error(
      `Failed to save shortcut ID: ${err instanceof Error ? err.message : String(err)}`
    );
  }
  if (isRpcStatus(result)) {
    throw new Error(`Failed to save shortcut ID: ${result.message || result.status}`);
  }
}

function getAppOverview(appId: number) {
  const store = getAppStore();
  return store.GetAppOverviewByAppID(appId);
}

function getGameIdFromAppId(appId: number): SteamGameId | null {
  const overview = getAppOverview(appId);
  if (!overview || !overview.m_gameid) {
    return null;
  }
  return overview.m_gameid;
}

function getOverviewAppId(overview: unknown): number | null {
  const casted = overview as any;
  const appId = casted?.m_unAppID ?? casted?.appid ?? casted?.m_nAppID;
  return typeof appId === "number" && appId > 0 ? appId : null;
}

function getOverviewName(overview: unknown): string | null {
  const casted = overview as any;
  const name = casted?.m_strDisplayName ?? casted?.display_name ?? casted?.name;
  return typeof name === "string" ? name : null;
}

function isShortcutOverview(overview: unknown): boolean {
  const casted = overview as any;
  return typeof casted?.BIsShortcut === "function" ? Boolean(casted.BIsShortcut()) : true;
}

function shortcutStateFromOverview(overview: unknown): LauncherShortcutState | null {
  const casted = overview as any;
  const appId = getOverviewAppId(casted);
  const gameId = casted?.m_gameid;

  if (!appId || typeof gameId !== "string" || !isShortcutOverview(casted)) {
    return null;
  }

  return { appId, gameId };
}

function getAppOverviewEntries(): unknown[] {
  const store = getAppStore() as any;
  // Try common internal property names for the app overview map/list.
  const apps = store.m_mapAppOverview || store.m_mapApps || store.allApps;

  if (!apps) {
    console.warn("SDH-ludusavi: Could not find app list on appStore. Available keys:", Object.keys(store));
    return [];
  }

  return typeof apps.values === "function" ? Array.from(apps.values()) : Object.values(apps);
}

function findLudusaviShortcutByName(): LauncherShortcutState | null {
  try {
    const iterable = getAppOverviewEntries();
    console.log(`SDH-ludusavi: Searching ${iterable.length} apps for name "${SHORTCUT_NAME}"`);

    for (const overview of iterable) {
      if (getOverviewName(overview) === SHORTCUT_NAME) {
        const shortcut = shortcutStateFromOverview(overview);
        if (shortcut) {
          return shortcut;
        }
      }
    }
  } catch (err) {
    console.error("SDH-ludusavi: Failed to iterate appStore:", err);
  }

  console.log(`SDH-ludusavi: No shortcut named "${SHORTCUT_NAME}" found in app list.`);
  return null;
}

async function createLudusaviShortcut(): Promise<LauncherShortcutState> {
  const steamClient = getSteamClient();
  // AddShortcut can return number or Promise<number>
  const appIdRes = steamClient.Apps.AddShortcut(SHORTCUT_NAME, PLACEHOLDER_EXE, "", "");
  const appId = typeof appIdRes === "number" ? appIdRes : await appIdRes;

  await saveShortcutAppId(appId);
  await sleep(500);

  const gameId = getGameIdFromAppId(appId);
  if (!gameId) {
    throw new Error(
      `Created Ludusavi launcher shortcut ${appId}, but could not resolve game ID.`
    );
  }

  console.log(
    `SDH-ludusavi: No "Ludusavi" shortcut found. Created new shortcut (AppID: ${appId}) and updated cache.`
  );
  return { appId, gameId };
}

async function ensureLudusaviShortcut(): Promise<LauncherShortcutState> {
  const namedShortcut = findLudusaviShortcutByName();
  const savedAppId = await getSavedShortcutAppId();

  if (namedShortcut) {
    let cacheStatus = "missing";
    if (savedAppId > 0) {
      cacheStatus = savedAppId === namedShortcut.appId ? "current" : `different (${savedAppId})`;
    }

    if (savedAppId !== namedShortcut.appId) {
      await saveShortcutAppId(namedShortcut.appId);
    }

    console.log(
      `SDH-ludusavi: Found "Ludusavi" shortcut by name (AppID: ${namedShortcut.appId}). Cache was ${cacheStatus}.`
    );
    return namedShortcut;
  }

  if (savedAppId > 0) {
    const gameId = getGameIdFromAppId(savedAppId);
    if (gameId) {
      getSteamClient().Apps.SetShortcutName(savedAppId, SHORTCUT_NAME);
      console.log(`SDH-ludusavi: Cached shortcut ${savedAppId} is valid. Using it.`);
      return { appId: savedAppId, gameId };
    }
    console.warn(
      `SDH-ludusavi: Cached shortcut ${savedAppId} is invalid or missing. Recreating.`
    );
  }

  return await createLudusaviShortcut();
}

export async function launchLudusavi(
  command: LudusaviLaunchCommand,
  options?: LaunchLudusaviOptions
): Promise<void> {
  if (!command.commandPath || !command.commandPath.trim()) {
    throw new Error("Ludusavi commandPath is required.");
  }

  const state = await ensureLudusaviShortcut();
  const steamClient = getSteamClient();
  const { appId } = state;
  const launchOptions = buildLaunchOptions(command.args);
  const exe = quoteExe(command.commandPath);
  const compatTool = command.compatTool ?? "";

  steamClient.Apps.SetShortcutName(appId, SHORTCUT_NAME);
  steamClient.Apps.SetShortcutExe(appId, exe);
  steamClient.Apps.SetShortcutLaunchOptions(appId, launchOptions);
  steamClient.Apps.SpecifyCompatTool(appId, compatTool);

  await sleep(500);

  const refreshedGameId = getGameIdFromAppId(appId);
  if (!refreshedGameId) {
    throw new Error(`Could not resolve game ID for Ludusavi shortcut ${appId}.`);
  }

  const appOverview = getAppOverview(appId);
  if (appOverview) {
    try {
      await applyLudusaviArtworkToShortcut({ appId, appOverview, logger: options?.logger });
    } catch (err) {
      options?.logger?.(
        "warning",
        `Continuing launch after artwork failure for shortcut ${appId}: ${err instanceof Error ? err.message : String(err)}`,
        "artwork"
      );
      console.warn("SDH-ludusavi: Continuing launch after artwork failure:", err);
    }
  } else {
    options?.logger?.(
      "warning",
      `Skipping artwork for shortcut ${appId}; app overview unavailable.`,
      "artwork"
    );
    console.warn(`SDH-ludusavi: Skipping artwork for shortcut ${appId}; app overview unavailable.`);
  }
  steamClient.Apps.RunGame(refreshedGameId, "", -1, 100);
}
