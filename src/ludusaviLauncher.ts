import { call } from "@decky/api";
import { SteamClientGlobal, AppStoreGlobal, SteamGameId } from "./types/steam-globals";

export type LudusaviLaunchCommand = {
  commandPath: string;
  args?: string[];
  compatTool?: string;
};

export type LauncherShortcutState = {
  appId: number;
  gameId: string;
  managed: boolean;
};

const USER_SHORTCUT_NAME = "Ludusavi";
const LUDUSAVI_SHORTCUT_NAME = "[Plugin] Ludusavi Launcher";
const LUDUSAVI_RUNNING_NAME = "[Plugin] Ludusavi";
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

async function getSavedShortcutAppId(): Promise<number> {
  try {
    const appId = await call<[], number>("get_ludusavi_launcher_shortcut_id");
    return typeof appId === "number" ? appId : -1;
  } catch (err) {
    console.error("Failed to get saved shortcut ID:", err);
    return -1;
  }
}

async function saveShortcutAppId(appId: number): Promise<void> {
  try {
    await call<[appId: number], boolean>("set_ludusavi_launcher_shortcut_id", appId);
  } catch (err) {
    console.error("Failed to save shortcut ID:", err);
  }
}

function getGameIdFromAppId(appId: number): SteamGameId | null {
  const store = getAppStore();
  const overview = store.GetAppOverviewByAppID(appId);
  if (!overview || !overview.m_gameid) {
    return null;
  }
  return overview.m_gameid;
}

function findUserLudusaviShortcut(): LauncherShortcutState | null {
  const store = getAppStore() as any;
  // Try common internal property names for the app overview map/list.
  const apps = store.m_mapAppOverview || store.m_mapApps || store.allApps;

  if (!apps) {
    console.warn("SDH-ludusavi: Could not find app list on appStore. Shortcut search disabled.");
    return null;
  }

  try {
    const iterable = typeof apps.values === "function" ? apps.values() : Object.values(apps);
    for (const overview of iterable) {
      const casted = overview as any;
      if (casted?.m_strDisplayName === USER_SHORTCUT_NAME) {
        if (casted?.m_gameid) {
          return {
            appId: casted.m_unAppID,
            gameId: casted.m_gameid,
            managed: false,
          };
        }
      }
    }
  } catch (err) {
    console.error("SDH-ludusavi: Failed to iterate appStore:", err);
  }

  return null;
}

/**
 * Calculate the 64-bit GameID from the 32-bit AppID for non-Steam games.
 */
function calculateGameId(appId: number): SteamGameId {
  // Lower 32 bits = appId
  // Upper 32 bits = 0x02000000 (Shortcut flag)
  // Logic: (BigInt(appId) | (BigInt(0x02) << 32n)).toString()
  try {
    const gameId = (BigInt(appId) | (BigInt(0x02) << 32n)).toString();
    return gameId;
  } catch (err) {
    console.warn("SDH-ludusavi: BigInt calculation failed, falling back to string concat", err);
    // Fallback if BigInt is somehow broken: appId + mask
    return (appId + 0x0200000000).toString();
  }
}

async function hideShortcutIfSupported(
  appId: number,
  gameId: SteamGameId
): Promise<void> {
  const steamClient = getSteamClient();
  const calculatedGameId = calculateGameId(appId);
  
  console.log(`SDH-ludusavi: Attempting to hide shortcut. appId=${appId}, gameId=${gameId}, calculatedGameId=${calculatedGameId}`);

  /**
   * Steam client internals vary. We try ALL available methods instead of returning early.
   */
  const tryHide = (methodName: string, id: any, val: boolean) => {
    const fn = (steamClient.Apps as any)[methodName];
    if (typeof fn === "function") {
      try {
        fn(id, val);
        console.log(`SDH-ludusavi: Called ${methodName}(${id}, ${val})`);
      } catch (err) {
        console.warn(`SDH-ludusavi: Failed call to ${methodName}(${id}, ${val}):`, err);
      }
    }
  };

  // 1. Try methods that expect GameID (64-bit)
  for (const id of new Set([gameId, calculatedGameId])) {
    if (!id) continue;
    tryHide("SetAppHidden", id, true);
    tryHide("SetHidden", id, true);
    tryHide("SetAppIsHidden", id, true);
  }

  // 2. Try methods that expect AppID (32-bit)
  tryHide("SetShortcutHidden", appId, true);
  tryHide("SetShortcutIsHidden", appId, true);
}

async function createHiddenLudusaviShortcut(): Promise<LauncherShortcutState> {
  const steamClient = getSteamClient();
  // AddShortcut can return number or Promise<number>
  const appIdRes = steamClient.Apps.AddShortcut(
    LUDUSAVI_SHORTCUT_NAME,
    PLACEHOLDER_EXE,
    "",
    ""
  );
  const appId = typeof appIdRes === 'number' ? appIdRes : await appIdRes;

  await saveShortcutAppId(appId);
  await sleep(500);

  const gameId = getGameIdFromAppId(appId);
  if (!gameId) {
    throw new Error(
      `Created Ludusavi launcher shortcut ${appId}, but could not resolve game ID.`
    );
  }

  await hideShortcutIfSupported(appId, gameId);
  return { appId, gameId, managed: true };
}

async function ensureLudusaviShortcut(): Promise<LauncherShortcutState> {
  // 1. Priority: User-created shortcut named "Ludusavi"
  const userShortcut = findUserLudusaviShortcut();
  if (userShortcut) {
    console.log(`SDH-ludusavi: Found user 'Ludusavi' shortcut: ${userShortcut.appId}. Prioritizing.`);
    return userShortcut;
  }

  // 2. Fallback: Plugin-managed shortcut
  const savedAppId = await getSavedShortcutAppId();
  if (savedAppId > 0) {
    const gameId = getGameIdFromAppId(savedAppId);
    if (gameId) {
      await hideShortcutIfSupported(savedAppId, gameId);
      return { appId: savedAppId, gameId, managed: true };
    }
    console.warn(
      `Saved Ludusavi launcher shortcut ${savedAppId} no longer exists. Recreating.`
    );
  }
  return await createHiddenLudusaviShortcut();
}

export async function launchLudusavi(
  command: LudusaviLaunchCommand
): Promise<void> {
  if (!command.commandPath || !command.commandPath.trim()) {
    throw new Error("Ludusavi commandPath is required.");
  }

  const state = await ensureLudusaviShortcut();
  const steamClient = getSteamClient();

  if (!state.managed) {
    // For user shortcuts, we just launch them as-is.
    console.log(`SDH-ludusavi: Launching user shortcut ${state.appId} (${state.gameId})`);
    steamClient.Apps.RunGame(state.gameId, "", -1, 100);
    return;
  }

  const { appId } = state;
  const launchOptions = buildLaunchOptions(command.args);
  const exe = quoteExe(command.commandPath);
  const compatTool = command.compatTool ?? "";

  steamClient.Apps.SetShortcutName(appId, LUDUSAVI_RUNNING_NAME);
  steamClient.Apps.SetShortcutExe(appId, exe);
  steamClient.Apps.SetShortcutLaunchOptions(appId, launchOptions);
  steamClient.Apps.SpecifyCompatTool(appId, compatTool);

  await sleep(500);

  const refreshedGameId = getGameIdFromAppId(appId);
  if (!refreshedGameId) {
    throw new Error(`Could not resolve game ID for Ludusavi shortcut ${appId}.`);
  }

  await hideShortcutIfSupported(appId, refreshedGameId);
  steamClient.Apps.RunGame(refreshedGameId, "", -1, 100);
}
