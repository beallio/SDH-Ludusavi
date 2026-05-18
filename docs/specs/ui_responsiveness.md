# Specification: UI Responsiveness and Warmed-Boot State

## 1. Goal
Provide a seamless, low-latency user experience for game selection and plugin initialization by minimizing synchronous I/O on the main event loop and leveraging persistent in-memory caching.

## 2. Backend Interface Requirements

### 2.1. RPC Async Execution
All backend methods that perform file I/O, persist state, or perform blocking subprocess discovery MUST be executed on a background thread to prevent blocking the Decky Loader event loop. They must return an `RpcResult` compatible dictionary to communicate failures.

| Method | Original Return | New Return |
| :--- | :--- | :--- |
| `set_selected_game` | `dict` | `RpcResult[dict]` |
| `set_auto_sync_enabled` | `dict` | `RpcResult[dict]` |
| `set_ludusavi_launcher_shortcut_id` | `bool` | `RpcResult[bool]` |
| `clear_ludusavi_launcher_shortcut_id` | `bool` | `RpcResult[bool]` |
| `get_ludusavi_command` | `dict \| None` | `RpcResult[dict \| None]` |
| `get_ludusavi_logs` | `str` | `RpcResult[str]` |

#### Failure Semantics for `get_ludusavi_command`:
- **Success (Found)**: Returns the `LudusaviLaunchCommand` object.
- **Success (Not Found)**: Returns `None`.
- **Failure**: Returns `RpcStatus` (e.g., `{"status": "failed", "message": "..."}`).

### 2.2. State Concurrency
The `SDHLudusaviService` must implement a shared re-entrant or standard lock to protect both the in-memory state dictionary and the `_save_state` file-writing process. This ensures that concurrent asynchronous RPCs do not result in race conditions or partial state writes.

### 2.3. Subprocess Caching
Subprocess calls to `ludusavi` for static metadata (configuration paths) SHOULD be cached for the duration of the adapter session.

| Resource | Discovery Command | Cache Key | Behavior on Stat Failure |
| :--- | :--- | :--- | :--- |
| Config Path | `ludusavi config path` | `PyludusaviAdapter._cached_config_path` | Keep cached path string, return `None` for mtime |

## 3. Frontend State Architecture

### 3.1. Persistence Across Mounts
The plugin frontend (React) is subject to unmounting and re-mounting by the Decky UI. Core state MUST be persisted in variables scoped to the plugin module.

| State Variable | Type | Description |
| :--- | :--- | :--- |
| `globalSettings` | `Settings \| null` | Persisted settings (auto-sync, selected game). |
| `globalGames` | `GameStatus[] \| null` | Cached list of Ludusavi-managed games. |
| `globalGameHistory` | `Record<string, GameOperationHistory> \| null` | Recent operations history. |
| `globalVersions` | `Versions \| null` | Version info. |
| `globalLudusaviCommand` | `LudusaviLaunchCommand \| null` | Launcher command info. |

### 3.2. Cache Update and Invalidation Rules
1. **Update**: Every successful RPC that fetches or modifies state MUST update BOTH the local React state and the corresponding global module-level variable.
2. **Failure**: If a background refresh or fetch RPC fails, the stale cached data MUST remain visible. It MUST NOT overwrite the global cache with null or error payloads.
3. **Optimistic UI**: When toggling settings or changing a game, the local UI state SHOULD be updated optimistically. If the backend RPC fails, the local state MUST be reverted to match the `global` state and an error toast shown.

### 3.3. Warmed Boot Sequence
The initialization routine (`loadInitial`) must distinguish between a Cold Boot and a Warmed Boot.

#### Logic Flow:
1. Initialize local `useState` from `global` variables.
2. If `globalGames` is null (Cold Boot):
   - Set UI to "Loading" state (`busyLabel("Loading")`).
   - Perform full RPC fetch.
3. If `globalGames` is NOT null (Warmed Boot):
   - Show UI instantly with cached data.
   - Perform RPC fetch in background (silent refresh).
4. On RPC success:
   - Update local state and `global` variables.
   - Clear "Loading" state if it was set.

## 4. Sequence Diagram

```text
User           Frontend (Content)      Global Store      Backend (Plugin)
 |                      |                   |                  |
 |---[Open Panel]------>|                   |                  |
 |                      |---[Get Globals]-->|                  |
 |                      |<--[Cached Data]---|                  |
 |<--[Render Instantly]-|                   |                  |
 |                      |                   |                  |
 |                      |---[RPC: refresh]-------------------->|
 |                      |                   |                  |
 |                      |<--[New Data]-------------------------|
 |                      |---[Update Globals]-->|                  |
 |<--[Refresh UI]-------|                   |                  |
```
