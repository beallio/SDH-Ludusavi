# Implementation Plan - Initial Load Optimization

## Problem Definition
Opening the QAM (Quick Access Menu) panel for the first time displays a blocking loading spinner for ~1.5 seconds. This occurs because the frontend `loadInitial()` function executes a blocking `Promise.all` containing `getVersions()` and `getLudusaviCommandCall()`.
* `getVersions()` calls `get_versions` on the backend, which lazily initializes `PyludusaviAdapter`. This initialization executes 3 synchronous CLI subprocesses (`ludusavi --version`, `ludusavi config path`, and `ludusavi config show`) to gather and log diagnostic details.
* `getLudusaviCommandCall()` calls `find_ludusavi` which performs discovery checks on disk.

Since these versions and command paths are not required to display the settings or games lists, blocking the initial render on them is unnecessary.

## Architecture Overview
1. **Frontend Optimization**:
   Refactor `loadInitial` to only wait for `getSettings()` before dismissing the loading spinner. Defer `getVersions()` and `getLudusaviCommandCall()` to resolve in the background asynchronously. The initial state of versions will be set to `"Loading..."` for each version field, transitioning to the actual versions once loaded. If loading fails or returns an error status, it falls back to `"Unknown"` (or the specific error message) to prevent showing a perpetual loading state.
2. **Backend Optimization**:
   Refactor backend diagnostics logging `_log_ludusavi_diagnostics` to run in a background daemon thread, preventing any lazy-initialization RPC call from blocking on subprocess execution.

## Core Data Structures
No changes to database schemas or state file structures. Caching behavior for settings and games list remains unchanged.

## Public Interfaces
All frontend RPC interfaces and backend RPC methods (`get_versions`, `get_ludusavi_command`) remain identical. No API contracts are altered.

## Dependency Requirements
None.

## Testing Strategy
1. **Static Frontend Tests**:
   Ensure `tests/test_frontend_static.py` is updated to verify the new asynchronous call sequence in `loadInitial()`.
2. **Backend Unit Tests**:
   - Write a unit test in `tests/test_service.py` to verify that `_log_ludusavi_diagnostics` runs concurrently/asynchronously.
   - Run the entire test suite `pytest` to verify all 230 existing tests still pass.
