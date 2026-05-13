export {};

declare global {
  const SteamClient: SteamClientGlobal | undefined;
  const appStore: AppStoreGlobal | undefined;

  interface Window {
    SteamClient?: SteamClientGlobal;
    appStore?: AppStoreGlobal;
  }
}

export type SteamGameId = string;

export interface SteamClientGlobal {
  Apps: {
    AddShortcut(
      name: string,
      exe: string,
      startDir: string,
      launchOptions: string
    ): number | Promise<number>;

    SetShortcutName(appId: number, name: string): void;
    SetShortcutExe(appId: number, exe: string): void;
    SetShortcutLaunchOptions(appId: number, launchOptions: string): void;
    SpecifyCompatTool(appId: number, compatTool: string): void;

    RunGame(
      gameId: SteamGameId,
      launchOptions: string,
      unknownA: number,
      unknownB: number
    ): void;

    SetAppHidden?: (gameId: SteamGameId, hidden: boolean) => void;
    SetShortcutHidden?: (appId: number, hidden: boolean) => void;
    SetHidden?: (gameId: SteamGameId, hidden: boolean) => void;
  };
}

export interface AppStoreGlobal {
  GetAppOverviewByAppID(appId: number): SteamAppOverview | null | undefined;
}

export interface SteamAppOverview {
  m_gameid?: SteamGameId;
}
