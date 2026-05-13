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
};

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

async function hideShortcutIfSupported(
  appId: number,
  gameId: SteamGameId
): Promise<void> {
  const steamClient = getSteamClient();
  try {
    if (typeof steamClient.Apps.SetAppHidden === "function") {
      steamClient.Apps.SetAppHidden(gameId, true);
      return;
    }
    if (typeof steamClient.Apps.SetShortcutHidden === "function") {
      steamClient.Apps.SetShortcutHidden(appId, true);
      return;
    }
    if (typeof steamClient.Apps.SetHidden === "function") {
      steamClient.Apps.SetHidden(gameId, true);
      return;
    }
    console.warn("No supported SteamClient hide method found.");
  } catch (err) {
    console.warn("Failed to hide Ludusavi launcher shortcut:", err);
  }
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
  return { appId, gameId };
}

async function ensureLudusaviShortcut(): Promise<LauncherShortcutState> {
  const savedAppId = await getSavedShortcutAppId();
  if (savedAppId > 0) {
    const gameId = getGameIdFromAppId(savedAppId);
    if (gameId) {
      await hideShortcutIfSupported(savedAppId, gameId);
      return { appId: savedAppId, gameId };
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

  const { appId } = await ensureLudusaviShortcut();
  const launchOptions = buildLaunchOptions(command.args);
  const exe = quoteExe(command.commandPath);
  const compatTool = command.compatTool ?? "";

  const steamClient = getSteamClient();
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
