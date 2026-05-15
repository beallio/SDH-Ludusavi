# Fix Shortcut Artwork Application

## Problem Definition

The bundled Ludusavi shortcut artwork feature is not producing visible artwork,
and the Decky log does not show artwork-specific diagnostics. The current
frontend artwork path logs only to the browser console and clears custom artwork
before setting it, even though the managed shortcut can be newly created and
`SetCustomArtworkForApp` should overwrite existing custom artwork.

## Architecture Overview

Keep the fix in SDH-owned TypeScript. The launcher should pass the existing
frontend `log` RPC wrapper into the shortcut artwork helper so artwork events
reach the backend log file. The artwork helper should apply each bundled PNG
directly through Steam's custom artwork setter and preserve best-effort launch
behavior if artwork application fails.

## Core Data Structures

- `LudusaviArtworkAsset`: the local asset keys `grid_p`, `grid_l`, `hero`, and
  `logo`.
- `ArtworkLogger`: a frontend logging callback with the same shape as the
  existing panel `log` helper.

## Public Interfaces

- `launchLudusavi(command, options?)` accepts an optional logger.
- `applyLudusaviArtworkToShortcut(params)` accepts a logger and logs per-asset
  start, success, and failure events.
- `ClearCustomArtworkForApp` is not used unless future runtime evidence shows
  `SetCustomArtworkForApp` does not overwrite cleanly.

## Dependency Requirements

No new dependencies.

## Testing Strategy

Add static tests that fail until the artwork helper:

- stops calling `ClearCustomArtworkForApp`;
- keeps using `SetCustomArtworkForApp` for bundled local PNG assets;
- routes artwork logs through the backend logging path;
- includes shortcut app ID and asset type in failure logs.

Validate with focused Python tests, TypeScript typecheck, and the repository
quality gate.
