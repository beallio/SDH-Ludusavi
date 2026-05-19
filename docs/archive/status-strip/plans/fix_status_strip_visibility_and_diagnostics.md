# Fix Status Strip Provenance and Diagnostics

## Problem Definition

The AutoSync status strip is still not proven visible over a running game, and recent
diagnostic logs can be confused with real lifecycle autosync. The next fix must make
each status update's provenance explicit before changing the overlay strategy again.

## Architecture Overview

Keep the implementation frontend-owned and SteamUI-only, but separate diagnostics
from lifecycle autosync:

- Add a source label to every status publish: `debug_button`, `lifecycle_start`,
  `lifecycle_exit`, `rpc_result`, `timeout`, or `hide`.
- Log source, game name, app ID, tracked state, result status, status, visibility,
  and diagnostic surface mode for every status change.
- Log before and after the `handle_game_start` and `handle_game_exit` RPC calls.
- Keep success/progress autosync out of Decky toasts; only failures use toasts.
- Keep BrowserView, React portal, and combined diagnostic modes available from the
  debug button with unmistakable labels and colors.
- Avoid crash-prone runtime paths: no `EUIComposition.Overlay`, no BrowserView
  `AddGlass` or `NotifyUserActivation`, and no hooks outside mounted components.

## Core Data Structures

- `AutoSyncStatusSource`: provenance label for status changes.
- `AutoSyncStatusSurfaceMode`: `browserview`, `react`, or `both`.
- `AutoSyncStatusState`: status, visibility, source, optional game/app/tracked/result
  metadata, and active diagnostic surface mode.
- `AutoSyncStatusBrowserView`: minimal BrowserView runtime interface.

## Public Interfaces

- No backend RPC changes.
- The existing debug button cycles BrowserView-only, React-only, and both-surfaces
  diagnostics. Logs identify these as `debug_button` updates.

## Dependency Requirements

- No new dependencies.

## Testing Strategy

1. Update `tests/test_frontend_static.py` with static invariants for source labels,
   lifecycle/RPC logging, failure-only autosync toasts, BrowserView creation order,
   React portal fallback, and debug mode cycling.
2. Run the targeted frontend static tests and TypeScript typecheck.
3. Run Rollup build and full Python test suite after implementation.

## Implementation Steps

1. Add source and surface-mode types plus provenance logging helpers.
2. Replace the temporary full-screen debug styling with the bottom strip React portal.
3. Prefer `GamepadUIMainWindowInstance.CreateBrowserView`, then fall back to
   `SteamClient.BrowserView.Create`.
4. Wire lifecycle start/exit and RPC results through explicit source metadata.
5. Replace the debug button with a three-mode diagnostic cycle.

## Follow-up From Device Logs

The Steam Deck log from version `0.1.0+37d2571` proved lifecycle detection works and
showed two remaining frontend defects:

- `GamepadUIMainWindowInstance.CreateBrowserView` returned a wrapper object whose
  method-bearing view is under nested fields such as `m_browserView`, so the status
  code must normalize the wrapper before requiring `LoadURL`, `SetBounds`, and
  `SetVisible`.
- Backend `skipped` results with `reason: "local_current"` were rendered as
  `BACKUP: NEEDED`; those should render as up to date.

Add static regressions for both behaviors and keep BrowserView-only diagnostics from
rendering the React surface so the three debug modes remain distinct.
