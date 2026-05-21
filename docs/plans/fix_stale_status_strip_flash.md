# Fix Stale Status Strip Flash

## Problem Definition

The autosync BrowserView can briefly show stale `GAME SAVE UP TO DATE` content before
the new `VERIFYING GAME SAVE` document loads on game start or exit. The BrowserView
is reused, and `LoadURL(dataUrl)` is asynchronous, so showing the BrowserView
immediately after `LoadURL` can expose the previous document.

## Architecture Overview

Keep the BrowserView-only status strip and existing lifecycle RPC flow. Hide the
BrowserView before loading every visible status, then reveal it after a short guarded
delay so the previous document cannot flash. For lifecycle verification publishes,
destroy the reused BrowserView first so game start and game exit load
`VERIFYING GAME SAVE` into a fresh surface.

## Core Data Structures

- `autoSyncStatusShowTimeoutID`: pending delayed BrowserView show timer.
- `autoSyncStatusShowGeneration`: monotonically increasing guard that invalidates
  stale show callbacks.
- `AUTO_SYNC_STATUS_SHOW_DELAY`: named reveal delay in milliseconds.
- `shouldResetStatusStripSurfaceBeforeVerification`: lifecycle start/exit guard for
  fresh verification surfaces.

## Public Interfaces

No backend RPC, settings, notification, or payload interfaces change. The first
visible lifecycle state remains `VERIFYING GAME SAVE`; `GAME SAVE UP TO DATE` remains
a post-verification result.

## Dependency Requirements

None.

## Testing Strategy

- Add frontend static coverage proving `SetVisible(false)` happens before `LoadURL`
  for visible BrowserView updates.
- Verify delayed reveal uses `AUTO_SYNC_STATUS_SHOW_DELAY` and a generation guard.
- Verify pending show timers clear during sync, hide, destroy, and plugin dismount.
- Verify lifecycle start/exit `checking` destroys the prior BrowserView surface before
  publishing the verification document.
- Run the standard `./run.sh` Python, type, frontend, and packaging checks.
