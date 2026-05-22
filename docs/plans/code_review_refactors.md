# Code Review Refactors

## Problem Definition
Four issues were identified in recent reviews:
1. **Config Stat failures**: In `py_modules/sdh_ludusavi/service.py`, `_current_ludusavi_config_mtime_ns` attempts to catch exceptions thrown by `get_config_mtime_ns()` in order to return `_CONFIG_MARKER_READ_FAILED` and force a cache refresh. However, the adapter implementation in `py_modules/sdh_ludusavi/ludusavi.py` catches all exceptions internally and returns `None`. Consequently, a stat failure (e.g. permission denied or missing file) propagates `None` to the service caller, resulting in a silent failure to refresh the games list.
2. **Truthy RpcStatus check**: In `src/index.tsx::loadInitial`, `cacheCurrent` is assigned the returned promise of `isGameCacheCurrentCall`. If the RPC call fails, the backend returns an `RpcStatus` object instead of a boolean. In JavaScript, all objects are truthy, meaning the check `if (cacheCurrent && globalGames)` will falsely evaluate to `true`, skipping cache refresh.
3. **Promise.all fail-fast**: In `src/index.tsx::loadInitial`, independent operations `getVersions()` and `getLudusaviCommandCall()` are resolved using `Promise.all`. If one rejects, both are aborted, showing an error for both.
4. **Sleep-based test sync**: The test `test_run_blocking_retrieves_exception_on_cancellation` uses fixed-duration sleeps to coordinate thread cancellation timing, causing potential flakiness under high CPU load.

## Architecture Overview
- **Propagate mtime exceptions**: Modify `LudusaviAdapter.get_config_mtime_ns` to propagate exceptions rather than returning `None`. Update callers and tests accordingly.
- **isRpcStatus guard**: Update cache status check to explicitly verify it is a boolean and strictly `true` using `isRpcStatus`.
- **Promise.allSettled**: Replace `Promise.all` with `Promise.allSettled` to resolve independent background tasks separately.
- **Event-based test sync**: Use `threading.Event` to coordinate test thread execution deterministically.

## Core Data Structures
No changes to persistent data structures.

## Public Interfaces
Public API signatures remain unchanged.

## Dependency Requirements
No new dependencies.

## Testing Strategy
- Update existing tests for mtime stat failures.
- Add new test cases to verify that config read failures force a refresh.
- Run all tests using pytest.
- Verify typescript linting and compiling.
