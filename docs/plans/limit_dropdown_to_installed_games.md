# Limit Game Dropdown to Installed Games

## Problem Definition
The game dropdown in the SDH-ludusavi plugin currently shows all games that Ludusavi knows about, which includes:
1. Games found on the system (installed).
2. Games that have an existing backup in the backup directory (even if currently uninstalled).

The user wants to limit this list to only games that are currently installed on the system.

## Architecture Overview
The list of games is generated in the backend by `PyludusaviAdapter.refresh_statuses()` in `py_modules/sdh_ludusavi/ludusavi.py`. It currently performs a union of games found in a backup preview and games found in the backup list.

## Proposed Solution
Modify `PyludusaviAdapter.refresh_statuses()` to only use the keys from the backup preview results.

## Key Files & Context
- `py_modules/sdh_ludusavi/ludusavi.py`: Contains the `refresh_statuses` method.
- `tests/test_installed_games_only.py`: New test to verify the fix.

## Implementation Steps
1.  **Modify `py_modules/sdh_ludusavi/ludusavi.py`**:
    - Update `refresh_statuses` to only use `preview_games.keys()` for the `names` list.
2.  **Verify with Tests**:
    - Create `tests/test_installed_games_only.py` (after exiting plan mode).
    - Run the test to ensure only installed games are returned.
    - Run existing tests to ensure no regressions.

## Verification & Testing
- **Unit Test**: `tests/test_installed_games_only.py` will specifically check that a game with only a backup is excluded from the list.
- **Integration Test**: Run `./run.sh uv run pytest` to ensure all status and backup/restore logic still works as expected.
