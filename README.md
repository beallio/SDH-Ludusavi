# SDH-ludusavi

SDH-ludusavi is a Decky Loader plugin that surfaces Ludusavi save backup and
restore controls in the Steam Deck side panel.

Ludusavi remains the source of truth for configured games, backup paths, cloud
settings, and restore behavior. The plugin stores only local UI state, cached
game status, operation status, and recent operation logs.

## Features

- **Automatic Sync:** Automates save lifecycle management:
  - **On Game Start:** Automatically restores your save if the backup is newer than the local files (e.g., after playing on another device).
  - **On Game Exit:** Automatically performs a backup immediately after closing the game, including cloud synchronization if Ludusavi/rclone is configured.
  - **Safety First:** Skips operations if results are ambiguous or if another operation is already running to prevent data corruption.
- **Unified Logging:** Frontend and backend logs are consolidated into the Decky Loader system log and accessible via a "View Logs" modal with timestamps and chronological ordering.
- **Persistent Settings:** Remembers your selected game and sync preferences across plugin reloads.
- **Ludusavi Integration:** Direct selector for Ludusavi game entries with real-time status display (e.g., "Backup ready", "Needs first backup").
- **Manual Overrides:** Refresh Games, Force Backup, and Force Restore actions are always available, even when Automatic Sync is disabled.
- **Shortcut Artwork:** The plugin-managed Ludusavi launcher shortcut uses bundled local
  capsule, hero, and logo artwork and does not fetch SteamGridDB assets at runtime.
- **Version Display:** SDH-ludusavi and Ludusavi version information.

## Requirements

- Decky Loader.
- Ludusavi Flatpak: `com.github.mtkennerly.ludusavi`.
- Python package dependency: `pyludusavi`.
- Frontend dependencies from `package.json`.

The backend locates Ludusavi through the vendored `pyludusavi` package. It constructs
`pyludusavi.Ludusavi(flatpak_id="com.github.mtkennerly.ludusavi", env=...)` with
Deck-compatible environment overrides. The overrides provide `XDG_RUNTIME_DIR` when
Decky omits it and clear `LD_LIBRARY_PATH` for Ludusavi subprocesses.

## Development Setup

Use the wrapper so Python virtual environments and caches stay outside Dropbox:

```bash
./run.sh uv sync
```

The wrapper stores Python tooling state under `/tmp/sdh_ludusavi`.

## State and Runtime Privileges

Runtime settings are stored in Decky/plugin-owned settings space at
`DECKY_SETTINGS_DIR/sdh_ludusavi.json` when Decky provides that directory. If Decky does
not provide a settings directory, the backend falls back to
`DECKY_USER_HOME/.config/sdh-ludusavi/sdh_ludusavi.json` with a private `0700` config
directory, then to the current user's home config directory if `DECKY_USER_HOME` is not
available. Tooling caches still live under `/tmp/sdh_ludusavi`; plugin settings do not.

`plugin.json` does not request Decky's `_root` flag. The backend runs as the Decky user
so the Ludusavi Flatpak can see that user's Ludusavi configuration, backup metadata,
and Flatpak runtime state. If a future feature needs elevated privileges, it should be
validated separately without regressing Ludusavi access.

## Project Structure

The installable Decky plugin is built from these required files:

- `plugin.json`: Decky plugin metadata.
- `package.json`: frontend package metadata and version.
- `main.py`: Python backend entry point for Decky RPC calls.
- `py_modules/sdh_ludusavi/`: Python backend modules on Decky's runtime import path.
- `py_modules/pyludusavi/`: vendored pure-Python Ludusavi adapter dependency.
- `src/index.tsx`: TypeScript frontend source.
- `assets/steamgrid/ludusavi/`: bundled local artwork source files for the
  plugin-managed Ludusavi launcher shortcut.
- `dist/`: generated frontend bundle, source map, and built frontend assets from
  `pnpm run build`, including hashed artwork files emitted from the local assets.
- `LICENSE`: redistributable license text.

Install frontend dependencies when needed:

```bash
pnpm install --frozen-lockfile --ignore-scripts
```

The repository uses `pnpm-lock.yaml` as the canonical frontend lockfile. Do not
use `npm install` or add `package-lock.json`. The pnpm store and heavy virtual
store are configured under `/tmp/sdh_ludusavi`; the local `node_modules/`
directory is ignored and contains only pnpm links/bin shims needed by package
scripts.

## Usage

Run backend tests:

```bash
./run.sh uv run pytest
```

Build the Decky frontend:

```bash
pnpm run build
```

Run frontend supply-chain checks:

```bash
pnpm run verify
```

Create the Decky plugin zip:

```bash
./run.sh uv run python scripts/package_plugin.py
```

The package is written to `out/SDH-ludusavi.zip` and contains a top-level
`SDH-ludusavi/` plugin directory. The local post-commit hook runs
`scripts/post_commit.sh`, which rebuilds `dist/` and recreates that zip after each
commit.

## Status Messages

Game status values:

- `has_backup`: Ludusavi recognizes at least one backup for the game. The UI labels this as `Backup ready`.
- `needs_first_backup`: Ludusavi recognizes the game, but no backup exists yet. This is the normal no-backup state. The UI labels this as `Needs first backup`.
- `configured`: Ludusavi recognizes the game, but the plugin has not marked it as `has_backup` or `needs_first_backup`. This is a fallback state for ambiguous status data.
- `error`: Ludusavi reported a failed file, registry item, or invalid game state for the game.

Operation result values:

- `backed_up`: A backup operation completed for the selected or matched game.
- `restored`: A restore operation completed for the selected or matched game.
- `skipped`: The plugin intentionally did not run backup or restore. See the skip reasons below.
- `failed`: The frontend caught an unexpected operation failure and displays the error message.

Skip reasons:

- `auto_sync_disabled`: Automatic Sync is off. Manual Force Backup and Force Restore remain available.
- `operation_running`: Another refresh, backup, restore, or version lookup is already running.
- `unmatched_game`: The provided game name did not confidently match a Ludusavi game name.
- `no_backup`: Restore was requested or considered, but Ludusavi has no backup for that game.
- `local_current`: On game start, Ludusavi data indicated the local save is already current.
- `ambiguous_recency`: On game start, the plugin could not prove that the backup is newer than the local save, so it skipped automatic restore.

Operation status fields:

- `is_running`: `true` while the global operation lock is held.
- `name`: The active operation name, such as `refresh`, `backup`, `restore`, or `versions`.
- `game_name`: The game associated with the active operation, when applicable.
- `last_result`: `ok` after a successful locked operation, `failed` after an exception, or `null` before any operation result is recorded.
- `last_error`: The latest operation error text, or `null` when no error is recorded.

Other UI states:

- `dependency_error`: A refresh-time dependency or Ludusavi error shown directly in the panel.
- `No Ludusavi games found`: The UI has no cached Ludusavi games to show in the selector.
- `Unknown`: Version information is not available for Ludusavi or rclone.
- Log levels are currently `info` for normal decisions and `error` for refresh or dependency failures.

## Validation

Before committing changes, run:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run build
```

## License

MIT - See [LICENSE](LICENSE) for details.
