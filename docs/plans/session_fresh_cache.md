# Session-Fresh Cache Strategy

## Problem Definition
The plugin caches the list of Ludusavi games in `sdh_ludusavi.json`. While this allows for immediate UI rendering, the cache can become stale if games are uninstalled or if Ludusavi's configuration changes while the plugin isn't active. Currently, the plugin trusts the disk-loaded cache until a manual refresh is triggered, leading to "ghost" games in the dropdown.

## Architecture Overview
The cache is managed by `SDHLudusaviService` in `py_modules/sdh_ludusavi/service.py`. It populates `self._games` from the state file during initialization.

## Proposed Solution
Implement a "session-fresh" policy:
1.  Add a `_refreshed_once` boolean flag to `SDHLudusaviService`, initialized to `False`.
2.  Update `refresh_games(force=False)` to ignore the cache and perform a scan if `_refreshed_once` is `False`.
3.  Update `_match_game` to trigger a refresh if `_refreshed_once` is `False`.
4.  Set `_refreshed_once = True` inside `_refresh_statuses_unlocked`.

This ensures that the first time the plugin is used after a boot or reload, it performs a real scan to synchronize with the system state. Subsequent uses in the same session remain fast.

## Key Files & Context
- `py_modules/sdh_ludusavi/service.py`: Core logic for game list management and caching.

## Implementation Steps
1.  **Modify `py_modules/sdh_ludusavi/service.py`**:
    - Add `self._refreshed_once = False` to `__init__`.
    - Update `refresh_games` to check `self._refreshed_once`.
    - Update `_match_game` to check `self._refreshed_once`.
    - Set `self._refreshed_once = True` in `_refresh_statuses_unlocked`.
2.  **Verify with Tests**:
    - Add a test case to `tests/test_service.py` verifying that the first `refresh_games(force=False)` call triggers the adapter even if a cache exists.
    - Verify that a second call uses the cache.

## Verification & Testing
- **Unit Test**: Expand `tests/test_service.py` to cover session-level cache invalidation.
- **Manual Verification**: Restart the plugin (or the Deck) after uninstalling a game; the game should disappear from the dropdown on the first open without needing a manual refresh.
