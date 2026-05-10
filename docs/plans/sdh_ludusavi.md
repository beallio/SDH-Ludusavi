# SDH-ludusavi Implementation Plan

## Problem Definition

Build a Decky Loader plugin named `SDH-ludusavi` that exposes Ludusavi save backup
and restore controls in the Decky side panel. Ludusavi remains the source of truth
for save configuration; the plugin stores only local UI and operation state.

## Architecture Overview

- `main.py` provides the Decky RPC facade and delegates behavior to a typed Python
  service.
- `src/sdh_ludusavi/service.py` owns settings, cached game status, operation locking,
  conservative automatic sync decisions, and recent logs.
- `src/sdh_ludusavi/ludusavi.py` adapts `pyludusavi.Ludusavi` using the required
  Ludusavi Flatpak ID `com.github.mtkennerly.ludusavi`.
- `src/index.tsx` renders the Decky panel and calls the backend methods through
  `@decky/api`.

## Core Data Structures

- `PluginSettings`: currently `auto_sync_enabled`.
- `GameStatus`: Ludusavi game name plus `configured`, `has_backup`,
  `needs_first_backup`, and `error` state.
- `OperationState`: global operation lock and last operation metadata.
- `LogEntry`: bounded recent operation log entries for UI diagnostics.

## Public Interfaces

Backend methods exposed to the frontend:

- `get_settings()`
- `set_auto_sync_enabled(enabled)`
- `refresh_games()`
- `handle_game_start(game_name, app_id?)`
- `handle_game_exit(game_name, app_id?)`
- `force_backup(game_name)`
- `force_restore(game_name)`
- `get_versions()`
- `get_operation_status()`
- `get_recent_logs()`

## Dependency Requirements

- Python dependencies are managed by `uv`.
- `pyludusavi` is added from PyPI.
- Runtime Ludusavi access uses the Flatpak ID `com.github.mtkennerly.ludusavi`.
- Tests mock `pyludusavi` and do not require Ludusavi, rclone, Flatpak, Steam, or
  network access.

## Testing Strategy

- Add backend tests before implementation for settings persistence, game refresh,
  name matching, auto-sync decisions, forced operations while automatic sync is
  disabled, operation locking, version lookup, dependency errors, log retrieval, and
  ambiguous-recency skips.
- Add frontend static tests for the Automatic Sync toggle, game selector, status
  rendering, force action state, spinner, refresh button, dependency-state display,
  and toast handling.
- Validate with `./run.sh uv run ruff check . --fix`, `./run.sh uv run ruff format .`,
  `./run.sh uv run ty check src/`, `./run.sh uv run pytest`, and the frontend build.
