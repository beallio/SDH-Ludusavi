# Plan - Frontend and Backend Refinements

Refine the SDH-ludusavi plugin to improve logging, user experience (UX), and state persistence.

## Problem Definition
1. **Frontend Logging:** Currently, `console.log` is only visible in the browser console. It should be possible to route these logs to the Decky Loader backend logger for easier debugging on the device.
2. **UX (Spinners):** The current "busy label" approach is functional but less intuitive than showing a spinner directly on the button being clicked.
3. **Selection Persistence:** The selected game in the dropdown resets every time the plugin is closed and reopened because it is not persisted in the backend settings.

## Proposed Solution

### 1. Backend Enhancements
- **Logging:** Expose a `log` callable that accepts a level and message. This will route logs to both the plugin's internal ring buffer (visible in the Log Modal) and the system-wide `decky.logger`.
- **Settings Persistence:** Add `selected_game` to the persistent settings JSON. Implement a `set_selected_game` callable to update this value.

### 2. Frontend Enhancements
- **Logger Utility:** Create a `log` utility that wraps `console.log` and also sends the message to the backend.
- **SpinnerButton Component:** Create a custom component that wraps `ButtonItem` and shows a `Spinner` (or `SteamSpinner`) when an operation is in progress.
- **State Synchronization:** Update the `Content` component to initialize `selectedGame` from settings and update the backend whenever the selection changes.

## Changes

### Backend (`py_modules/sdh_ludusavi/service.py`)
- Update `SDHLudusaviService` to:
    - Initialize `_selected_game`.
    - Include `selected_game` in `_load_state`, `_save_state`, and `get_settings`.
    - Implement `set_selected_game(game_name)`.
    - Implement `log(level, message, operation, game_name)`.

### Backend (`main.py`)
- Expose `log` and `set_selected_game` as asynchronous callables.
- In `Plugin.log`, call `decky.logger`.

### Frontend (`src/index.tsx`)
- Define new callables.
- Create `SpinnerButton` component.
- Refactor `Content`:
    - Use `selected_game` from fetched settings.
    - Replace `ButtonItem` with `SpinnerButton` where appropriate.
    - Ensure `onChange` of dropdown updates the backend.
    - Add frontend logs to the backend via the new `log` callable.

## Verification & Testing
1. **Logging:** Verify that logs triggered in the frontend appear in the "View Logs" modal and (if possible) in the backend logs.
2. **UX:** Verify that clicking Backup/Restore/Refresh shows a spinner within the button and disables other actions.
3. **Persistence:** Select a game, close the plugin, reopen it, and verify the selection is maintained.
