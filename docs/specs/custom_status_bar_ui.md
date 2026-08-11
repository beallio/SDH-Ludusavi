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

Module-level timers own status expiry. Running states have a 930-second safety ceiling,
active Syncthing statuses remain visible until the monitor replaces them, result states
hide after 2 seconds, hide events clear pending timers, and plugin dismount clears
pending timers before destroying the BrowserView.

BrowserView updates hide the reused BrowserView before loading each new visible
`data:text/html` document. Identical visible statuses are deduplicated and do not navigate, hide, or replay the reveal delay. For genuine status transitions, the view is revealed only after a short guarded delay so the previous status document, such as `GAME SAVE UP TO DATE`, cannot flash before a new `VERIFYING GAME SAVE` document finishes navigating. The reveal callback is
invalidated by a generation counter on every sync, hide, destroy, and dismount path.
Lifecycle verification states also reset the BrowserView surface before publishing
`VERIFYING GAME SAVE` so game start and game exit never reuse a surface that can
retain stale result pixels.

React global components, React DOM portals, diagnostic surface cycling, and SteamUI
composition-hook fallback paths are not production surfaces for this feature.

An external native overlay process, like OverLaid's backend-launched `DISPLAY=:0`
overlay binary, remains a fallback architecture only. The autosync strip should stay
inside SteamUI unless runtime testing proves the BrowserView surface is insufficient.

Lifecycle status publication must not depend solely on frontend tracking caches. Tracking
hydration guarantees settings and game lists are loaded before standard classification.
If tracking data fails to load or is cold, the frontend conservatively guards the game 
launch and shows the running strip before calling the backend, hiding it immediately if
the backend returns a silent skip (e.g., disabled autosync, unmatched game, or a
deselected Ludusavi game). Before save inspection begins, the backend temporarily holds the
validated Steam bootstrap PID while waiting a bounded interval for its exact Steam app scope.
That process-level hold is only a startup handoff: the backend freezes the exact scope through
the user systemd manager, verifies both cgroup v2 requested and completed freezer states,
releases the bootstrap hold inside the frozen scope, and verifies the freeze again before the
pause RPC can succeed. The renewable lease owns that stable scope identity while the user is
deciding on a save conflict, so later Steam/Proton processes join the already-frozen cgroup.

An expected differing-save conflict is shown only after that verified scope acquisition.
If acquisition, discovery, freeze, handoff verification, or systemd execution is unavailable,
the gate fails safely and the frontend does not restore, back up, or resolve a conflict while
the game loads. The existing `Launch gate unavailable; conflict resolution skipped while game
is loading.` notification remains the required visible failure state; it must not be hidden
or replaced by an unverified conflict modal.

The same renewable lease protects pre-game Syncthing settlement. An initialized idle
watch adds no launch delay. If relevant folder activity is observed, the launch stays
paused until three distinct settled samples arrive, `VERIFYING GAME SAVE` is published
again, and `check_game_start` is rerun against stable backup files. An interrupted active
transfer fails safely with `UNABLE TO SYNC`; it never acts on the preview captured while
the folder was changing.

Syncthing BrowserView activity is scoped in the backend to the deepest configured
Syncthing folder containing Ludusavi's backup path. `/rest/system/connections` is a
relevant-peer availability source only: its global and per-device byte counters never
determine activity or transfer direction. Watched-folder state from `/rest/db/status`
and folder-tagged `DownloadProgress`, state, scan, item, and index events remain the
folder-local activity sources. For post-game watches, `/rest/db/completion` supplies one
baseline per currently connected relevant peer, and a `FolderCompletion` reducer accepts
only events for that watched folder and one of its configured remote devices. It records
completion plus `needBytes`, `needItems`, and `needDeletes` internally; these device-level
values never enter the RPC payload.

Syncthing scopes an event `id` to the `/rest/events` subscription selected by its
`events=` filter; `since` matches that scoped value, while `globalID` is
process-wide. Cursor seeding and event polling therefore use the same `EVENT_TYPES`
filter. A new event call site must use that filter too, or its cursor would refer to a
different subscription.

After a watched-folder local-index mutation, an older peer completion cannot acknowledge
the mutation. The backend uses event ordering and monotonic observation times, not the
remote device's `FolderCompletion.sequence`, to establish freshness. A connected relevant
peer holds post-game upload activity only while it has missing content (`needBytes > 0` or
`needItems > 0`) or has not yet freshly acknowledged the mutation. The completion
percentage and `needDeletes` stay in count-only transition diagnostics, but never gate
completion: Syncthing reduces its percentage for pending deletes, as the 2026-08-09
`completion=95`, `needBytes=0`, `needItems=0`, `needDeletes=12` capture demonstrates.
A 2.5-second observation hold following a mutation or content-incomplete report gives the
500 ms monitor poller several chances to observe a fast transfer even when the first
content-complete peer report arrives in the same REST event batch.
`RemoteDownloadProgress` remains supplemental upload evidence; peer completion is
authoritative because its need counters
persist across gaps between transient block requests. A post-game watcher stops after 90
seconds without a decrease in aggregate content need, or at the backend's 900-second hard
ceiling. The frontend additionally stops a silent awaiting-fresh-completion watch after
300 seconds because it has no content need to measure. The stall window and both ceilings
remain unchanged: once delete pruning stopped gating in the 2026-08-10 captured run,
content settled in roughly 24 seconds and approached none of them. Their content-only
workload suitability is deferred until a run reaches a boundary. Either incomplete-upload
boundary publishes the amber
`LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE` outcome, not an API-failure status.
Bounded transition diagnostics contain only peer counts and aggregate need totals, never
device IDs or raw completion payloads. Pre-game watches do not query peer completion or
use it to extend launch settlement; their local/incoming behavior is unchanged. Events and
traffic from another Syncthing folder are excluded even when both folders share the same
remote device.

## Core Data Structures

- `AutoSyncStatusKind`: `checking`, `backing_up`, `restoring`, `conflict`,
  `conflict_unresolved`, `has_backup`, `unknown`, `error`,
  `syncthing_pending_upload`, `syncthing_downloading`,
  `syncthing_uploading`, `syncthing_complete`,
  `syncthing_upload_incomplete`, `syncthing_unavailable`,
  `syncthing_folder_not_found`, or `syncthing_no_peers`.
- `AutoSyncStatusSource`: lifecycle, RPC result, timeout, or hide provenance.
- `AutoSyncStatusState`: current strip status, visibility, and provenance.
- `AutoSyncStatusBrowserViewOwner`: wrapper shape used to normalize the BrowserView
  returned by Decky or Steam APIs.

The BrowserView document uses inline SVG icons. The restore icon is the backup arrow
rotated 180 degrees. Syncthing status icons are serialized and cached from `react-icons/io` (`IoMdCloudDownload`, `IoMdCloudUpload`, and `IoMdCloudDone`).

The visual contract is a compact bottom strip positioned directly above the Steam
bottom menu bar. BrowserView bounds use screen-height ratios instead of absolute
pixel constants: the strip height is 4.75% of viewport height and the bottom menu
offset is 2.625% of viewport height. On a 1280x800 Steam Deck OLED viewport, this
maps to a 38px strip at `y=741` and a 21px bottom menu bar at `y=779-799`. The icon
plus text are centered horizontally as one group, with a stable text-group width so
status changes do not visibly shift the strip. Checking, upload/download, and success
states use Steam Blue (`#66c0f4`), while `unknown`, `conflict`, and
`conflict_unresolved` and the non-error Syncthing terminal outcomes (including
`syncthing_upload_incomplete`) use the amber warning color (`#f59e0b`), and `error`
remains red (`#ef4444`).

## Public Interfaces

Automatic lifecycle sync is split into check and action RPCs so the strip can verify
save state before showing action copy:

- `check_game_start(game_name, app_id?)`
- `restore_game_on_start(game_name, app_id?)`
- `check_game_exit(game_name, app_id?)`
- `backup_game_on_exit(game_name, app_id?)`

The existing `handle_game_start(game_name, app_id?)` and
`handle_game_exit(game_name, app_id?)` RPCs remain compatibility wrappers with the
original result shapes. No persisted state or package dependencies change. The
frontend notification preferences panel no longer exposes autosync progress/result
toast toggles because those routine states move to the status strip.

Manual force backup and force restore keep their existing notification behavior.

Autosync status strip behavior:

- Before launch and exit checks: show `VERIFYING GAME SAVE`.
- Restore needed after launch check: show `RESTORING BACKUP SAVE`.
- Backup needed after exit check: show `BACKING UP LOCAL SAVE`.
- Ambiguous launch recency: show `SAVE CONFLICT` while the user chooses between
  keeping the local save and restoring the Ludusavi backup save. This state does not
  auto-hide while the modal remains open.
- Dismissed conflict: show `SYNC SKIPPED — CONFLICT UNRESOLVED` in amber for 2 seconds.
- Successful autosync result or current save state: show `GAME SAVE UP TO DATE` for
  2 seconds.
- Syncthing downloading activity: show `SYNCTHING DOWNLOADING` with cloud-down icon.
- Syncthing uploading activity: show `SYNCTHING UPLOADING` with cloud-up icon. After a
  backup, it means a currently connected relevant peer is missing backup content or has
  not yet freshly acknowledged the watched-folder local-index mutation.
- Syncthing completion: show `SYNCTHING COMPLETE` with cloud-checkmark icon only after
  the Deck's watched folder settles and every currently connected relevant peer has
  received the backup after that mutation. Pending deletion of older snapshots and the
  completion percentage do not delay this state. It does not validate a disconnected or
  offline configured peer.
- Incomplete post-game upload: show `LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE`
  in amber when monitoring ends while a connected peer remains behind or has not freshly
  confirmed the local-index mutation. The local backup succeeded; this is not an API
  error and it auto-hides with the other result outcomes.
- Unknown/non-actionable save state: show `UNKNOWN` for 2 seconds.
- Failed or unsafe-to-sync state: show `UNABLE TO SYNC` and emit one Decky failure
  toast.

During launch, visible `SYNCTHING DOWNLOADING` or `SYNCTHING UPLOADING` activity takes
precedence over a stale `local_current` result. After observed incoming activity settles,
the launch flow is observe, settle, recheck, decide, then resume. The 900 ms
`GAME SAVE UP TO DATE` dwell applies only to a successful post-game `backed_up` result
before the pending/uploading Syncthing handoff; it does not delay pre-game current or
restored results. Settled samples received before the post-game handoff cannot consume the
completion quorum. Once the handoff is confirmed, three new distinct settled samples are
required before the monitor publishes COMPLETE and stops, making UPLOADING visible even
for a very fast peer transfer.

Checking and running states stay visible while their operation runs and are replaced
when the operation's result is published. A stuck-bar safety ceiling force-hides them
after 930 seconds (just above the backend's 900-second operation bound), and only if
that ceiling fires does a late success stay quiet. A late failure always shows the
failure toast. Publishing any new running status clears a previous ceiling
suppression.

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
- BrowserView visible updates hide stale content before `LoadURL` and reveal through
  a guarded delayed show callback.
- Lifecycle verification publishes recreate the BrowserView surface before the
  verification document is loaded.
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
