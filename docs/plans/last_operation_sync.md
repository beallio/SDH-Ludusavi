# Plan: Sync Last Operation to Frontend on Load

Ensure that \"Last Operation\" history updates from automatic game start and game exit synchronizations are correctly returned to the frontend when the QAM is opened, even if the game cache is current, and ensure the in-memory global history cache is updated immediately following background auto-sync events.

## Problem Definition
1. **Frontend uses stale cached history when cache is current**:
   - On QAM mount, `initialLoad` fetches settings via `getSettings()`.
   - It checks if the game list cache is current (`isGameCacheCurrentCall()`). If `true`, the frontend mounts using its memory-cached `globalGameHistory`, which has not been updated with background sync operations since the frontend context was suspended/warmed.
   - Because settings does not and should not contain this state cache, the UI remains stale until a manual refresh is triggered.
2. **Settings is not the correct place for execution history**:
   - Instead of polluting `get_settings()` with non-settings cache data, we should fetch history via a dedicated RPC method that reads from the backend's state cache (loaded from the data directory).
3. **In-memory cache is not updated after background auto-sync**:
   - After background auto-sync runs (start or exit), `globalGameHistory` in the frontend's memory remains stale until the next UI load. We should proactively update `globalGameHistory` as soon as the auto-sync completes.

## Architecture Overview
- **Backend (`py_modules/sdh_ludusavi/service.py` & `main.py`)**:
  - Add a `get_game_history()` RPC method that returns `self._game_history`.
- **Frontend (`src/index.tsx`)**:
  - Register `getGameHistoryCall` as an RPC method.
  - In `initialLoad`, fetch both settings and history in parallel using `Promise.all`.
  - Update `globalGameHistory` and `gameHistory` React state with the loaded history.
  - After background auto-sync operations (`handleAppStart` / `handleAppExit`) finish, call `getGameHistoryCall()` to update the in-memory `globalGameHistory`.

## Proposed Changes

### [Backend Service]

#### [MODIFY] [service.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/service.py)
- Implement `get_game_history(self) -> dict[str, dict[str, Any]]` returning `self._game_history`.

#### [MODIFY] [main.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/main.py)
- Expose the async RPC method `get_game_history(self) -> dict[str, Any]`.

### [Frontend Components]

#### [MODIFY] [index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
- Define `getGameHistoryCall = callable<[], RpcResult<Record<string, GameOperationHistory>>>("get_game_history")`.
- Inside `initialLoad`, fetch settings and history in parallel:
  ```typescript
  const [loadedSettings, loadedHistory] = await Promise.all([
    getSettings(),
    getGameHistoryCall()
  ]);
  ```
- If `loadedHistory` is not an RPC error, call `setGameHistory(loadedHistory)` and update `globalGameHistory`.
- In `handleAppStart` (after calling `restoreGameOnStartCall` or `resolveGameStartConflictCall`) and in `handleAppExit` (after calling `backupGameOnExitCall`), fetch `getGameHistoryCall()` and update `globalGameHistory`.

### [Tests]

#### [NEW] [test_last_operation_sync.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_last_operation_sync.py)
- Create a test file verifying that:
  - `get_game_history()` returns the correct history dictionary.
  - History recorded from automatic actions is correctly exposed via `get_game_history()`.

## Testing Strategy
1. Run ruff quality control checks.
2. Build the frontend using `pnpm run build`.
3. Run the pytest test suite via `./run.sh uv run pytest` and verify everything is green.
