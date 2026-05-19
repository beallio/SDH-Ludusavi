# Fix `_run_blocking` Closed Event Loop Completion

## Problem Definition

Cancelling `_run_blocking` can let the awaiting coroutine close its event loop while
the daemon worker thread is still running. When that worker later completes, it calls
`loop.call_soon_threadsafe(...)` against a closed loop and prints a background-thread
`RuntimeError: Event loop is closed` after pytest has already reported success.

## Architecture Overview

Keep the existing dedicated worker-thread and Future-based signaling model, but make
worker completion best-effort after cancellation. Completion should return without
raising if the loop is already closed.

## Core Data Structures

No data structure changes.

## Public Interfaces

No public backend RPC or frontend interface changes.

## Dependency Requirements

No dependency changes.

## Testing Strategy

- Add a regression test that cancels `_run_blocking`, closes the event loop before the
  worker finishes, waits for the worker to complete, and asserts `threading.excepthook`
  receives no uncaught worker exception.
- Re-run existing `_run_blocking` cancellation and nonblocking tests.
- Run Ruff, `ty`, and the full pytest suite before committing.
