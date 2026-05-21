# Implementation Plan: Refactor `_run_blocking` Async Polling

## Problem Definition
The current implementation of `_run_blocking` in `main.py` is used to execute
synchronous service methods in a background thread to prevent blocking the Decky
Loader async event loop. It already uses an `asyncio.Future` and
`loop.call_soon_threadsafe()` for thread-safe completion, but it waits for that
future through a 50ms polling loop:

```python
while True:
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=0.05)
    except TimeoutError:
        continue
```

This keeps cancellation responsive, but it wakes the event loop roughly 20 times
per second for every long backup, restore, or scan. Each wakeup recreates a
timeout wrapper, schedules work, catches `TimeoutError`, and loops even though
the worker thread has not completed.

Research findings:

- Decky Loader plugins expose Python methods callable from TypeScript and run in
  a plugin process; the official loader README calls out Python backend support,
  and the plugin template uses async backend methods plus lifecycle hooks.
- Decky's plugin import module strongly recommends using
  `DECKY_PLUGIN_SETTINGS_DIR`, `DECKY_PLUGIN_RUNTIME_DIR`, and
  `DECKY_PLUGIN_LOG_DIR`; this change does not alter storage or lifecycle paths.
- Reviewed Decky plugin examples show backend methods are commonly declared
  `async`, with synchronous file/network work sometimes performed directly. This
  plugin is stricter because Ludusavi operations can be long-running, so it must
  keep the existing worker-thread bridge instead of moving blocking calls into
  Decky's event loop.
- Python 3.12 `asyncio` documents that awaiting a Future suspends the task until
  the Future is resolved, and that `shield()` prevents cancellation of the inner
  awaitable while still raising `CancelledError` in the cancelled caller. The
  docs also describe `wait_for()` as a timeout wrapper, which is unnecessary
  when no timeout behavior is desired.

## Architecture Overview
Keep the current dedicated worker thread, `contextvars.copy_context()`, and
thread-safe `loop.call_soon_threadsafe()` completion path. Replace only the
polling wait loop with a direct shielded await:

```python
try:
    return await asyncio.shield(future)
except asyncio.CancelledError:
    decky.logger.warning(...)
    raise
```

Do not switch to `asyncio.to_thread()` or `loop.run_in_executor()` in this pass.
Prior hardening work found executor-style rewrites risky in this checkout, and
the current manual bridge already preserves the needed context propagation,
thread naming, cancellation logging, and closed-loop safety.

## Core Data Structures
No new persistent data structures.

The existing local structures remain:

- `asyncio.Future` created on the Decky event loop.
- copied `contextvars.Context` used by the worker thread.
- daemon `threading.Thread` named `sdh-ludusavi-worker`.

## Public Interfaces
- `main.py::_run_blocking(callback: Any) -> Any`: Signature remains identical. The internal behavior changes from polling to awaiting a Future.

## Dependency Requirements
- Built-in `asyncio` and `threading` (already imported).
- No package or Decky API dependency changes.

## Testing Strategy
- Update the static regression in `tests/test_main.py` so `_run_blocking` must
  keep `create_future`, `call_soon_threadsafe`, and `shield`, while forbidding
  `wait_for`, timeout polling, `sleep`, `queue`, `pipe`, `add_reader`, and
  `remove_reader`.
- Run the updated targeted test first and confirm it fails before the
  implementation change:
  `./run.sh uv run pytest tests/test_main.py::test_run_blocking_awaits_threadsafe_future_without_polling`
- Implement the minimal change in `main.py`.
- Re-run targeted `_run_blocking` tests:
  `./run.sh uv run pytest tests/test_main.py::test_run_blocking_awaits_threadsafe_future_without_polling tests/test_main.py::test_call_does_not_block_event_loop_while_callback_runs tests/test_issue_7_cancellation.py`
- Run required validation before commit:
  `./run.sh uv run ruff check . --fix`
  `./run.sh uv run ruff format .`
  `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  `./run.sh uv run pytest`

## Reviewed References

- Decky Loader README:
  https://github.com/SteamDeckHomebrew/decky-loader
- Decky plugin template README and `main.py`:
  https://github.com/SteamDeckHomebrew/decky-plugin-template
- Decky plugin imports module:
  https://github.com/SteamDeckHomebrew/decky-loader/blob/main/backend/decky_loader/plugin/imports/decky.py
- SteamGridDB Decky plugin `main.py`:
  https://github.com/SteamGridDB/decky-steamgriddb/blob/main/main.py
- Python 3.12 `asyncio` task documentation:
  https://docs.python.org/3.12/library/asyncio-task.html
