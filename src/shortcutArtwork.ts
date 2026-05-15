import { LUDUSAVI_ARTWORK, LudusaviArtworkAsset } from "./assets/ludusaviArtwork";
import type { SteamAppOverview, SteamClientGlobal } from "./types/steam-globals";

export const LOCAL_ARTWORK_ASSET_TYPES: Record<LudusaviArtworkAsset, number> = {
  grid_p: 0,
  hero: 1,
  grid_l: 3,
};

export type ArtworkLogger = (
  level: "info" | "debug" | "warning" | "error",
  message: string,
  operation?: string,
  gameName?: string
) => void;

type ApplyLocalArtworkAssetParams = {
  appId: number;
  appOverview: SteamAppOverview;
  assetType: LudusaviArtworkAsset;
  logger?: ArtworkLogger;
};

type ApplyLudusaviArtworkParams = {
  appId: number;
  appOverview: SteamAppOverview;
  logger?: ArtworkLogger;
};

function getSteamClient(): SteamClientGlobal {
  const client = (globalThis as any).SteamClient ?? (window as any).SteamClient;
  if (!client?.Apps) {
    throw new Error("SteamClient.Apps is unavailable in this frontend context.");
  }
  return client as SteamClientGlobal;
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

function formatArtworkError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function applyLocalArtworkAsset({
  appId,
  assetType,
  logger,
}: ApplyLocalArtworkAssetParams): Promise<void> {
  const steamClient = getSteamClient();
  const steamAssetType = LOCAL_ARTWORK_ASSET_TYPES[assetType];

  try {
    logger?.("debug", `Applying ${assetType} artwork to shortcut ${appId}`, "artwork");
    const base64Data = await localAssetUrlToBase64(LUDUSAVI_ARTWORK[assetType]);

    await steamClient.Apps.SetCustomArtworkForApp(appId, base64Data, "png", steamAssetType);
    logger?.("info", `Applied ${assetType} artwork to shortcut ${appId}`, "artwork");
  } catch (error) {
    logger?.(
      "error",
      `Failed to apply ${assetType} artwork to shortcut ${appId}: ${formatArtworkError(error)}`,
      "artwork"
    );
    console.error("SDH-ludusavi: Failed to apply local shortcut artwork:", error);
    throw error;
  }
}

export async function applyLudusaviArtworkToShortcut({
  appId,
  appOverview,
  logger,
}: ApplyLudusaviArtworkParams): Promise<void> {
  const assetTypes: LudusaviArtworkAsset[] = ["grid_p", "grid_l", "hero"];

  for (const assetType of assetTypes) {
    await applyLocalArtworkAsset({
      appId,
      appOverview,
      assetType,
      logger,
    });
  }
}
