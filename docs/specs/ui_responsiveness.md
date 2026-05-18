# Specification: UI Responsiveness and Warmed-Boot State

## 1. Goal
Provide a seamless, low-latency user experience for game selection and plugin initialization by minimizing synchronous I/O on the main event loop and leveraging persistent in-memory caching.

## 2. Backend Interface Requirements

### 2.1. RPC Async Execution
All backend methods that perform file I/O or persist state MUST be executed on a background thread to prevent blocking the Decky Loader event loop.

- `set_selected_game(game_name: str) -> dict`: Must be wrapped in `_run_blocking`.
- `set_auto_sync_enabled(enabled: bool) -> dict`: Must be wrapped in `_run_blocking`.

### 2.2. Subprocess Caching
Subprocess calls to `ludusavi` for static metadata (configuration paths) SHOULD be cached for the duration of the service session.

| Resource | Discovery Command | Cache Key |
| :--- | :--- | :--- |
| Config Path | `ludusavi config path` | `PyludusaviAdapter._cached_config_path` |

## 3. Frontend State Architecture

### 3.1. Persistence Across Mounts
The plugin frontend (React) is subject to unmounting and re-mounting by the Decky UI. To maintain responsiveness, the core state must be persisted in variables scoped to the plugin module.

| State Variable | Type | Description |
| :--- | :--- | :--- |
| `globalSettings` | `Settings \| null` | Persisted settings (auto-sync, selected game). |
| `globalGames` | `GameStatus[] \| null` | Cached list of Ludusavi-managed games. |
| `globalGameHistory` | `Record<string, History> \| null` | Recent operations history for all games. |

### 3.2. Warmed Boot Sequence
The initialization routine (`loadInitial`) must distinguish between a **Cold Boot** (first time loading in a Decky session) and a **Warmed Boot** (re-mounting after previously successful load).

#### Logic Flow:
1. Initialize local `useState` from `global` variables.
2. If `globalGames` is null:
   - Set UI to "Loading" state (busy label).
   - Perform full RPC fetch.
3. If `globalGames` is NOT null:
   - Show UI instantly with cached data.
   - Perform RPC fetch in background (silent refresh).
4. On RPC success:
   - Update both local state and `global` variables.
   - Clear "Loading" state if it was set.

## 4. UI Behavior Specifications

### 4.1. Status Transitions
- **Dropdown Change**: Upon selecting a new game, the UI must update the `selectedGame` state immediately. The backend persistence happens in the background. The "Status:" line should reflect the new game's status instantly using the cached `games` list.
- **Initial Load**: If cached data exists, the "Status:" line should show the status of the previously selected game immediately, with no "Loading game list..." flicker.

## 5. Sequence Diagram

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
