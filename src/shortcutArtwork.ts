import { LUDUSAVI_ARTWORK, LudusaviArtworkAsset } from "./assets/ludusaviArtwork";
import type {
  AppDetailsStoreGlobal,
  SteamAppOverview,
  SteamClientGlobal,
} from "./types/steam-globals";

export const LOCAL_ARTWORK_ASSET_TYPES: Record<LudusaviArtworkAsset, number> = {
  grid_p: 0,
  hero: 1,
  logo: 2,
  grid_l: 3,
};

const LOGO_POSITION_WAIT_ATTEMPTS = 5;
const LOGO_POSITION_WAIT_MS = 100;

type ApplyLocalArtworkAssetParams = {
  appId: number;
  appOverview: SteamAppOverview;
  assetType: LudusaviArtworkAsset;
};

type ApplyLudusaviArtworkParams = {
  appId: number;
  appOverview: SteamAppOverview;
};

function getSteamClient(): SteamClientGlobal {
  const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
  if (!client?.Apps) {
    throw new Error("SteamClient.Apps is unavailable in this frontend context.");
  }
  return client as SteamClientGlobal;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function localAssetUrlToBase64(assetUrl: string): Promise<string> {
  const response = await fetch(assetUrl);

  if (!response.ok) {
    throw new Error(`Failed to load local asset: ${assetUrl}`);
  }

  const blob = await response.blob();

  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();

    reader.onerror = () => reject(reader.error ?? new Error("Failed to read local asset"));
    reader.onload = () => {
      const result = reader.result;

      if (typeof result !== "string") {
        reject(new Error("Unexpected FileReader result"));
        return;
      }

      const base64 = result.split(",")[1];

      if (!base64) {
        reject(new Error("Failed to extract base64 data from local asset"));
        return;
      }

      resolve(base64);
    };

    reader.readAsDataURL(blob);
  });
}

async function getCustomLogoPosition(appOverview: SteamAppOverview): Promise<unknown | null> {
  const appDetailsStore = (window as any).appDetailsStore as AppDetailsStoreGlobal | undefined;
  if (!appDetailsStore?.GetCustomLogoPosition) {
    return null;
  }

  for (let attempt = 0; attempt < LOGO_POSITION_WAIT_ATTEMPTS; attempt += 1) {
    const logoPosition = await appDetailsStore.GetCustomLogoPosition(appOverview);
    if (logoPosition) {
      return logoPosition;
    }
    await sleep(LOGO_POSITION_WAIT_MS);
  }

  return null;
}

export async function applyLocalArtworkAsset({
  appId,
  appOverview,
  assetType,
}: ApplyLocalArtworkAssetParams): Promise<void> {
  const steamClient = getSteamClient();
  const steamAssetType = LOCAL_ARTWORK_ASSET_TYPES[assetType];

  try {
    const base64Data = await localAssetUrlToBase64(LUDUSAVI_ARTWORK[assetType]);

    await steamClient.Apps.ClearCustomArtworkForApp(appId, steamAssetType);
    await steamClient.Apps.SetCustomArtworkForApp(appId, base64Data, "png", steamAssetType);

    if (steamAssetType === LOCAL_ARTWORK_ASSET_TYPES.logo && appOverview.BIsShortcut?.()) {
      const logoPosition = await getCustomLogoPosition(appOverview);

      if (!logoPosition) {
        const appDetailsStore = (window as any).appDetailsStore as
          | AppDetailsStoreGlobal
          | undefined;
        await appDetailsStore?.SaveCustomLogoPosition(appOverview, {
          pinnedPosition: "BottomLeft",
          nWidthPct: 50,
          nHeightPct: 50,
        });
      }
    }
  } catch (error) {
    console.error("SDH-ludusavi: Failed to apply local shortcut artwork:", error);
    throw error;
  }
}

export async function applyLudusaviArtworkToShortcut({
  appId,
  appOverview,
}: ApplyLudusaviArtworkParams): Promise<void> {
  const assetTypes: LudusaviArtworkAsset[] = ["grid_p", "grid_l", "hero", "logo"];

  for (const assetType of assetTypes) {
    await applyLocalArtworkAsset({
      appId,
      appOverview,
      assetType,
    });
  }
}
