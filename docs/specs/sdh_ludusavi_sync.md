# SDH-ludusavi Sync Spec

## Identity

The plugin name is `SDH-ludusavi`. The Python package is `sdh_ludusavi`, and the
JavaScript package name is `sdh-ludusavi`.

## Ludusavi Integration

The backend constructs `pyludusavi.Ludusavi` with:

```python
Ludusavi(flatpak_id="com.github.mtkennerly.ludusavi")
```

Ludusavi game names are canonical game IDs. Steam app IDs are optional metadata.

## Settings

`auto_sync_enabled` controls automatic sync only. Manual backup and restore remain
available when automatic sync is disabled, subject to game status and the global
operation lock.

Runtime state is stored as `sdh_ludusavi.json` in `DECKY_SETTINGS_DIR` when Decky
provides that directory. If Decky does not provide it, the backend uses a private
`0700` fallback under `DECKY_USER_HOME/.config/sdh-ludusavi/`, then the current user's
home config directory if `DECKY_USER_HOME` is unavailable. The persisted JSON schema is
unchanged:

```json
{"auto_sync_enabled": true}
```

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

## Manual Sync

`force_backup(game_name)` and `force_restore(game_name)` operate on the selected game.
They are not blocked by `auto_sync_enabled`, but they are blocked by invalid game
state and by the global operation lock.

## UI

The Decky panel includes an Automatic Sync toggle, a Ludusavi game selector, refresh,
force backup, force restore, progress state, Ludusavi/rclone versions, dependency
states, and a recent log panel. Backup and restore events emit Decky toast
notifications for start, success, skipped, and failure outcomes.

## Runtime Privilege

`plugin.json` does not request Decky's `_root` flag. The backend runs as the Decky user
so the Ludusavi Flatpak can see that user's Ludusavi configuration, backup metadata,
and Flatpak runtime state.
