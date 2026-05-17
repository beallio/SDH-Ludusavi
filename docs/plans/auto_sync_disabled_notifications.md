# Auto-Sync Disabled Notifications

## Problem Definition

Tracked game start and exit events currently show automatic sync notifications before the
frontend receives the backend result. When Automatic Sync is disabled, the backend returns
`auto_sync_disabled`, but the frontend has already shown the initial "Checking saves..." or
"Backing up saves..." toast for tracked games.

## Architecture Overview

The Steam lifecycle watcher is defined outside the React panel state in `src/index.tsx`,
while the Automatic Sync toggle state is loaded and changed inside `Content`. The fix needs
a small module-level mirror of the persisted setting so lifecycle handlers can suppress
automatic sync toasts without moving the watcher into React state.

Backend lifecycle calls should remain unconditional. The backend remains the source of truth
for skip reasons and operation logging.

## Core Data Structures

- `autoSyncNotificationsEnabled`: module-level boolean mirror of
  `Settings.auto_sync_enabled`, defaulting to `false`.
- `Settings.auto_sync_enabled`: persisted backend setting already returned by
  `get_settings`, `set_auto_sync_enabled`, and `set_selected_game`.

## Public Interfaces

No backend RPC, Python API, or user-facing settings interface changes are required. Manual
Force Backup and Force Restore remain available and keep their existing notifications when
Automatic Sync is disabled.

## Dependency Requirements

No dependency changes are required.

## Testing Strategy

- Add a frontend static regression test proving lifecycle start and exit toasts require both
  a tracked game and enabled auto-sync notifications.
- Prove `loadInitial`, `toggleAutoSync`, and `onGameChange` keep the module-level mirror in
  sync with backend settings.
- Prove `handleGameStartCall` and `handleGameExitCall` remain present, preserving backend
  skip logging while Automatic Sync is disabled.
- Run targeted frontend static tests and the full validation suite before commit.
