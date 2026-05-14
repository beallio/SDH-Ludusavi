# Fix Non-Installed Games in Dropdown

## Problem Definition
The game dropdown still shows some games that the user considers "not installed". Currently, the plugin uses the output of `ludusavi backup --preview` to populate the list. However, Ludusavi may include games in this preview even if no files or registry entries were found (e.g., custom games with missing paths or games in the manifest that Ludusavi explicitly scans but doesn't find).

## Architecture Overview
The filtering happens in `PyludusaviAdapter.refresh_statuses()` in `py_modules/sdh_ludusavi/ludusavi.py`. It currently uses all keys from the `preview` output.

## Proposed Solution
Modify `refresh_statuses` to filter the `preview_games` dictionary, keeping only those games that have a non-empty `files` or `registry` collection.

## Key Files & Context
- `py_modules/sdh_ludusavi/ludusavi.py`: Implementation of `refresh_statuses`.
- `tests/test_installed_games_only.py`: Unit test to verify the fix.

## Implementation Steps
1.  **Modify `py_modules/sdh_ludusavi/ludusavi.py`**:
    - Update `refresh_statuses` to filter `preview_games` by checking `bool(game.get("files")) or bool(game.get("registry"))`.
2.  **Update `tests/test_installed_games_only.py`**:
    - Add a test case for an "Empty Game" (present in preview but with no files/registry) and verify it is excluded.
3.  **Verification**:
    - Run the updated unit test.
    - Run all existing tests to ensure no regressions.

## Verification & Testing
- **Unit Test**: `tests/test_installed_games_only.py` will be expanded to cover the empty collections case.
- **Manual Verification**: (In a real environment) Clicking "Refresh Games" should now remove uninstalled games from the dropdown.
