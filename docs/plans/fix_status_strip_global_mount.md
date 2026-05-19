# Fix Autosync Status Strip Runtime Mount

## Problem Definition

The autosync status strip can fail to appear while launching or playing a configured
game because it is mounted inside the plugin panel content tree. That tree is tied to
the Quick Access Menu/plugin panel lifecycle, so it is not a reliable host for UI that
must show outside the panel.

## Architecture Overview

Register the status strip as a Decky global component with
`routerHook.addGlobalComponent`, keep the existing `createPortal(..., document.body)`
rendering strategy, and unregister it on plugin dismount. Store the latest published
strip state at module scope so a lifecycle event that fires before the global component
effect subscribes is not lost.

## Core Data Structures

- `AUTO_SYNC_STATUS_COMPONENT`: stable global component key.
- `currentAutoSyncStatusState`: module-level latest strip state used to initialize the
  global component.
- `autoSyncStatusListeners`: existing listener set for mounted strip updates.

## Public Interfaces

No backend RPC, settings, or dependency changes.

## Testing Strategy

- Update frontend static tests to require `routerHook.addGlobalComponent` and
  `routerHook.removeGlobalComponent`.
- Assert the strip is not mounted inside the plugin `content` tree.
- Assert module-level status state is updated before listener fan-out and used as the
  component initial state.
- Run frontend static tests, TypeScript typecheck, Rollup build, Ruff, `ty`, and full
  pytest before commit.
