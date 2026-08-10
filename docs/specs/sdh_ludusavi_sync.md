# SDH-ludusavi Sync Spec

## Identity

The plugin name is `SDH-ludusavi`. The Python package is `sdh_ludusavi`, and the
JavaScript package name is `sdh-ludusavi`.

## Ludusavi Integration

The backend constructs `pyludusavi.Ludusavi` with:

```python
Ludusavi(flatpak_id="com.github.mtkennerly.ludusavi", env=_ludusavi_env())
```

The adapter passes Deck-compatible environment overrides into `pyludusavi`. It provides
`XDG_RUNTIME_DIR=/run/user/1000` when Decky omits that variable and clears
`LD_LIBRARY_PATH` for Ludusavi subprocesses without mutating the plugin process
environment. Launcher discovery uses the same environment helper.

Ludusavi game names are canonical game IDs. Steam app IDs are optional metadata.

## Settings

`auto_sync_enabled` controls automatic sync only. Manual backup and restore remain
available when automatic sync is disabled, subject to game status and the global
operation lock.

Runtime state is stored as `sdh_ludusavi.json` in `DECKY_SETTINGS_DIR` when Decky
provides that directory. If Decky does not provide it, the backend uses a private
`0700` fallback under `DECKY_USER_HOME/.config/sdh-ludusavi/`, then the current user's
home config directory if `DECKY_USER_HOME` is unavailable.

The persisted state includes settings, cached game metadata, normalized Steam app
membership metadata, and a backend-owned Ludusavi config modification marker. The cache
is valid for fast QAM open only when the Steam app marker and Ludusavi config marker
still match the current runtime state. The Ludusavi marker is based on the active config
file's `st_mtime_ns` value from `pyludusavi.Ludusavi.config_path()`.

`installed_app_ids` is treated as frontend-provided input. The backend must bound,
parse, deduplicate, and sort it before comparison or persistence. Malformed or oversized
values are ignored and are never saved raw to state.

External backup status changes are not cache invalidators. Backup and restore operation
paths must validate current Ludusavi state before acting; stale backup-status display
can be corrected by refresh.

Empty, corrupt, unreadable, or non-object state files are ignored with a warning and
default to `auto_sync_enabled: false`.

## Game Status

Each game has one of these statuses:

- `configured`: Ludusavi recognizes the game.
- `has_backup`: Ludusavi recognizes at least one backup for the game.
- `needs_first_backup`: Ludusavi recognizes the game but no backup exists.
- `error`: the latest Ludusavi operation reported an error for the game.

## Operation Lock

The backend uses a single global operation lock. Only one refresh, backup, restore,
or version probe can run at a time.

## Automatic Sync

On game start, the backend skips when automatic sync is disabled, the game is
unmatched, no backup exists, an operation is running, or recency cannot be determined
conservatively. It restores only when Ludusavi output clearly reports backup data
newer than local saves.

On game exit, the backend skips when automatic sync is disabled, the game is unmatched,
or an operation is running. Otherwise it backs up the matched game and refreshes the
cached status.

### Syncthing Activity Monitoring

To track synchronization of backup data to other devices, the plugin monitors Syncthing activity in the background.

- **Non-blocking Behavior**: Monitoring is advisory and display-only. Syncthing connection/API issues or slow sync will never block game launch or game exit.
- **Path Resolution**: The watched folder is resolved dynamically by matching Syncthing configured folders against Ludusavi's backup path.
- **Conflict Handling**: The monitor is stopped when a conflict is detected and is restarted only after a resolution operation is chosen, preventing the conflict screen from being overridden by temporary Syncthing statuses.
- **Peer Connectivity Gate**: Peer connectivity, not internet connectivity, controls monitoring. Before a watch starts, the backend intersects the matched folder's configured remote devices with the currently connected devices from `/rest/system/connections`. A folder with no configured remote devices is classified `folder_not_shared` (rendered as `LOCAL BACKUP SAVED - PATH NOT SHARED`); configured devices with none connected is classified `no_connected_peers`. Connected devices that do not share the matched folder do not count.
- **No Peers Online**: After a successful backup with no relevant peers connected, the frontend immediately publishes the terminal `LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE` warning (amber, auto-hidden by the result-status timeout) instead of waiting through the detection grace period. The local backup remains successful and no failure toast is emitted. Pre-game monitoring is skipped silently. If every relevant peer disconnects while a watch is active, the watcher stops with the same terminal `no_connected_peers` result. Device IDs are never logged or returned through RPC.
- **Post-game Peer Completion**: For a post-game watch only, the backend reads `/rest/db/completion` once for each currently connected relevant peer, then accepts `FolderCompletion` events only when both the watched folder and a configured remote device match. A peer remains incomplete when its completion is below 100% or it reports positive `needBytes`, `needItems`, or `needDeletes`. After a watched-folder local-index mutation, every connected relevant peer needs a newer completion observation before it can acknowledge that mutation. Freshness is based on event ordering and monotonic observation time, not `FolderCompletion.sequence`, which describes the remote device database and is not comparable to the Deck's local sequence.
- **Outbound Status and Privacy**: Incomplete or not-yet-fresh connected peers keep post-game `SYNCTHING UPLOADING` active. A 2.5-second observation hold prevents a local-index mutation and final completion in the same event batch from vanishing between frontend polls. `RemoteDownloadProgress` stays supplemental evidence rather than the acknowledgement source because it can be absent during an otherwise active remote pull. COMPLETE requires local settlement plus fresh, no-need reports from all connected relevant peers; it does not cover disconnected or offline configured peers. Transition diagnostics include only counts and aggregate need totals. `/rest/system/connections` remains an availability boundary only: its global and per-device byte counters never determine activity or direction.
- **Pre-game Boundary**: Pre-game watches do not call the completion endpoint and do not use remote peer lag to extend the launch gate. Their existing folder-local incoming, scan, need, index, and `RemoteDownloadProgress` evidence remains the sole settlement input.

## Manual Sync

`force_backup(game_name)` and `force_restore(game_name)` operate on the selected game.
They are not blocked by `auto_sync_enabled`, but they are blocked by invalid game
state and by the global operation lock.

## UI

The Decky panel includes an Automatic Sync toggle, a Ludusavi game selector, refresh,
force backup, force restore, progress state, Ludusavi/rclone versions, dependency
states, notification preferences, and a recent log panel. Notification preferences live
above the Ludusavi launcher panel and can suppress all plugin toasts or supported toast
categories. Autosync progress and successful autosync results are shown in a compact
bottom status strip; autosync failures still emit Decky toasts.

## Runtime Privilege

`plugin.json` does not request Decky's `_root` flag. The backend runs as the Decky user
so the Ludusavi Flatpak can see that user's Ludusavi configuration, backup metadata,
and Flatpak runtime state.
