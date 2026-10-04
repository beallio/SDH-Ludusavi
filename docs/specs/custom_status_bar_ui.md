# Custom Autosync Status Strip UI

## Problem Definition

Autosync currently relies on Decky toast notifications for lifecycle feedback. Toasts
work, but they do not match SteamOS launch-screen status affordances and can be noisy
for normal successful backup and restore work. SDH-ludusavi needs a compact,
non-interactive status strip that appears during automatic restore-on-start and
backup-on-exit operations, while keeping native Decky toasts for failures only.

## Architecture Overview

The status presentation is frontend-owned and driven by the existing app lifetime flow in
`src/index.tsx`. It has two read-only presentations: the BrowserView strip for protected
launch work, and a native details-page row for eligible non-Steam entries.

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

Module-level timers own status expiry. Real Ludusavi operations and preview/status checks each
fail after three minutes. Running states have a separate 210-second cleanup ceiling, active
Syncthing statuses remain visible until the monitor replaces them, result states hide after 2
seconds, hide events clear pending timers, and plugin dismount clears pending timers before
destroying the BrowserView. The backend launch gate retains its distinct four-minute emergency
ceiling. Automatic lifecycle checks may wait up to 30 seconds for a currently active Ludusavi
operation so they can inspect fresh state, while automatic save-copy actions remain fail-fast.
An `operation_running` result is therefore rendered as one visible failure rather than a silent
completion. Syncthing's independent 120-second pre-game and 300/900-second post-game observation
limits are unchanged.

BrowserView updates hide the reused BrowserView before loading each new visible
`data:text/html` document. Identical visible statuses are deduplicated and do not navigate, hide, or replay the reveal delay. For genuine status transitions, the view is revealed only after a short guarded delay so the previous status document, such as `GAME SAVE UP TO DATE`, cannot flash before a new `VERIFYING GAME SAVE` document finishes navigating. The reveal callback is
invalidated by a generation counter on every sync, hide, destroy, and dismount path.
Lifecycle verification states also reset the BrowserView surface before publishing
`VERIFYING GAME SAVE` so game start and game exit never reuse a surface that can
retain stale result pixels.

React DOM portals, diagnostic surface cycling, and SteamUI composition-hook fallback paths are
not BrowserView-strip surfaces for this feature. The guarded details row is the one approved React
route contribution: it uses Decky's public route hook, reads only native state, and adds no action.

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

The frontend lease race is an early warning only; the backend owns the authority to protect a
save mutation. Start restore and both conflict choices, including `keep_local`, pass the exact
gate PID and lease ID. The watchdog verifies and pins that lease immediately around the managed
Ludusavi command. Resume, lease loss, watchdog expiry, and unload request cancellation for that
exact command and do not thaw the scope until cancellation returns and the worker has completed.
If the process group cannot be reaped, the gate remains frozen and the failure stays visible.

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
Only post-game `settled` uses the three-second `POST_GAME_SETTLE_QUIET_WINDOW_SECONDS`.
Seven captured post-backup bursts spread 0.051 to 0.111 seconds, so this leaves roughly
30x margin; values below about 6.5 seconds are equivalent because first-peer confirmation
binds first. Pre-game retains the fifteen-second launch-safety window. The reported local
recency flags and both local and remote pruning retain their fifteen-second
`DEFAULT_ACTIVE_WINDOW_SECONDS` behavior, so the short window does not shrink the
diagnostic surface or incoming-transfer reporting.
`RemoteDownloadProgress` remains supplemental upload evidence; peer completion is
authoritative because its need counters persist across gaps between transient block
requests. Peer completion never stops an owned post-game watch: the backend keeps
publishing settled samples with advancing `timestamp_unix` values, and the frontend
publishes `SYNCTHING COMPLETE` only after observing three settled samples with distinct
timestamps, then calls `stopWatch`. That call releases the watch; only a released watch
with debug logging latched may continue backend diagnostic observation, until every peer
finishes or an existing terminal boundary is reached. A watcher stopped before that
frontend-owned release freezes `latest_sample`, so a still-registered `poll_watch()` call
would return duplicate timestamps forever and the frontend could never satisfy its
completion quorum. An owned post-game watcher can still stop after 90 seconds without a
decrease in aggregate content need, or at the backend's 900-second hard ceiling. The
frontend additionally stops a silent awaiting-fresh-completion watch after 300 seconds
because it has no content need to measure. The stall window and both ceilings remain
unchanged: once delete pruning stopped gating in the 2026-08-10 captured run,
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
- `restore_game_on_start(game_name, app_id?, gate_pid?, gate_lease_id?)`
- `resolve_game_start_conflict(game_name, app_id?, resolution, gate_pid?, gate_lease_id?)`
- `check_game_exit(game_name, app_id?)`
- `backup_game_on_exit(game_name, app_id?)`

The existing `handle_game_start(game_name, app_id?)` and
`handle_game_exit(game_name, app_id?)` RPCs remain compatibility wrappers with the
original result shapes. No persisted state or package dependencies change. The
frontend notification preferences panel no longer exposes autosync progress/result
toast toggles because those routine states move to the status strip.

Gate arguments remain optional only at the RPC transport boundary for compatibility. The backend
requires a matching active gate before every start-side mutation; a missing or malformed pair
returns the structured fail-closed `gate_lost` result without invoking the adapter.

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
  backup, it means no connected relevant peer has yet produced three consecutive fresh,
  content-complete observations after the watched-folder local-index mutation.
- Syncthing completion: show `SYNCTHING COMPLETE` with cloud-checkmark icon after the
  Deck's watched folder settles and at least one connected relevant peer has produced
  three consecutive fresh, content-complete observations after that mutation. Other
  connected peers may still be catching up; their content and pending-delete counts remain
  diagnostics, and pending deletion of older snapshots and the completion percentage do
  not delay this state. Debug observation for those diagnostics is selected only from the
  persisted `debug_logging` value captured at watch start, not the logger level:
  `setup_logging()` pins `sdh_ludusavi` loggers to `DEBUG` while the user toggle adjusts
  only the `decky.logger` sink filter. It does not change the sample or visible status.
  Completion does not validate a disconnected or offline configured peer.
- Incomplete post-game upload: show `LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE`
  in amber when monitoring ends while a connected peer remains behind or has not freshly
  confirmed the local-index mutation. The local backup succeeded; this is not an API
  error and it auto-hides with the other result outcomes.
- Unknown/non-actionable save state: show `UNKNOWN` for 2 seconds.
- Failed or unsafe-to-sync state: show `UNABLE TO SYNC` and emit one Decky failure
  toast.
- A lifecycle check can wait at most 30 seconds for an active operation; an automatic restore,
  conflict choice, or exit backup does not wait behind a new operation. Either contention path
  reports `operation_running` as the same visible failure with one toast.

During launch, visible `SYNCTHING DOWNLOADING` or `SYNCTHING UPLOADING` activity takes
precedence over a stale `local_current` result. After observed incoming activity settles,
the launch flow is observe, settle, recheck, decide, then resume. The 900 ms
`GAME SAVE UP TO DATE` dwell applies only to a successful post-game `backed_up` result
before the pending/uploading Syncthing handoff; it does not delay pre-game current or
restored results. Settled samples received before the post-game handoff cannot consume the
completion quorum. Once the handoff is confirmed, three new distinct settled samples are
required before the frontend publishes COMPLETE and calls `stopWatch`, making UPLOADING
visible even for a very fast peer transfer.

Checking and running states stay visible while their operation runs and are replaced
when the operation's result is published. A stuck-bar safety ceiling force-hides them
after 210 seconds (the three-minute Ludusavi ceiling plus 30 seconds for RPC delivery
and cleanup). If that ceiling fires, a late success stays quiet, but a late failure
still shows the failure toast. Publishing any new running status clears a previous
ceiling suppression.

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
- The BrowserView strip has no React portal or focus target. The details row uses the public
  Decky route hook only at `/library/app/:appid` and composes the verified provider value.
  The inert wrapper survives the bounded same-contract reload handoff so an already-mounted
  page can receive the replacement store; if no replacement attaches, it removes the exact
  installed patch. A new row-render contract replaces only an older retained plugin patch,
  so subsequent native route renders use the current row without removing other plugins'
  patches. It never changes Steam Cloud data, controls, or classes.
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

## Details-page status row

The row appears only after the selected library entry has loaded matching details with both
Cloud enable flags. It is hidden when both flags are enabled, which is a display rule only and
does not change backup or restore eligibility. It reads the selected entry through the native
app-details subscription and does not substitute a catalog match or mutate Steam Cloud data.
Unknown details leave the native row unchanged, but the mounted route still claims the details page
so a same-page post-game fallback remains possible. Unsupported native provider shapes leave Steam
unchanged and cannot mount the route contribution, so post-game BrowserView presentation stays
hidden; protected launch presentation remains available.

The route contribution clones Decky's React route child and composes at its deferred native
Cloud-status component boundary. The Cloud component stays mounted. The row appears only when that
component renders no native status band, so it never creates a second band or replaces native
controls. The row releases ownership when it is hidden, clipped, offscreen, or covered. Its status
icon and transfer animation are
presentation only and it adds no controller focus stop.

A separate route-lifecycle component registers the mounted `/library/app/:appid` page with the
active details presentation surface. The registration is tokenized: cleanup releases only the
claim it created, so a stale unmount cannot clear a newer app or replacement-runtime claim. Page
presence is independent of Cloud eligibility, native class discovery, row rendering, and row
geometry. A page change or runtime replacement resynchronizes presentation only; it does not
publish, settle, hide, or otherwise change the retained operation observation.

The row uses Steam's supplied Cloud-status row, icon slot, SVG class, label, problem, transfer-pulse,
and active-value classes. Its root is a direct sibling after the native play section; the
deferred Cloud component and plugin row share a React Fragment, not DOM wrappers. Steam
owns visual presentation, including pseudo-element dividers. The plugin adds no inline
fonts, colors, sizes, spacing, or divider elements. Steam's default row is 30 pixels high;
themes may change its dimensions, placement, or visibility through native selectors.
Warning and error states use the native problem class, and active states use the native
pulse and blue value classes. The native-only status glyphs are static, use inherited
`currentColor` and transparent negative space, and carry no fixed canvas size, strip background,
or strip animation. They keep the local, remote, completed, warning, error, and disabled states
distinct without changing the BrowserView glyphs. Missing class capabilities leave the native
header unchanged.

A fully visible indicator with its complete label can own exit status; there is no fixed minimum row
height. Theme-supplied opacity zero, hidden visibility, clipping, label truncation, and occlusion cannot
suppress the fallback strip. The plugin's own paint-suppressed row is measured with its
inline opacity temporarily removed, then restored with its original priority. Visibility,
slot, and artwork observers share a mutation-batch guard so these measurements do not
cause an observer feedback loop.

Visible inventory, durable-history, and pre-game row text uses short Steam-style states: `Checking...`, `Backing up...`, `Restoring...`,
`Uploading...`, `Downloading...`, `Up to date`, `Out of sync`, `File conflict`, `Disabled`,
`Unable to sync`, and `Unknown`. The accessible description keeps the precise local-result and
remote-observation wording. A short visible label must not imply remote delivery that was not
observed.

Live terminal results and durable `last_operation` entries use the same status classification.
In particular, `skipped/local_current` maps to `has_backup`, so it remains `Up to date` after a
frontend reload while its accessible description remains `Local save already current`. Durable
classification consumes both the recorded status and reason. `Unknown` uses the normal
transparent row with dividers; it is not a warning/problem presentation.

For exit work, a mounted page claim for the same app is required before either presentation can
paint. A mounted, visible, layout-valid row with a complete label suppresses duplicate BrowserView
pixels; otherwise, the fallback can paint on that same page only. Home and another game's page do
not show exit pixels, and an exit operation for one app does not make another app's ordinary row
yield. Page changes and row ownership changes do not stop timers, watches, or status production.
They also do not extend a result strip lifetime. Terminal observations remain in frontend state
through the strip timeout, but the frontend marks interrupted or superseded activity as
remote-unverified instead of showing an endless transfer. Accepted `lifecycle_exit` activity and
retained facts use `autoSyncStatusText` as their full native label. A success-prefixed remote
warning needs an accepted `backed_up` local fact; otherwise it keeps its compact warning label. A
local result and a remote observation remain distinct in the row text. Start-side checking,
restore, and conflict work always use the strip.

The mounted game-details header also owns a temporary artwork extension in Steam's native
Gamepad document. This applies to either a visible Steam Cloud band or a Ludusavi row, including
when no trailer is playing. It selects only the current app's full-size Steam hero or custom
shortcut hero and measures a native-class or plugin-marked, full-width, in-flow status band
at the artwork's lower edge. The band's actual layout height determines the extension;
transform-scaled screen heights only locate that edge while the game page animates in.
Compact, moved, and genuinely hidden rows do not reserve artwork space. Temporary
coverage or clipping during page entry retains a valid row's layout reservation,
but only a paintable row permits the inline artwork extension. Hit-testing near
the band's upper edge retains the normal occlusion check; there is no footer exception.
Initial measurement runs after the native slot's layout-effect commits, not against its
temporary hidden row. The band itself does not move. Original inline image height,
CSS-variable values, marker attributes, and priorities return when the extension ends.
Native DOM, stylesheet, scroll, resize, and band-size changes resync the image.

For the verified standard-equation Clean Gameview profiles only, the same lifecycle also measures the
visible band and temporarily deducts it from both the top-panel and image budgets on Decky's
`appDetailsClasses.InnerContainer`, when it is the common route-content ancestor of the header
artwork and status body. The nested play/status `AppDetailsRoot` is not a budget target because it
does not own the header artwork. It records each original property value and priority under a
lease, so a stale page or document cleanup cannot overwrite a newer owner. The lifecycle removes
its own properties before checking the current computed geometry, then reapplies them, so a theme
change can release the deduction. It remeasures after the browser reflows; a clipped, covered, or
otherwise invalid row releases the deduction and keeps the existing fallback. Decky Metadata can
own the trailer artwork while this route-local budget remains available; Ludusavi does not extend
the trailer itself. The checked profiles have the footer enabled and use Transparent with Zoom
Center, Zoom Left, or Contain, or Blur with centered alignment. Connected with Body, layouts that
ignore the footer, percentage-based, compact, absolute, hidden, and otherwise unrecognized Clean
Gameview geometry receives no guessed adjustment. Other Clean Gameview choices and CSS Loader
versions are not yet verified.
The launch-time BrowserView strip remains separate.

### Optional CSS Loader theme

The plugin ZIP includes `theme/theme.json`, `theme/layout.css`, `theme/clean.css`, and `theme/custom.css`.
On backend startup, `status_theme.install_status_theme` copies those managed files into
`DECKY_HOME/themes/SDH-Ludusavi Status`. A marker identifies the owned directory. The first
install enables the theme with its `Default` selection. Later startups replace only
managed theme files and preserve CSS Loader's choices. CSS Loader need not be installed for
the assets to be deployed: without it, no theme CSS is injected. CSS Loader's Refresh
control discovers a new theme when it was already running and did not observe directory
creation.

`layout.css` is injected in every selection while the theme is enabled. It reserves a
30-pixel empty panel immediately after the play section. With Clean Gameview, the native
header image and background reserve `--CGV-image-height + 30px` before the status children
mount. The `--sdh-status-band-reserved` flag identifies this allowance; runtimes subtract
it before deriving the original artwork height, then set the measured
`--sdh-status-band-height`. Hidden, compact, and relocated indicators reduce that
allowance to zero after layout settles. No row leaves the theme's early blank-slot
allowance intact. Without Clean Gameview's image-height variable, no allowance is
subtracted.

Ludusavi and Metadata share a native-window WeakMap keyed by the header background.
The first owner saves the genuine inline variable value and priority; a handoff changes
only ownership. Only the current owner restores that value. A separate lease on the common
route-content ancestor gives the verified Clean Gameview top-panel and image deductions the
same stale-owner protection. This avoids a second crop change during trailer attachment and
prevents an old owner from overwriting a new one.
Steam's page-scale transition remains unchanged. Without CSS Loader or with the theme
disabled, the mounted header's measured artwork extension remains in use.

`Save Status` is a three-notch CSS Loader slider: `Default` injects no extra color stylesheet,
`Clean View` injects a translucent play-section-style background with no top-edge
shadow, and `Custom` injects the user-selected background, text, icon, and inset outline
colors. The four color pickers are visible only when Custom is selected and their alpha channels control
transparency. A separate `Outline Width` slider provides Off, Thin, Medium, and Thick;
CSS Loader shows it in all three modes, but only Custom reads its CSS variable. Active
Ludusavi text/icon styling, native Steam Cloud transfer colors/pulse, and both
implementations' problem rows retain their own visual state. Accepted post-game native labels use
the canonical full status text; compact inventory, durable-history, and non-post-game labels and
all accessible descriptions retain their existing meanings.

The theme targets Steam's Cloud-status CSS module selectors, translated by CSS Loader
for the current Steam client, plus stable `data-sdh-ludusavi-*` attributes on the
plugin's row, label, and icon. The row also exposes tone and active state to keep
problem and running states distinct. Apart from the empty-panel spacer and artwork
reservation, the theme never changes status-row dimensions, placement, visibility,
focus, or hit testing: those properties participate in details-row ownership and
BrowserView-strip fallback. It does not style the separate
launch BrowserView document. Clean Gameview's optional top-right icon relocation is
not part of this theme.

Decky invokes `_uninstall` for both plugin updates and actual removals. Before removing
its owned theme, the hook stores CSS Loader's `config_USER.json`, `config_ROOT.json`, and
optional `PRIORITY` under `DECKY_PLUGIN_RUNTIME_DIR`. Startup restores them when the
new theme is installed. On a true removal, only the preference backup remains for a
later reinstall; no theme files remain for CSS Loader to load. If the directory is
unowned, symlinked, or contains additional user files, the backend leaves it intact
and logs a warning instead of deleting another theme or user work. CSS Loader can
keep an already-injected stylesheet until its next Refresh or Steam restart; the
uninstall hook does not call private cross-plugin reload APIs.
