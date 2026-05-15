# Spec: Apply Local SteamGridDB Artwork to Temporary Non-Steam Shortcut on Steam Deck

## Objective

Implement local artwork application for the temporary Non-Steam shortcut created by this Decky plugin.

The plugin must **not fetch SteamGridDB images at runtime**. Instead, the agent must download the required images from the SteamGridDB Ludusavi page during development/build work, place them in the project asset directory, and update the plugin code to reference those local files.

Target SteamGridDB source page:

```text
https://www.steamgriddb.com/game/5360951
```

This page is for **Ludusavi**. ([SteamGridDB][1])

The reference implementation for applying artwork should follow the SteamGridDB Decky plugin’s local artwork flow. That plugin is explicitly built to manage Steam artwork in Gaming Mode, supports Non-Steam shortcuts, and supports selecting local filesystem images. ([GitHub][2])

---

## Required Assets

The agent must download and commit local image files for these asset types:

```text
assets/
  steamgrid/
    ludusavi/
      grid_p.png      # portrait capsule / library capsule
      grid_l.png      # wide capsule / recent-game capsule
      hero.png        # hero / library background
```

SteamGridDB Decky maps these asset types as:

```ts
grid_p -> 0
hero   -> 1
grid_l -> 3
```

The same reference plugin defines readable asset names for Capsule, Wide Capsule, Hero, and Logo. ([GitHub][3])

---

## Hard Requirements

1. The plugin must apply artwork from bundled local files only.
2. The plugin must not call SteamGridDB APIs at runtime.
3. The plugin must not call remote SteamGridDB image URLs at runtime.
4. The plugin must not use or copy the SteamGridDB Decky plugin’s embedded API key. Its source explicitly labels that key as special-use for that plugin only. ([GitHub][4])
5. Runtime code must load the bundled image, convert it to base64, and call:

```ts
SteamClient.Apps.SetCustomArtworkForApp(appId, base64Data, 'png', assetType);
```

The plugin applies bundled artwork directly with `SetCustomArtworkForApp(appId, data, 'png', assetType)`. The logo overlay is intentionally not applied.

---

## Non-Goals

The agent must not implement:

```text
- SteamGridDB browsing UI
- SteamGridDB search
- runtime SGDB API lookup
- runtime image downloading
- user-selectable SGDB artwork
```

The plugin should apply a fixed local artwork set for the temporary shortcut.

---

## Reference Behavior to Reuse

The agent should copy the behavior pattern, not necessarily the exact code structure, from this function:

Key behaviors to preserve:

```text
- normalize the asset type
- apply artwork through SteamClient.Apps.SetCustomArtworkForApp
- log errors without crashing the plugin
```

---

## Implementation Design

### 1. Add Local Asset Manifest

Create a file like:

```ts
// src/assets/ludusaviArtwork.ts

import gridP from '../../assets/grid_p.png';
import gridL from '../../assets/grid_l.png';
import hero from '../../assets/hero.png';

export const LUDUSAVI_ARTWORK = {
  grid_p: gridP,
  grid_l: gridL,
  hero,
} as const;
```

The reference project already declares image imports such as `*.png`, `*.jpg`, and `*.svg`, so local asset imports are compatible with the Decky/Rollup project pattern. ([GitHub][6])

Its Rollup config uses `rollup-plugin-import-assets` for images including PNG, JPG, SVG, GIF, WebP, and MP4, serving them under the plugin’s local Decky URL. ([GitHub][7])

---

### 2. Convert Local Bundled Assets to Base64

Add a helper:

```ts
async function localAssetUrlToBase64(assetUrl: string): Promise<string> {
  const response = await fetch(assetUrl);

  if (!response.ok) {
    throw new Error(`Failed to load local asset: ${assetUrl}`);
  }

  const blob = await response.blob();

  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();

    reader.onerror = () => reject(reader.error ?? new Error('Failed to read local asset'));
    reader.onload = () => {
      const result = reader.result;

      if (typeof result !== 'string') {
        reject(new Error('Unexpected FileReader result'));
        return;
      }

      const base64 = result.split(',')[1];

      if (!base64) {
        reject(new Error('Failed to extract base64 data from local asset'));
        return;
      }

      resolve(base64);
    };

    reader.readAsDataURL(blob);
  });
}
```

This avoids backend network calls and avoids `download_as_base64`. The reference plugin’s backend exposes both `download_as_base64` and `read_file_as_base64`; this feature should use neither for remote downloads at runtime. ([GitHub][8])

---

### 3. Add Local Artwork Application Function

Create a function like:

```ts
import { ASSET_TYPE } from '../constants';
import { LUDUSAVI_ARTWORK } from '../assets/ludusaviArtwork';
import getCustomLogoPosition from '../utils/getCustomLogoPosition';
import log from '../utils/log';

type LocalArtworkAssetType = keyof typeof LUDUSAVI_ARTWORK;

const getAmbiguousAssetType = (assetType: SGDBAssetType | eAssetType): eAssetType =>
  typeof assetType === 'number' ? assetType : ASSET_TYPE[assetType];

export async function applyLocalArtworkAsset(params: {
  appId: number;
  appOverview: AppStoreAppOverview;
  assetType: LocalArtworkAssetType;
}): Promise<void> {
  const { appId, assetType } = params;
  const steamAssetType = getAmbiguousAssetType(assetType);

  try {
    const localAssetUrl = LUDUSAVI_ARTWORK[assetType];
    const base64Data = await localAssetUrlToBase64(localAssetUrl);

    await SteamClient.Apps.SetCustomArtworkForApp(appId, base64Data, 'png', steamAssetType);
  } catch (error) {
    log(error);
    throw error;
  }
}
```

---

### 4. Add Bulk Apply Function

The temporary shortcut should receive all artwork after the shortcut exists and after `appId` / `appOverview` can be resolved.

```ts
export async function applyLudusaviArtworkToShortcut(params: {
  appId: number;
  appOverview: AppStoreAppOverview;
}): Promise<void> {
  const assetTypes: LocalArtworkAssetType[] = [
    'grid_p',
    'grid_l',
    'hero',
  ];

  for (const assetType of assetTypes) {
    await applyLocalArtworkAsset({
      ...params,
      assetType,
    });
  }
}
```

Run this after the temporary Non-Steam shortcut is created and the Steam app overview is available.

---

## Agent Instructions for Downloading Assets

The agent must:

1. Visit:

```text
https://www.steamgriddb.com/game/5360951
```

2. Choose one suitable image for each required type:

```text
- Grids: portrait capsule -> grid_p.png
- Grids: wide capsule -> grid_l.png
- Heroes -> hero.png
```

3. Prefer static PNG files.
4. Avoid animated assets.
5. Save files under:

```text
assets/steamgrid/ludusavi/
```

6. Do not leave any code path that depends on the original remote URL.
7. Do not add the SteamGridDB API key from the reference plugin.
8. Add a small manifest comment with source attribution:

```ts
// Artwork source: SteamGridDB game 5360951, downloaded at build/development time.
// Runtime code must use these bundled local files only.
```

---

## Integration Point

The apply step should run after the temporary Non-Steam shortcut has been created and Steam has assigned/resolved its `appId`.

Pseudo-flow:

```ts
const shortcutAppId = await createTemporaryNonSteamShortcut(...);
const appOverview = await getAppOverview(shortcutAppId);

await applyLudusaviArtworkToShortcut({
  appId: shortcutAppId,
  appOverview,
});
```

Do not apply artwork before `appOverview` is available.

---

## Error Handling

The implementation must handle these cases:

```text
- missing local asset file
- failed local fetch
- failed base64 conversion
- SteamClient artwork call failure
- app overview unavailable
```

Expected behavior:

```text
- log the error
- surface a user-visible toast if this is in a UI-triggered flow
- do not crash the plugin
- do not retry by fetching from SteamGridDB
```

---

## Acceptance Criteria

The implementation is complete when:

```text
[ ] Required images exist in assets/steamgrid/ludusavi/.
[ ] Runtime code contains no steamgriddb.com image fetches.
[ ] Runtime code contains no SteamGridDB API calls for this artwork.
[ ] Runtime code does not use the SGDB Decky plugin API key.
[ ] grid_p, grid_l, and hero are applied to the temporary shortcut.
[ ] No logo overlay is applied to the temporary shortcut.
[ ] The plugin still works offline after build/install.
[ ] Removing network access does not prevent artwork from applying.
```

---

## Recommended Test

1. Disconnect the Steam Deck from the network.
2. Install/run the plugin.
3. Trigger creation of the temporary Non-Steam shortcut.
4. Confirm the shortcut displays:

   * portrait capsule
   * wide capsule
   * hero background
5. Restart Steam / return to Gaming Mode.
6. Confirm the artwork persists.
7. Confirm logs show no runtime request to SteamGridDB.

[1]: https://www.steamgriddb.com/game/5360951 "Ludusavi (Program) - SteamGridDB"
[2]: https://github.com/SteamGridDB/decky-steamgriddb/ "GitHub - SteamGridDB/decky-steamgriddb: Plugin for Decky Loader to apply and manage custom art assets from within gaming mode. · GitHub"
[3]: https://raw.githubusercontent.com/SteamGridDB/decky-steamgriddb/main/src/constants.ts "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/SteamGridDB/decky-steamgriddb/main/src/hooks/useSGDB.tsx "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/SteamGridDB/decky-steamgriddb/main/src/utils/getCustomLogoPosition.ts "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/SteamGridDB/decky-steamgriddb/main/src/types.d.ts "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/SteamGridDB/decky-steamgriddb/main/rollup.config.mjs "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/SteamGridDB/decky-steamgriddb/main/main.py "raw.githubusercontent.com"
