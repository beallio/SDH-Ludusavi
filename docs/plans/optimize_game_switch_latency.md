# Plan: Optimize Game Switch Latency and UI Responsiveness

## Problem Definition
Switching games in the dropdown or re-opening the plugin panel causes a visible "Loading game list..." status message for approximately one second. This latency and UI flicker are caused by:
1. **Blocking Backend RPCs**: Settings updates and metadata discovery run on the main Decky thread, freezing the UI.
2. **Redundant Subprocesses**: The "fast" refresh checks spawn multiple Ludusavi processes for config path discovery.
3. **Frontend State Reset**: The plugin component occasionally re-mounts in Decky. Since it doesn't persist its "warmed" state in a global cache, it defaults to a "Loading" state on every mount.

## Architecture Overview
1. **Asynchronous Backend**: All backend methods that perform file I/O, persist state, or perform blocking discovery will be wrapped in `_run_blocking` to execute on a background thread.
2. **Subprocess Caching**: The `PyludusaviAdapter` will cache the static config path in memory to avoid redundant subprocess spawns.
3. **Warmed-Boot Frontend**: Core state will be persisted in module-level global variables. The UI will render instantly using this cached data upon remounting, while performing a silent refresh in the background. Optimistic UI updates will be used for settings, with robust rollbacks if the backend RPCs fail.

## Core Data Structures

### Frontend Global Cache
- `globalSettings: Settings | null`
- `globalGames: GameStatus[] | null`
- `globalGameHistory: Record<string, GameOperationHistory> | null`
- `globalVersions: Versions | null`
- `globalLudusaviCommand: LudusaviLaunchCommand | null`

## Public Interfaces

### Backend RPC Contract Updates
The following methods will now execute asynchronously and their return types will be wrapped in `RpcResult[T]` to handle `OperationLockedError` and other exceptions consistently:
- `set_selected_game(game_name: str) -> RpcResult[Settings]` (previously `Settings`)
- `set_auto_sync_enabled(enabled: bool) -> RpcResult[Settings]` (previously `Settings`)
- `set_ludusavi_launcher_shortcut_id(app_id: int) -> RpcResult[bool]` (previously `bool`)
- `clear_ludusavi_launcher_shortcut_id() -> RpcResult[bool]` (previously `bool`)
- `get_ludusavi_command() -> RpcResult[LudusaviLaunchCommand | null]` (previously `LudusaviLaunchCommand | null`)

### Frontend Type Updates
- `setSelectedGameCall`, `setAutoSyncEnabled`, `setLudusaviLauncherShortcutIdCall`, `clearLudusaviLauncherShortcutIdCall`, and `getLudusaviCommandCall` signatures must be updated to return `RpcResult<T>`.

## Dependency Requirements
None. Uses standard library and existing Decky UI/API imports.

## Testing Strategy

### Backend Tests (`tests/test_main_rpc.py`, `tests/test_service.py`, `tests/test_ludusavi.py`)
- **Wrapper Tests**: Verify that `set_selected_game`, `set_auto_sync_enabled`, `get_ludusavi_command`, etc. are executed via `_call` and return `{"status": "failed"}` or `{"status": "skipped"}` on error.
- **Adapter Cache Tests**: Verify that `_client.config_path()` is called exactly once per adapter session, and that `stat` failures return `None` for the mtime but do not clear the static path cache string itself.

### Frontend Static Tests (`tests/test_frontend_static.py`)
- **Global Variables**: Assert the presence of `globalSettings`, `globalGames`, `globalGameHistory`, `globalVersions`, and `globalLudusaviCommand`.
- **Warmed Load**: Assert that `loadInitial` checks `globalGames` before setting `busyLabel("Loading")`.
- **Settings RPC Guards**: Assert that `setAutoSyncEnabled` and `setSelectedGameCall` usage is guarded with `isRpcStatus` to handle failures safely (e.g. reverting optimistic UI).
- **Cache Updates**: Assert that successful responses update both the local state and the global cache variables, and that failures do not overwrite the cache.
