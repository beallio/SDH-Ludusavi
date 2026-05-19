# Fix Status Strip Gamescope Composition

## Problem Definition

The autosync status strip is registered as a Decky global component and portal-mounted
to `document.body`, but it still does not appear over a running game. The remaining
gap is the Gamescope composition mode: the SteamUI window needs to request
notification composition while the strip is visible so transparent SteamUI pixels can
show the foreground game behind it and input remains with the game.

## Architecture Overview

Keep the existing frontend-owned status strip and lifecycle state publisher. Add a
small local composition hook wrapper modeled on decky-pip's overlay approach:

- Locate SteamUI's composition hook through `findModuleChild`.
- Request `EUIComposition.Notification` only from a child component mounted while the
  strip is visible.
- Keep the existing portal into `document.body` for the strip DOM.
- Avoid direct calls to `SteamClient.Window.SetComposition` or
  `SteamClient.Overlay.SetOverlayState`.

OverLaid was reviewed as a second reference. It solves in-game overlays by having the
Decky frontend toggle a separate native process from the Python backend with
`DISPLAY=:0`. That validates that running-game overlays need a compositor-aware path,
but it is out of scope for this lightweight status strip unless the SteamUI
notification composition path proves insufficient on-device.

## Core Data Structures

- `UseUIComposition`: local type for the discovered SteamUI composition hook.
- `AutoSyncStatusComposition`: hidden React component that requests notification
  composition while mounted.
- Existing `AutoSyncStatusState`: continues to control strip visibility and status.

## Public Interfaces

No backend RPC, settings, package dependency, or user-facing preference changes.

The visible behavior should change only when an autosync status is active: the strip
should request notification composition so it can render over a running game without
capturing game input.

## Dependency Requirements

No dependency changes. Use `findModuleChild` and `EUIComposition` from the existing
`@decky/ui` package.

## Testing Strategy

1. Add a failing frontend static test requiring the composition hook wrapper and
   visible-only `EUIComposition.Notification` usage.
2. Implement the hook wrapper and child component.
3. Run targeted frontend static tests, TypeScript typecheck, Rollup build, Ruff,
   `ty`, and full pytest.
