# Plan - Fix Visible Steam Shortcut

Ensure the reusable Steam shortcut for the Ludusavi launcher is properly hidden from the Steam library.

## Problem Definition
The current hiding logic is not effectively hiding the shortcut on some Steam client versions, causing it to appear in the user's library.

## Architecture Overview
The frontend interacts with `SteamClient.Apps` to hide shortcuts. The current implementation tries a few methods but returns early after the first one is found, and might be using suboptimal IDs for certain methods.

## Proposed Solution
1.  **Try All Methods**: Update `hideShortcutIfSupported` to try every known hiding method instead of returning early.
2.  **ID Versatility**: Pass both the 32-bit `appId` and the 64-bit `gameId` to the methods that expect them.
3.  **Manual ID Calculation**: Implement a fallback to calculate the 64-bit GameID from the 32-bit AppID if `appStore` doesn't provide it.
4.  **Add `SetAppIsHidden`**: Add this common method to the ambient declarations and implementation.
5.  **Logging**: Add `console.log` statements to trace which methods are detected and called.

## Key Files & Context
- `src/ludusaviLauncher.ts`: Hiding logic.
- `src/types/steam-globals.d.ts`: Ambient declarations.

## Phased Implementation Plan
- **Phase 1: Update Types**
    - T1: Add `SetAppIsHidden` and potentially other variants to `SteamClientGlobal`.
- **Phase 2: Refactor Hiding Logic**
    - T2: Refactor `hideShortcutIfSupported` to be exhaustive and include logging.
    - T3: Implement `calculateGameId(appId: number): string`.
- **Phase 3: Verification**
    - V1: Run `npm run build` to ensure integrity.

## Git Strategy
- Branch: `fix/hidden-shortcut-visibility`
- Commit: `fix(ui): improve shortcut hiding logic to handle different Steam client versions`

## Verification & Testing
- Run `npm run build`.
- Manual verification: Trigger a launch and verify the shortcut is hidden. Check browser console logs for the hiding method trace.
