# Plan: Optimize UI Responsiveness and "Warmed Boot" State Management

## Problem Definition
The user experience is currently degraded by two distinct issues:
1. **Synchronous Backend Blocking**: RPCs that perform state persistence (e.g., changing the selected game) or blocking I/O (e.g., reading logs, discovering commands) run on the main Decky thread, causing the UI to freeze or lag during the operation.
2. **Frontend State Flicker**: The plugin panel re-mounts frequently when closed and re-opened. Because it currently resets its state on every mount, it displays a "Loading game list..." message even when the data has not changed.

## Architecture Overview
1. **Asynchronous Backend**: All backend methods that perform file I/O, persist state, or perform blocking discovery will be wrapped in `_run_blocking` to execute on a background thread.
2. **Frontend Operation Gating**: The frontend will disable controls while refresh or settings persistence is in flight so duplicate refreshes and overlapping user-triggered save/refresh operations are not possible through the UI.
3. **Subprocess Caching**: The `PyludusaviAdapter` will cache the static config path in memory to avoid redundant subprocess spawns during normal "fast" refresh checks.
4. **Warmed-Boot Frontend**: Core state will be persisted in module-level global variables in `src/index.tsx`. The UI will render instantly using this cached data upon remounting only when both settings and games are cached, while performing a silent refresh in the background.
5. **Robust RPC Handling**: All persistence and discovery RPCs will use the `RpcResult` pattern. The frontend will implement optimistic updates with explicit rollbacks if a backend operation fails.

## Core Data Structures

### Frontend Global Cache
- `globalSettings: Settings | null`
- `globalGames: GameStatus[] | null`
- `globalGameHistory: Record<string, GameOperationHistory> | null`
- `globalVersions: Versions | null`
- `globalLudusaviCommand: LudusaviLaunchCommand | null`

## Public Interfaces

### Backend RPC Contract Updates
The following methods will now execute asynchronously and their return types will be wrapped in `RpcResult[T]` to handle concurrency and exceptions consistently:
- `set_selected_game(game_name: str) -> RpcResult[Settings]`
- `set_auto_sync_enabled(enabled: bool) -> RpcResult[Settings]`
- `set_ludusavi_launcher_shortcut_id(app_id: int) -> RpcResult[bool]`
- `clear_ludusavi_launcher_shortcut_id() -> RpcResult[bool]`
- `get_ludusavi_command() -> RpcResult[LudusaviLaunchCommand | null]` (None = not found, RpcStatus = discovery failed)
- `get_ludusavi_logs() -> RpcResult[string]`

### Frontend Implementation
- **index.tsx**: Update callables and handle `RpcResult` in `onGameChange`, `toggleAutoSync`, `loadInitial`, and `showLudusaviLogs`.
- **Warmed Boot**: Treat the cache as warmed only when `globalSettings` and `globalGames` are both present. If a warmed background refresh fails, keep the stale cached data visible.
- **Command Discovery**: If `get_ludusavi_command` returns `RpcStatus` during warmed boot, keep any existing `globalLudusaviCommand` and show/log a non-blocking warning. If no command is cached, show the existing Ludusavi unavailable state.
- **Log Modal**: If `get_ludusavi_logs` returns `RpcStatus` or throws, open the log modal with an error message instead of raw log contents.
- **Refresh Button**: Disable the refresh button immediately after it is clicked and until the refresh completes.
- **ludusaviLauncher.ts**: Update `getSavedShortcutAppId` and `saveShortcutAppId` to handle `RpcResult` from `call()`.

## Testing Strategy

### Backend Tests
- **Discovery Semantics**: Verify that `get_ludusavi_command` returns `None` for "not installed" and `RpcStatus` for "discovery failure".
- **Log Semantics**: Verify that `get_ludusavi_logs` can surface a failure payload that the frontend can display in the modal.
- **Wrapper Coverage**: Verify all listed RPCs are handled by the background worker.
- **Adapter Cache**: Verify `_client.config_path()` is cached during normal serial refresh checks.

### Frontend Tests
- **Launcher RPCs**: Add tests for `src/ludusaviLauncher.ts` RpcResult handling.
- **Static Analysis**: Verify module-level globals and "Warmed Load" logic require both `globalSettings` and `globalGames`.
- **Command RPCs**: Verify `getLudusaviCommandCall` preserves a cached command on `RpcStatus`.
- **Log Modal**: Verify log retrieval failures are displayed inside the Ludusavi log modal.
- **Refresh Gating**: Verify the refresh button is disabled while refresh is in flight.

### Validation Suite
- `./run.sh uv run pytest`
- `./run.sh uv run ty check py_modules/sdh_ludusavi/`
- `./run.sh uv run ruff check .`
- `./run.sh uv run ruff format .`
- `pnpm run typecheck`
- `pnpm run build`
