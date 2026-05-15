# Plan - Bundled Shortcut Artwork

## Problem Definition

The plugin-managed Ludusavi launcher shortcut currently has no custom Steam artwork.
The shortcut should receive fixed Ludusavi artwork without any runtime SteamGridDB
lookup, image download, or API key usage. Artwork must keep working offline after the
plugin has been built and installed.

## Architecture Overview

- Store the selected SteamGridDB Ludusavi artwork as committed PNG files under
  `assets/steamgrid/ludusavi/`.
- Import those images from TypeScript so Rollup emits hashed assets into `dist/assets/`.
- Add a frontend artwork helper that fetches the local Decky asset URL, converts it to
  base64 with `FileReader`, clears existing custom artwork, and calls Steam's custom
  artwork API.
- Integrate the helper only into the plugin-managed shortcut path in
  `src/ludusaviLauncher.ts`; user-created `Ludusavi` shortcuts remain untouched.
- Preserve the current launch flow if artwork application fails: log the failure and
  continue launching Ludusavi.

## Core Data Structures

- `LUDUSAVI_ARTWORK`: manifest of bundled asset URLs keyed by `grid_p`, `grid_l`,
  `hero`, and `logo`.
- `LOCAL_ARTWORK_ASSET_TYPES`: frontend mapping from manifest keys to Steam artwork
  type IDs: `grid_p=0`, `hero=1`, `logo=2`, `grid_l=3`.
- `LauncherShortcutState`: existing shortcut state continues to distinguish managed
  plugin shortcuts from user-created shortcuts.

## Public Interfaces

- No new backend RPCs or settings.
- Extend frontend Steam ambient types for `SetCustomArtworkForApp`,
  `ClearCustomArtworkForApp`, shortcut detection, and custom logo position APIs.
- Add frontend-only functions for applying one bundled asset and all Ludusavi shortcut
  artwork.

## Dependency Requirements

- No new Python or npm dependencies.
- Development/build work may download image files from SteamGridDB game `5360951`, but
  runtime code must use only committed local files.
- Do not use or copy any SteamGridDB Decky plugin API key.

## Testing Strategy

- Add static tests that assert the required PNG files exist, are non-empty, and include
  alpha for `logo.png`.
- Add static tests that reject runtime SteamGridDB URLs/API keys and backend download
  helper usage for artwork.
- Add frontend source tests for asset type mapping, local base64 conversion, clear-then-
  set behavior, managed-shortcut-only integration, and default logo position values.
- Update packaging tests to ensure Rollup-emitted `dist/assets/*.png` files are included
  in `out/SDH-ludusavi.zip`.
- Validate with `./run.sh uv run pytest`, `pnpm run typecheck`, `pnpm run build`, and
  `./run.sh uv run python scripts/package_plugin.py`.
