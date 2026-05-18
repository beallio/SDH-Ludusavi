# Custom Autosync Status Strip UI

## Problem Definition

Implement a compact SteamOS-style status strip for automatic backup and restore
feedback. The strip should replace routine autosync progress/result toasts and keep
native Decky toasts only for failures.

## Architecture Overview

The change is frontend-only. Add a portal-mounted status strip component to
`src/index.tsx` and publish state from the existing lifecycle handlers around
`handle_game_start` and `handle_game_exit`.

Do not add backend events, dependencies, CSS pipeline changes, or Steam overlay
composition changes.

## Core Data Structures

- `AutoSyncStatusKind`: visual status enum for backing up, restoring, up to date,
  needed, and error.
- `AutoSyncStatusState`: current visible strip state.
- `autoSyncStatusListeners`: local listener set that lets lifecycle handlers publish
  status updates to the mounted portal component.

## Public Interfaces

No public backend interface changes. The frontend notification preferences panel should
drop autosync progress/result toast toggles because those routine states are no longer
toasts.

The user-visible autosync notification contract becomes:

- `BACKUP: RESTORING` during automatic restore checks on game start.
- `BACKUP: BACKING UP` during automatic backup checks on game exit.
- `BACKUP: UP TO DATE` after successful autosync.
- `BACKUP: NEEDED` for visible skipped states.
- `BACKUP: ERROR` plus one Decky failure toast on failure.

## Dependency Requirements

Use the existing `react-icons` dependency. Import FA6 icons from `react-icons/fa6`.

## Testing Strategy

1. Add failing frontend static tests for portal rendering, strip style invariants,
   icons, autosync lifecycle publishing, failure-only toasts, and the absence of
   Steam overlay composition calls.
2. Implement the minimal frontend changes to pass those tests.
3. Run targeted frontend static tests, TypeScript typecheck, Rollup build, Ruff,
   `ty`, and the full pytest suite.
