# Implementation Plan: Optimize Logging Import in Hot-Path

## Problem Definition
In `py_modules/sdh_ludusavi/service.py`, the `_decky_log` function executes a `try: import decky` statement every time a log is emitted. Because this function is called frequently (especially during backend operations like backups or status refreshes), the repeated import attempt—even with Python's module caching—adds unnecessary execution overhead and clutters the hot-path.

## Architecture Overview
The Decky module presence should be resolved once at the module level, rather than on every function call.

1. At the top of `service.py` (or right after the standard imports), attempt to import `decky` and store its logger reference in a private module-level variable (e.g., `_DECKY_LOGGER`).
2. If the import fails, set `_DECKY_LOGGER = None`.
3. Update `_decky_log` to simply check `if _DECKY_LOGGER:` and use it, bypassing the need for a `try/except` block and an `import` statement on every invocation.

## Core Data Structures
- Module-level variable: `_DECKY_LOGGER` (type: `logging.Logger | None` or `Any`).

## Public Interfaces
- `_decky_log(level: str, message: str) -> None`: Signature remains identical.

## Dependency Requirements
- None.

## Testing Strategy
- Run the backend test suite: `./run.sh uv run pytest`
- Ensure that standard pytest captures the logs and does not throw `ImportError` or `NameError` in a pure Python environment where `decky` is not installed.
- Ensure no regressions in `test_service.py`.