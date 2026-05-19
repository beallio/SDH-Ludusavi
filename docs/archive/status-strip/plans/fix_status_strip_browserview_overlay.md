# Fix Status Strip BrowserView Overlay

## Problem Definition

The status strip still does not display during game run or exit. The previous fixes
kept the visible strip in SteamUI DOM and requested notification composition, but a
running game can still hide or bypass that DOM surface in practice.

## Architecture Overview

Keep the React global component as a fallback and add a BrowserView-backed overlay
surface driven by the same status publisher:

- `publishAutoSyncStatus` creates or updates a small BrowserView.
- The BrowserView loads a self-contained `data:text/html` status strip.
- The BrowserView is positioned at the bottom of the Gamepad UI viewport.
- The BrowserView is hidden on idle and destroyed during plugin dismount.

This follows the same overlay class used by decky-pip, but uses a local HTML strip
instead of a remote video page. OverLaid's separate native process approach remains a
fallback only.

## Core Data Structures

- `AutoSyncStatusBrowserView`: minimal interface for the runtime BrowserView object.
- `ensureAutoSyncStatusBrowserView`: creates the overlay surface from
  `Router.WindowStore.GamepadUIMainWindowInstance.CreateBrowserView` when available,
  or `SteamClient.BrowserView.Create` as fallback.
- `syncAutoSyncStatusBrowserView`: writes the current status HTML, bounds, and
  visibility.

## Public Interfaces

No user-facing setting, backend RPC, or package dependency changes.

## Dependency Requirements

No dependency changes. The fix uses runtime SteamUI/Decky APIs already present in the
Decky frontend environment.

## Testing Strategy

1. Add a failing frontend static test requiring BrowserView creation, data URL
   rendering, bounds updates, visibility updates, and dismount cleanup.
2. Implement the BrowserView status surface and wire it to the existing publisher.
3. Run targeted frontend tests, TypeScript, Rollup build, Ruff, `ty`, and full pytest.
