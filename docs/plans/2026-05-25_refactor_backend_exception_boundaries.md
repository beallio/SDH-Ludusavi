# Refactor Backend Exception Boundaries

Date: 2026-05-25

## Summary

Implement a targeted exception-handling cleanup in the first-party backend only.
Narrow broad catches where the expected failure modes are known, keep broad catches
only where they are deliberate operation/logging/cleanup boundaries, and add concise
code comments explaining each retained broad catch.

No public API, RPC shape, plugin behavior, third-party dependency, or upstream
`pyludusavi` code changes.

## Key Changes

- In `py_modules/sdh_ludusavi/ludusavi.py`, import
  `pyludusavi.core.LudusaviError` and replace silent `except Exception: pass`
  blocks with targeted catches:
  - `get_aliases()`: catch Ludusavi command/config-shape failures, return `{}`,
    and log at debug.
  - `compare_recency()`: catch restore-preview Ludusavi/data-shape failures and
    return `"ambiguous"`; do not catch unrelated programming errors.
  - `get_conflict_metadata()`: catch expected Ludusavi/data-shape failures per
    metadata phase, preserve partial metadata, and log at debug.
  - `get_diagnostics()`: catch expected backup-path lookup failures and keep
    `backupPath = "unknown"`.
  - `get_config_mtime_ns()`: narrow to config/stat failures and replace
    `raise exc` with bare `raise`.

- In `py_modules/sdh_ludusavi/service.py`, narrow data-parsing catches:
  - Cached game coercion should catch `KeyError`, `TypeError`, and `ValueError`.
  - Status refresh coercion should catch `KeyError`, `TypeError`, and
    `ValueError`, continue dropping malformed entries, and keep existing error
    logging.
  - State/settings/cache JSON and filesystem handlers are already specific;
    leave them unchanged.

- Keep these broad `except Exception` blocks, but add explicit comments directly
  above them:
  - `DeckyLogHandler.emit`: intentionally follows `logging.Handler` behavior by
    routing normal handler failures to `handleError()`.
  - `resume_all_paused_processes()` and `_watchdog_loop()`: intentionally
    best-effort cleanup so one failed PID does not block other resume attempts.
  - Operation history wrappers and `_run_locked()`: intentionally broad
    normal-exception boundaries that record operation state/history and
    immediately re-raise.
  - Post-backup refresh handlers: intentionally best-effort after a successful
    backup so refresh failure does not convert backup success into failure.
  - Optional metadata/diagnostic fallbacks that must not block user-facing
    conflict prompts or initialization logs.

## Test Plan

- Add failing tests first.
- Adapter tests:
  - Ludusavi command errors in aliases, recency preview, conflict metadata,
    diagnostics, and config mtime paths use `LudusaviError` and preserve current
    fallback behavior.
  - An unrelated `RuntimeError` from adapter parsing code propagates for at
    least one narrowed path, proving unexpected bugs are no longer masked.
  - `get_config_mtime_ns()` re-raises with bare `raise`; add a static assertion
    that `raise exc` is absent.

- Service tests:
  - Malformed cached game entries are skipped for specific coercion failures.
  - Malformed refresh status entries are logged and dropped for specific coercion
    failures.
  - Operation failure history still records and re-raises callback failures.
  - Post-backup refresh failure still logs a warning and returns the completed
    backup result.
  - Retained broad catches have nearby `Intentionally broad` comments; enforce
    with a small static text/AST regression.

- Validation commands:
  - `./run.sh uv run pytest tests/test_ludusavi.py tests/test_service.py tests/test_adapter_cache.py`
  - `./run.sh uv run ruff check . --fix`
  - `./run.sh uv run ruff format .`
  - `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  - `./run.sh uv run pytest`

## Assumptions

- The implementation should stay in first-party `py_modules/sdh_ludusavi/` code
  and tests; do not modify vendored/upstream `py_modules/pyludusavi`.
- `except Exception` is acceptable only when documented as a deliberate boundary
  and when `BaseException` subclasses still propagate.
- README updates are not required because this is backend maintainability work
  without user-facing behavior or usage changes.
- Record the implementation session afterward in
  `docs/agent_conversations/2026-05-25_refactor_backend_exception_boundaries.json`.
