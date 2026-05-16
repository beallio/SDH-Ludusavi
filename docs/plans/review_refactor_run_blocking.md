# Implementation Plan: Refactor `_run_blocking` Busy-Wait

## Problem Definition
The current implementation of `_run_blocking` in `main.py` is used to execute synchronous service methods in a background thread to prevent blocking the Decky Loader async event loop. However, it uses a `queue.Queue` with a busy-wait loop (`while True: await asyncio.sleep(0.05)`) to check for results. This polling approach is CPU-inefficient and non-idiomatic for asynchronous Python.

## Architecture Overview
Instead of polling a thread-safe queue, the background thread should signal completion directly to the async event loop using an `asyncio.Future` and `loop.call_soon_threadsafe`.
1. `_run_blocking` creates an `asyncio.Future`.
2. It captures the current `asyncio.get_running_loop()`.
3. The background thread executes the synchronous `callback`.
4. Upon completion (or exception), the background thread uses `loop.call_soon_threadsafe` to set the result or exception on the Future.
5. The main async function simply `await`s the Future.

*Alternatively, `asyncio.to_thread` could be used, but since Decky environments might have specific context or loop requirements, building a robust `Future` resolution guarantees compatibility with the existing `contextvars.copy_context()` requirements.*

## Core Data Structures
No new data structures.

## Public Interfaces
- `main.py::_run_blocking(callback: Any) -> Any`: Signature remains identical. The internal behavior changes from polling to awaiting a Future.

## Dependency Requirements
- Built-in `asyncio` and `threading` (already imported).

## Testing Strategy
- Run the backend test suite: `./run.sh uv run pytest`
- Specifically, ensure `test_concurrent_operations_are_rejected_by_thread_safe_lock` in `tests/test_service.py` and any tests in `test_main.py` pass.
- Verify cancellation handling: Ensure that if the future is cancelled, the thread can still safely exit without crashing the plugin.
