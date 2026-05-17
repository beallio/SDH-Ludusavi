# Fast QAM Open via Installed Games Caching

## Objective
Eliminate the unconditional 3-5 second Ludusavi refresh on the first Quick Access Menu (QAM) open after a Deck reboot. Improve user experience by safely persisting the game list cache across reboots and utilizing the Steam Deck's frontend APIs to invalidate the cache only when the installed games list changes.

## Background & Motivation
Currently, `SDH-ludusavi` caches the games list in `state.json` but sets `_refreshed_once = False` upon the Python backend's initialization. This forces a full `ludusavi backups --preview` scan on the first QAM open. While subsequent opens use the cache and are fast, the initial delay is noticeable. 

If we simply trust the `state.json` cache on startup, we risk showing stale data if games were installed or uninstalled while the Deck was offline or while the backend was restarted. 

## Proposed Solution
We will track the list of currently installed Steam games. The frontend has rapid access to Steam's list of installed apps. It can extract the App IDs, sort them, and send this list as a string to the backend during the `refresh_games` call.

1.  **Frontend App ID Tracking:** On QAM mount, the frontend uses `SteamClient.Apps.GetInstalledApps()` to fetch the currently installed apps, extracts the `appid` from each, sorts them numerically, and joins them into a comma-separated string (e.g., `"220,730,4000"`).
2.  **Backend Cache Validation:** The backend stores this `installed_app_ids` string in its `state.json` alongside the game cache. When `refresh_games(force=False, installed_app_ids)` is called:
    *   If `installed_app_ids` matches the saved string, the backend **instantly returns the cached game list** (even on the first open after a reboot).
    *   If `installed_app_ids` differs (or `force=True`), the backend performs the slow `refresh_statuses` scan, updates the cache, updates its stored `installed_app_ids`, and saves `state.json`.

**Trade-offs:** 
As discussed with the user, this relies on Steam's app tracking. Non-Steam games (like native Flatpaks not added to Steam) won't alter the `SteamClient.Apps` list. In these edge cases, the user can use the manual "Refresh Games" button to trigger a full scan.

## Detailed Specification & Implementation Steps

### 1. Frontend: Types Update
*   **File:** `src/types/steam-globals.d.ts`
*   **Changes:**
    *   Add `GetInstalledApps?(): any[] | Promise<any[]>;` to the `SteamClientGlobal["Apps"]` interface.

### 2. Frontend: App ID Extraction & API Call
*   **File:** `src/index.tsx`
*   **Changes:**
    *   Update `refreshGamesCall` signature: `callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>("refresh_games")`.
    *   Implement `getInstalledAppIdsString()` function:
        *   Calls `SteamClient.Apps.GetInstalledApps()`.
        *   Maps the result to extract `appid` (handling potential promise/array structures securely).
        *   Filters out invalid IDs, sorts them numerically to ensure consistent order.
        *   Joins the sorted IDs into a comma-separated string.
    *   In `loadInitial` and `refreshGames` (manual trigger), call this function and pass the resulting string to `refreshGamesCall`.

### 3. Backend: State Management
*   **File:** `py_modules/sdh_ludusavi/service.py`
*   **Changes:**
    *   Add `self._installed_app_ids: str | None = None` and `self._pending_installed_app_ids: str | None = None` to `__init__`.
    *   In `_load_state`, load `self._installed_app_ids = data.get("installed_app_ids")`.
    *   In `_save_state`, save `data["installed_app_ids"] = self._installed_app_ids`.

### 4. Backend: Refresh Logic
*   **File:** `py_modules/sdh_ludusavi/service.py`
*   **Changes:**
    *   Update `refresh_games(self, force: bool = False, installed_app_ids: str | None = None) -> dict[str, object]`.
    *   Determine if a refresh is needed: `force` is True, OR `installed_app_ids` is provided and differs from `self._installed_app_ids`, OR `not self._games`.
    *   Remove the strict reliance on `self._refreshed_once` to block using the cache on first boot.
    *   If a refresh is required, set `self._pending_installed_app_ids = installed_app_ids` before calling `_run_locked(...)`.
    *   In `_refresh_statuses_unlocked`, if `self._pending_installed_app_ids` is set, transfer it to `self._installed_app_ids` right before calling `_save_state()`.

### 5. Backend: Unit Tests
*   **File:** `tests/test_service.py`
*   **Changes:**
    *   Add a test verifying that `refresh_games(force=False, installed_app_ids="1,2,3")` updates the stored app IDs and saves state.
    *   Add a test verifying that a subsequent call with `installed_app_ids="1,2,3"` returns the cache without calling the ludusavi adapter.
    *   Add a test verifying that a call with `installed_app_ids="1,2,3,4"` triggers a fresh adapter call.

## Verification & Testing
1.  Run `ty check py_modules/sdh_ludusavi/` and `ruff check .`
2.  Run `pytest` to ensure all existing and new cache logic tests pass.
3.  Deploy to Deck and verify via logs that the very first QAM open returns instantly by matching the app ID list.
4.  Install a small free game from Steam and verify the next QAM open triggers a background refresh.