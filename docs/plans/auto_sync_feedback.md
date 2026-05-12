# Plan - Auto-Sync Feedback and Hooks (Refined)

## Problem Definition
The "Automatic Sync" feature needs to be more targeted and informative:
1.  **Tracked Game Filtering:** Toast notifications should only appear for games Ludusavi is actually managing.
2.  **Backup if Newer:** On game exit, only perform a backup if the local save is actually newer/different than the existing backup.
3.  **Launch Feedback:** Perform check/restore immediately on launch.

## Architecture Overview
1.  **Frontend Hook:** Register a listener for Steam app state changes.
2.  **Frontend Tracking:** Cache a list of tracked AppIDs and Game Names in the frontend to quickly filter toast notifications.
3.  **Backend Logic:** 
    - `handle_game_start`: Restore only if backup is newer.
    - `handle_game_exit`: Backup only if local save is newer (via backup preview).
4.  **Toasts:** Inform the user when operations start and finish, but only for tracked games.

## Proposed Solution

### 1. Backend Logic Refinement (`py_modules/sdh_ludusavi/service.py`)
- **`handle_game_exit`**: Before running the actual backup, perform a backup preview using `_ludusavi().backup(game.name, preview=True)`.
    - Check the `overall` status or individual game `change` status.
    - Only proceed with the full backup if the status is `New` or `Different`.
    - Log "Skipping backup: local save is already current" if no changes detected.

### 2. Frontend Hook & Filtering (`src/index.tsx`)
- **State Management:** Add a global `trackedGames` state (sets of AppIDs and Names).
- **Initialization:** Populate these sets during `loadInitial` and `applyRefreshResult` by extracting them from the `games` list returned by the backend.
- **Hook Logic:**
    - In `RegisterForAppRunningStateChanges`:
        - Immediately check if the `unAppID` or `gameName` is in the tracked sets.
        - Only show the "Checking..." or "Backing up..." toast if tracked.
        - Always call the backend (to ensure logs are updated and fuzzy matching is handled), but the *initial* toast is filtered.

## Changes

### Backend (`py_modules/sdh_ludusavi/service.py`)
- Refine `handle_game_exit` to include the "newer" check.
- Update `handle_game_start` to ensure clear logging of recency results.

### Frontend (`src/index.tsx`)
- Implement `trackedAppIDs` and `trackedNames` sets.
- Update logic to filter initial toasts.
- Refine `summarizeOperationResult` to handle "local_current" on exit.

## Verification & Testing
- **TDD:** Add a test case in `tests/test_service.py` for the refined exit logic (skipping backup if no changes).
- **Manual:** Verify that starting/exiting a tracked game shows toasts, but an untracked game (like a random utility) does not.
- **Build:** Ensure `pnpm run build` succeeds.
