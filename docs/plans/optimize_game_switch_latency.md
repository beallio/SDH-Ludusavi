# Plan: Optimize UI Responsiveness and "Warmed Boot" State Management

## Problem Definition
The user experience is currently degraded by two distinct issues:
1. **Synchronous Backend Blocking**: RPCs that perform state persistence (e.g., changing the selected game) or blocking I/O (e.g., reading logs, discovering commands) run on the main Decky thread, causing the UI to freeze or lag during the operation.
2. **Frontend State Flicker**: The plugin panel re-mounts frequently when closed and re-opened. Because it currently resets its state on every mount, it displays a "Loading game list..." message even when the data has not changed.

## Architecture Overview
1. **Asynchronous Backend**: All backend methods that perform file I/O, persist state, or perform blocking discovery will be wrapped in `_run_blocking` to execute on a background thread.
2. **State Concurrency**: A service-level `threading.Lock` will be added to `SDHLudusaviService` to protect `_save_state` and in-memory state mutations from races during asynchronous execution.
3. **Subprocess Caching**: The `PyludusaviAdapter` will cache the static config path in memory to avoid redundant subprocess spawns during "fast" refresh checks.
4. **Warmed-Boot Frontend**: Core state will be persisted in module-level global variables in `src/index.tsx`. The UI will render instantly using this cached data upon remounting, while performing a silent refresh in the background. 
5. **Robust RPC Handling**: All persistence and discovery RPCs will use the `RpcResult` pattern. The frontend will implement optimistic updates with explicit rollbacks if a backend operation fails.

## Core Data Structures

### Backend State Lock
- `SDHLudusaviService._state_lock: threading.Lock`

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
- **index.tsx**: Update callables and handle `RpcResult` in `onGameChange` and `toggleAutoSync`.
- **ludusaviLauncher.ts**: Update `getSavedShortcutAppId` and `saveShortcutAppId` to handle `RpcResult` from `call()`.

## Testing Strategy

### Backend Tests
- **Concurrency Test**: Add a test in `tests/test_service.py` that triggers multiple overlapping `_save_state` calls from different threads to verify lock stability.
- **Discovery Semantics**: Verify that `get_ludusavi_command` returns `None` for "not installed" and `RpcStatus` for "discovery failure".
- **Wrapper Coverage**: Verify all listed RPCs are handled by the background worker.

### Frontend Tests
- **Launcher RPCs**: Add tests for `src/ludusaviLauncher.ts` RpcResult handling.
- **Static Analysis**: Verify module-level globals and "Warmed Load" logic.

### Validation Suite
- `./run.sh uv run pytest`
- `./run.sh uv run ty check py_modules/sdh_ludusavi/`
- `./run.sh uv run ruff check .`
- Frontend typecheck and build.
