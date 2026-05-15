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
    SetCustomArtworkForApp(
      appId: number,
      base64Data: string,
      imageType: "png",
      assetType: number
    ): void | Promise<void>;

    RunGame(
      gameId: SteamGameId,
      launchOptions: string,
      unknownA: number,
      unknownB: number
    ): void;

    SetAppHidden?: (gameId: SteamGameId, hidden: boolean) => void;
    SetShortcutHidden?: (appId: number, hidden: boolean) => void;
    SetHidden?: (gameId: SteamGameId, hidden: boolean) => void;
    SetAppIsHidden?: (gameId: SteamGameId, hidden: boolean) => void;
    SetShortcutIsHidden?: (appId: number, hidden: boolean) => void;
  };
}

export interface AppStoreGlobal {
  GetAppOverviewByAppID(appId: number): SteamAppOverview | null | undefined;
  m_mapAppOverview: Map<number, SteamAppOverview>;
}

export interface SteamAppOverview {
  m_gameid?: SteamGameId;
  m_unAppID: number;
  m_strDisplayName: string;
  BIsShortcut?(): boolean;
}

declare global {
  interface Window {
    SteamClient?: SteamClientGlobal;
  }
}
