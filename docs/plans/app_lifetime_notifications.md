# App Lifetime Notifications

## Problem Definition

`src/index.tsx` currently watches game start and exit by polling
`Router.MainRunningApp` every second. That keeps a timer active during gameplay even
when Steam exposes app lifetime events through Decky's `SteamClient.GameSessions`
surface. The plugin should use the event API when available and reserve polling for
older or incomplete runtime contexts.

## Architecture Overview

The frontend lifecycle detector will use
`SteamClient.GameSessions.RegisterForAppLifetimeNotifications` as the primary source
for game start and exit events. Each notification is resolved to an app id and display
name, then forwarded to the existing `handleAppStart` and `handleAppExit` functions.

The existing sync behavior stays unchanged:

- `handle_game_start` and `handle_game_exit` remain backend RPCs.
- Auto-sync disabled is still enforced by the backend.
- Start and exit pre-toasts remain gated by `tracked && autoSyncNotificationsEnabled`.
- Manual Force Backup and Force Restore remain available when auto-sync is disabled.

If the lifetime API is missing, the plugin will fall back to the current
`Router.MainRunningApp` interval watcher.

## Core Data Structures

- `AppLifetimeNotification`: frontend shape containing `unAppID`, `nInstanceID`, and
  `bRunning`.
- `RunningSession`: frontend-only record containing string `appID` and `name`.
- `activeSessions: Map<number, RunningSession>`: stores started sessions by Steam
  instance id so exit notifications can be resolved after Router state has already
  cleared.

`unAppID` is not treated as authoritative for non-Steam games because Decky's installed
types document that Steam may report `0` for non-Steam shortcuts.

## Public Interfaces

No backend RPC, settings, or user-facing settings change.

Frontend runtime dependency:

```ts
SteamClient.GameSessions.RegisterForAppLifetimeNotifications(
  callback: (notification: AppLifetimeNotification) => void
)
```

`SteamClient.Apps.RegisterForGameActionEnd` is intentionally not used because game
action completion is not equivalent to app lifetime exit.

## Dependency Requirements

No dependency changes are required. The needed Decky types are already present through
`@decky/ui`.

## Testing Strategy

Add red static tests before implementation to verify:

- The frontend registers for app lifetime notifications.
- The frontend does not use `RegisterForGameActionEnd`.
- The 1-second polling watcher is fallback-only, not unconditional.
- Sessions are tracked by `nInstanceID`.
- `bRunning` true and false branches dispatch to start and exit handlers.
- Non-Steam app ids are handled without relying only on `unAppID`.
- Existing auto-sync notification gating remains intact.

Validation commands:

```bash
./run.sh uv run pytest tests/test_frontend_static.py
pnpm run typecheck
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```
