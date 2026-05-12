# Plan - Auto-Sync Feedback and Hooks

## Problem Definition
The "Automatic Sync" feature in SDH-ludusavi is implemented in the backend but is not triggered by any automatic events in the frontend. Furthermore, there is insufficient logging to diagnose why sync might be skipped, and there are no toast notifications for automatic operations. 

Users also want:
1.  **Non-Steam Game Support:** Reliable matching for games added as non-Steam shortcuts.
2.  **Launch Interception (if possible):** Delaying the game launch while checking/restoring saves.
3.  **Refined Exit Logic:** Ensuring backups only happen if the local save is actually newer.

## Architecture Overview
1.  **Frontend Hook:** Register a listener for Steam app state changes to trigger sync.
2.  **App Identification:** Use `SteamClient.Apps.GetAppDetails` to get game names, which works for both Steam and non-Steam shortcuts in the library.
3.  **Sync Trigger:** Call `handle_game_start` and `handle_game_exit` RPC methods.
4.  **Toasts:** Provide real-time feedback via Decky toasts.
5.  **Logging:** Improve backend diagnostic logging.

## Proposed Solution

### 1. Backend Logging & Logic Refinement (`py_modules/sdh_ludusavi/service.py`)
- **Logging:** Upgrade key "skipped" logs to `info`. Add tracing to `_match_game`.
- **Exit Logic:** The backend already calls `_ludusavi().backup(game.name)`. We will ensure `ludusavi.py` uses Ludusavi's internal logic which avoids redundant backups if files haven't changed.
- **Start Logic:** We will keep the start logic conservative. Since Decky cannot easily *block* a launch without invasive Router hacks, we will perform the check/restore as quickly as possible upon the "Launching" state.

### 2. Frontend Game Hooks (`src/index.tsx`)
- **Listener:** Use `SteamClient.Apps.RegisterForAppRunningStateChanges`.
- **Game Name Lookup:** For every state change, fetch the game name using `SteamClient.Apps.GetAppDetails(unAppID)`. This name is passed to the backend, which already has normalization and fuzzy matching to bridge Steam names to Ludusavi names.
- **Timing:** 
    - When `bIsRunning` transitions to `true` (Launch): Trigger `handle_game_start`.
    - When `bIsRunning` transitions to `false` (Exit): Trigger `handle_game_exit`.
- **Toasts:**
    - On start: "Auto-sync: Checking [Game Name]..."
    - On exit: "Auto-sync: Backing up [Game Name]..."
    - On result: Show result summary (Restored, Backed Up, or Skip reason if relevant).

### 3. Backend Matching Improvements (`py_modules/sdh_ludusavi/service.py`)
- Improve `_match_game` to better handle non-Steam names that might have suffixes or different casing.

## Changes

### Backend (`py_modules/sdh_ludusavi/service.py`)
- Increase log levels for auto-sync decisions.
- Add debug logging for matching steps.

### Frontend (`src/index.tsx`)
- Define `handleGameStartCall` and `handleGameExitCall`.
- Register the app state listener in `definePlugin`.
- Add toast logic for auto-sync.

## Verification & Testing
- **TDD:** Add test cases for refined log levels and matching logic in `tests/test_service.py` and `tests/test_matching.py`.
- **Manual:** Verify toasts and logs when starting/stopping games in the Decky environment.
- **Build:** Ensure `pnpm run build` succeeds.
