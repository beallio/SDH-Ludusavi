# Implementation Plan: Update Shortcut Artwork Assets

## Problem Definition
The Ludusavi shortcut assets need to be updated to use new images for the portrait capsule and hero, and the logo overlay should be removed entirely.

## Architecture Overview
The shortcut artwork is managed by a combination of static PNG assets in `assets/steamgrid/ludusavi/` and TypeScript logic in `src/shortcutArtwork.ts` which uses the SteamClient API to apply these assets to the shortcut.

## Core Data Structures
- `LUDUSAVI_ARTWORK` in `src/assets/ludusaviArtwork.ts`: A map of asset keys to imported PNG files.
- `LOCAL_ARTWORK_ASSET_TYPES` in `src/shortcutArtwork.ts`: A map of asset keys to Steam's internal asset type IDs.

## Public Interfaces
- `applyLudusaviArtworkToShortcut`: The main entry point for applying the set of artwork to a shortcut.

## Dependency Requirements
- `curl` or `wget` for downloading the new assets during the implementation phase.
- `ruff` and `pytest` for validation.

## Implementation Steps

### 1. Asset Management
- Delete the logo asset: `rm assets/steamgrid/ludusavi/logo.png`.
- Download the new portrait capsule:
  `curl -L https://cdn2.steamgriddb.com/grid/71c7ca74c4dec0da6247b49837c47ed5.png -o assets/steamgrid/ludusavi/grid_p.png`
- Download the new hero image:
  `curl -L https://cdn2.steamgriddb.com/hero/8e94f8d8e0d415f7ab0f35653eacd7f3.png -o assets/steamgrid/ludusavi/hero.png`
- Verify that `assets/steamgrid/ludusavi/grid_l.png` is preserved.

### 2. Frontend Code Refactoring
- **Modify `src/assets/ludusaviArtwork.ts`**:
    - Remove `import logo from "../../assets/steamgrid/ludusavi/logo.png";`.
    - Remove the `logo` property from the `LUDUSAVI_ARTWORK` object.
- **Modify `src/shortcutArtwork.ts`**:
    - Remove `logo: 2` from `LOCAL_ARTWORK_ASSET_TYPES`.
    - Remove `logo` from the `assetTypes` array in `applyLudusaviArtworkToShortcut`.
    - Remove the `if (steamAssetType === LOCAL_ARTWORK_ASSET_TYPES.logo ...)` block in `applyLocalArtworkAsset`.
    - Delete the `getCustomLogoPosition` function and its associated constants (`LOGO_POSITION_WAIT_ATTEMPTS`, `LOGO_POSITION_WAIT_MS`).

### 3. Test Updates
- **Modify `tests/test_shortcut_artwork_static.py`**:
    - Remove `logo.png` from `REQUIRED_ARTWORK`.
    - Delete the `test_ludusavi_logo_asset_preserves_transparency` function.
    - Update `test_shortcut_artwork_helper_uses_local_base64_and_steam_artwork_api` to remove expectations for:
        - `logo: 2`
        - `SaveCustomLogoPosition(appOverview`
        - `pinnedPosition: "BottomLeft"`
        - `nWidthPct: 50`
        - `nHeightPct: 50`

## Testing Strategy
1.  **Static Analysis**: Run `ruff check .` and `ty check py_modules/sdh_ludusavi/` (though this is JS/TS, the project protocol includes these).
2.  **Unit Tests**: Run `./run.sh uv run pytest tests/test_shortcut_artwork_static.py` to ensure the asset existence and code structure tests pass.
3.  **Manual Verification**: If possible, build the plugin and verify that the shortcut artwork is applied correctly without a logo overlay.
