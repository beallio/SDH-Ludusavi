# Implementation Plan: Parallelize Artwork Application

## Problem Definition
The function `applyLudusaviArtworkToShortcut` in `src/shortcutArtwork.ts` applies four different artwork assets (grid_p, grid_l, hero, logo) to the Ludusavi shortcut. Currently, it iterates over these assets using a `for...of` loop with an `await` on each `applyLocalArtworkAsset` call. This sequential execution causes unnecessary delay during the launch flow because each artwork application is independent.

## Architecture Overview
We will refactor the `applyLudusaviArtworkToShortcut` function to execute all asset applications concurrently using `Promise.all`.

1. Map over the `assetTypes` array to create an array of Promises returned by `applyLocalArtworkAsset`.
2. Wrap the mapped array in `Promise.all`.
3. Wait for all promises to resolve.

This will reduce the total time taken to apply artwork to roughly the duration of the single longest network/disk/API operation, rather than the sum of all four operations.

## Core Data Structures
No new data structures.

## Public Interfaces
- `src/shortcutArtwork.ts::applyLudusaviArtworkToShortcut`: Signature remains identical. Return type is still `Promise<void>`.

## Dependency Requirements
- None.

## Testing Strategy
- Compile the frontend to ensure no TypeScript regressions: `pnpm run typecheck`.
- Verify the behavior in `tests/test_shortcut_artwork_static.py` (if any TypeScript/JS tests or static analysis exist).
- During runtime, applying the artwork via `SteamClient.Apps.SetCustomArtworkForApp` should not exhibit race conditions when called rapidly for the same `appId` with different `assetType`s. Steam's backend should handle rapid sequential dispatches.