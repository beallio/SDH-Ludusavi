# Code Review Refactors

## Problem Definition
Four issues were identified during a code review of the `feat/config-cache-qam-cleanup` branch:
1. `DeckySettingsStore` executes `self._manager.read()` in `__init__` without exception wrapping, causing potential startup crashes if the file is corrupted.
2. `SDHLudusaviService` merges settings and cache payloads in `_load_state` via `{**self.get_settings(), **cache_data}` which allows fields in `cache.json` to overwrite actual settings.
3. Redundant inline styles are present in the versions container in `src/index.tsx`.
4. Non-standard indentation is present on the Select Game dropdown in `src/index.tsx`.

## Architecture Overview
- Move the settings read operation from class instantiation (`__init__`) to the service read lifecycle (`read()`), allowing standard error handling wrappers to catch JSON/OS errors.
- Exclude keys in `SETTINGS_KEYS` from the cache payload load mapping inside `service.py`.
- Clean up redundant JSX layout styles and restore standard indentation on the frontend code.

## Core Data Structures
No change to core data structures. Settings keys remain `SETTINGS_KEYS = ("auto_sync_enabled", "selected_game", "notifications")`.

## Public Interfaces
Public RPC contracts and settings interfaces are entirely preserved.

## Dependency Requirements
No new dependencies are introduced.

## Testing Strategy
- Add a test case in `tests/test_main.py` mocking a settings manager initialization crash/read crash.
- Add a test case in `tests/test_service.py` where a populated `cache.json` containing settings keys is loaded, verifying settings are not overwritten.
- Run complete test suite and linters/typecheckers before commit:
  - `./run.sh uv run pytest`
  - `./run.sh uv run ruff check .`
  - `./run.sh uv run ty check py_modules/sdh_ludusavi/`
