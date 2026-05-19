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

The production visible surface is a BrowserView overlay. `publishAutoSyncStatus`
creates or updates a small BrowserView, loads a self-contained `data:text/html`
document that renders the strip, positions it at the bottom of the Gamepad UI
viewport, and toggles BrowserView visibility with the autosync state. The BrowserView
owner is normalized through known Decky/Steam wrapper shapes, including `m_browserView`,
before required methods are used.

Module-level timers own status expiry. Running states hide after 10 seconds, result
states hide after 2 seconds, hide events clear pending timers, and plugin dismount
clears pending timers before destroying the BrowserView.

React global components, React DOM portals, diagnostic surface cycling, and SteamUI
composition-hook fallback paths are not production surfaces for this feature.

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
- `AutoSyncStatusSource`: lifecycle, RPC result, timeout, or hide provenance.
- `AutoSyncStatusState`: current strip status, visibility, and provenance.
- `AutoSyncStatusBrowserViewOwner`: wrapper shape used to normalize the BrowserView
  returned by Decky or Steam APIs.

The BrowserView document uses inline SVG icons. The restore icon is the backup arrow
rotated 180 degrees. No additional icon dependencies are required.

The visual contract is a compact bottom strip positioned directly above the Steam
bottom menu bar. BrowserView bounds use screen-height ratios instead of absolute
pixel constants: the strip height is 4.75% of viewport height and the bottom menu
offset is 2.625% of viewport height. On a 1280x800 Steam Deck OLED viewport, this
maps to a 38px strip at `y=741` and a 21px bottom menu bar at `y=779-799`. The icon
plus text are centered horizontally as one group, with a stable text-group width so
status changes do not visibly shift the strip. Running and success states use Steam
Blue (`#66c0f4`), `needs_backup` uses a distinct warning/action color (`#f59e0b`),
and `error` remains red (`#ef4444`).

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

- The plugin uses `alwaysRender: true`.
- The strip creates and updates a BrowserView-backed overlay surface with a local
  `data:text/html` document.
- The BrowserView wrapper is normalized through root, `m_browserView`, `browserView`,
  `BrowserView`, and nested `m_browserView.m_browserView` candidates.
- The BrowserView document matches the compact SteamOS-style bottom strip visual
  contract.
- The BrowserView bounds use percentage-based height and bottom menu offset ratios
  so the strip sits above the bottom menu bar across viewport sizes.
- The icon plus text are centered as one group, normal/running/success icons use
  Steam Blue, `needs_backup` uses a warning/action color, and errors remain red.
- Diagnostic buttons, diagnostic labels, alternate surface modes, React portal code,
  global component registration, and composition-hook code are absent.
- Autosync lifecycle handlers publish strip states around existing RPC calls.
- Autosync start/result success toasts are removed.
- Autosync failure still routes through the `failures_errors` notification category.
- Module-level timers clear on hide and dismount.
- Direct `SetOverlayState` and `SetComposition` calls are not used.

Validation commands:

```bash
./run.sh uv run pytest tests/test_frontend_static.py
./run.sh pnpm run typecheck
./run.sh pnpm run build
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```
