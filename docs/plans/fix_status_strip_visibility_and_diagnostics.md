# Fix Status Strip Visibility and Diagnostics

## Problem Definition

The AutoSync Status Strip (notification notification) is not appearing over running games. This is likely due to a combination of:
1.  **Strategy Conflict:** Both `EUIComposition` (main DOM portal) and `BrowserView` (separate overlay) are being used simultaneously, which may cause layering or focus conflicts.
2.  **Uncertain BrowserView Attachment:** The `BrowserView` created via `SteamClient.BrowserView.Create` or `CreateBrowserView` may not be correctly attached to the active Gamescope display surface.
3.  **Silent Failures:** Critical discovery steps (finding the composition hook, creating the BrowserView) are not logged sufficiently to diagnose on-device failures.

## Architecture Overview

Consolidate the overlay mechanism to prioritize the `BrowserView` as the primary surface for in-game visibility while adding deep diagnostic logging.

- **Diagnostic Phase:** Add explicit `log` calls to `useUIComposition` discovery and `ensureAutoSyncStatusBrowserView` creation paths.
- **Consolidation:** 
    - Keep `BrowserView` as the primary overlay for running games.
    - Maintain the React DOM portal only as a fallback or for display within the QAM itself.
    - Ensure `BrowserView` methods are called in a safer sequence (Bounds -> Load -> Visible).
- **Hardening:**
    - Increase `SetWindowStackingOrder` to ensure it clears other SteamUI overlays.
    - Add a `SetTopmost` call if available in the runtime environment.

## Core Data Structures

- No new data structures. Use existing `AutoSyncStatusState` and `AutoSyncStatusBrowserView` types.

## Public Interfaces

- No backend RPC changes.
- Added logs will be visible in the "View Logs" modal within the plugin.

## Dependency Requirements

- No new dependencies.

## Testing Strategy

1.  **Static Tests:** Update `tests/test_frontend_static.py` to require the new diagnostic log strings and the corrected BrowserView initialization sequence.
2.  **Runtime Diagnostics:** Once deployed, the user can check "View Logs" to see:
    - `SDH-ludusavi:autosync_status: Composition hook found: <boolean>`
    - `SDH-ludusavi:autosync_status: Created BrowserView via GamepadUIMainWindowInstance: <boolean>`
    - `SDH-ludusavi:autosync_status: Created BrowserView via SteamClient fallback: <boolean>`

## Implementation Steps

1.  Modify `useUIComposition` in `src/index.tsx` to log whether the module child was successfully found.
2.  Update `ensureAutoSyncStatusBrowserView` to log exactly which creation path was taken.
3.  In `syncAutoSyncStatusBrowserView`, increase `SetWindowStackingOrder` to `2` (above standard notifications) and call `SetVisible` after a small microtask to allow the `LoadURL` to register.
4.  Update the `AutoSyncStatusIcon` and `renderAutoSyncStatusHtml` to ensure high contrast for the overlay.
5.  Update `tests/test_frontend_static.py` with invariants for the new logs and hardened BrowserView logic.
