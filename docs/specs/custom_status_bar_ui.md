# Custom Autosync Status Strip UI

## Problem Definition

Autosync currently relies on Decky toast notifications for lifecycle feedback. Toasts
work, but they do not match SteamOS launch-screen status affordances and can be noisy
for normal successful backup and restore work. SDH-ludusavi needs a compact,
non-interactive status strip that appears during automatic restore-on-start and
backup-on-exit operations, while keeping native Decky toasts for failures only.

## Architecture Overview

The status strip is frontend-owned and driven by the existing app lifetime flow in
`src/index.tsx`.

- `SteamClient.GameSessions.RegisterForAppLifetimeNotifications` remains the primary
  app start/exit source.
- The existing `handle_game_start` and `handle_game_exit` RPCs remain the backend
  operation boundary.
- The strip publishes local frontend state before and after those RPC calls.
- No backend `decky.emit` event stream is added for v1.
- No direct Steam overlay/window composition APIs are called.

The status strip is registered as a Decky global component and renders through a React
portal into `document.body`. It stays mounted while the plugin is loaded and toggles
visibility with CSS transforms. The strip must not live only inside the plugin panel
content tree because that tree may not be visible while a game is launching or running.

When visible, the status strip must also request SteamUI notification composition via
the internal UI composition hook resolved with Decky's `findModuleChild`. This mirrors
the decky-pip overlay pattern and uses `EUIComposition.Notification`, whose semantics
allow transparent SteamUI pixels to show the running game behind Steam while input
continues to go to the game. The composition request is mounted only while the strip
is visible so SDH-ludusavi does not permanently alter SteamUI composition behavior.

The canonical visible surface is a BrowserView overlay. `publishAutoSyncStatus`
creates or updates a small BrowserView, loads a self-contained `data:text/html`
document that renders the same strip, positions it at the bottom of the Gamepad UI
viewport, and toggles BrowserView visibility with the autosync state. The React DOM
portal remains as a fallback surface for SteamUI contexts where it is visible, but the
BrowserView is the path intended to survive the running-game layer.

An external native overlay process, like OverLaid's backend-launched `DISPLAY=:0`
overlay binary, remains a fallback architecture only. The autosync strip should stay
inside SteamUI unless runtime testing proves the BrowserView surface is insufficient.

Lifecycle status publication must not depend solely on frontend tracking caches. If
settings or tracking data have not been loaded yet, the frontend should show the
running strip before calling the backend and hide it if the backend returns a silent
skip such as disabled autosync, unmatched game, another operation running, or a
deselected Ludusavi game.

## Core Data Structures

- `AutoSyncStatusKind`: `backing_up`, `restoring`, `has_backup`, `needs_backup`, or
  `error`.
- `AutoSyncStatusState`: current strip status plus visibility.
- `AutoSyncStatusListener`: local frontend callback used by lifecycle handlers to
  publish strip updates.

The UI uses existing `react-icons/fa6` icons. The restore icon is the backup arrow
rotated 180 degrees. The backup-needed icon layers a floppy disk over a circle with
positioned spans instead of adding Font Awesome dependencies.

## Public Interfaces

No backend RPCs, persisted state, or package dependencies change. The frontend
notification preferences panel no longer exposes autosync progress/result toast
toggles because those routine states move to the status strip.

Manual force backup and force restore keep their existing notification behavior.

Autosync notification behavior changes:

- Start restore operation: show `BACKUP: RESTORING`.
- Start backup operation: show `BACKUP: BACKING UP`.
- Successful autosync result: show `BACKUP: UP TO DATE` for 2 seconds.
- User-relevant skipped autosync result: show `BACKUP: NEEDED` for 2 seconds.
- Failed autosync result: show `BACKUP: ERROR` and emit one Decky failure toast.

The running state auto-hides after 10 seconds. A late success stays quiet. A late
failure still shows the failure toast.

## Dependency Requirements

No dependency changes are required.

## Testing Strategy

Frontend static tests must verify:

- The status strip renders with `createPortal(..., document.body)`.
- The plugin registers the strip with `routerHook.addGlobalComponent` and removes it on
  dismount.
- The plugin uses `alwaysRender: true`.
- The strip is fixed to the bottom, non-interactive, high z-index, and transform
  animated.
- The implementation imports the expected `react-icons/fa6` icons and does not add
  Font Awesome packages.
- Autosync lifecycle handlers publish strip states around existing RPC calls.
- Autosync start/result success toasts are removed.
- Autosync failure still routes through the `failures_errors` notification category.
- The strip requests `EUIComposition.Notification` through the discovered SteamUI
  composition hook while visible.
- The strip creates and updates a BrowserView-backed overlay surface with a local
  `data:text/html` document.
- Direct `SetOverlayState` and `SetComposition` calls are not used.

Validation commands:

```bash
./run.sh uv run pytest tests/test_frontend_static.py
pnpm run typecheck
pnpm run build
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```
