# Plan: Refine Ludusavi Launcher Logic

## Problem Definition
The current Ludusavi launcher logic always creates and manages (hides) its own shortcut. The user wants to prioritize any existing, manually created "Ludusavi" shortcut. If found, it should be launched as-is without being hidden.

## Architecture Overview
The frontend `ludusaviLauncher.ts` handles shortcut management and launching. We need to extend this to:
1. Search the Steam AppStore for a shortcut named "Ludusavi".
2. If found, launch it via its native AppID/GameID.
3. If not found, continue with the current plugin-managed (hidden) shortcut logic.

## Core Data Structures
No new core data structures, but `AppStoreGlobal` and `SteamAppOverview` in `src/types/steam-globals.d.ts` will be updated to support searching.

## Public Interfaces
Modified internal function `ensureLudusaviShortcut` in `src/ludusaviLauncher.ts` to return whether the shortcut is "managed" (plugin-created) or "external" (user-created).

## Implementation Plan

### 1. Update Types
- Update `src/types/steam-globals.d.ts`:
    - Add `m_strDisplayName` and `m_unAppID` to `SteamAppOverview`.
    - Add `m_mapAppOverview` to `AppStoreGlobal` to allow iteration/searching.

### 2. Implement Shortcut Search
- Add `findUserLudusaviShortcut()` in `src/ludusaviLauncher.ts`:
    - Iterates over `appStore.m_mapAppOverview`.
    - Returns the first entry where `m_strDisplayName === "Ludusavi"`.

### 3. Refactor Launch Logic
- Modify `ensureLudusaviShortcut()` to first call `findUserLudusaviShortcut()`.
- Return a new interface: `{ appId: number; gameId: string; managed: boolean }`.
- Modify `launchLudusavi()`:
    - If `!managed`, directly call `RunGame` using the user's shortcut details.
    - If `managed`, proceed with the current logic (setting EXE, launch options, hiding, etc.).

## Testing Strategy
- Manual verification on the Steam Deck (or fake deck environment if available).
- Log statements to confirm which path is taken (User Shortcut vs. Plugin Shortcut).
- Verify that user shortcuts are NOT hidden by the plugin.

## Verification
- Confirm that if a "Ludusavi" non-Steam game exists, it is launched when clicking the "Launch" button in the plugin.
- Confirm that if no such game exists, the plugin creates its own hidden shortcut and launches Ludusavi.
