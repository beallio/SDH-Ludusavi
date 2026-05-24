# Fix `_run_blocking` Event-Driven Completion

## Problem Definition

`main.py::_run_blocking` currently runs synchronous callbacks in a daemon
thread, but the async side polls a queue every 10ms with `asyncio.sleep(0.01)`.
That keeps cancellation safe, but adds avoidable latency to fast callbacks and
wakes the event loop repeatedly while long callbacks are still running.

## Architecture Overview

Keep the dedicated daemon worker thread so cancelled Decky RPC calls do not hold
the plugin process open. Replace queue polling with a loop-owned
`asyncio.Future` and an event-loop reader on a self-pipe. The worker stores its
completion result and writes one byte to the pipe; the loop reader drains the
pipe and resolves the future.

The worker must never mutate the `Future` directly. Completion is resolved from
the event-loop reader and becomes best-effort after cancellation or loop
shutdown.

## Core Data Structures

- `asyncio.Future[Any]`: loop-owned result/error carrier for the async caller.
- self-pipe file descriptors: event-driven wakeup without `asyncio.sleep`
  polling.
- `contextvars.Context`: copied before spawning the worker so synchronous
  callbacks keep context propagation.
- `threading.Thread`: daemon worker named `sdh-ludusavi-worker`.

## Public Interfaces

No public API changes.

- `_run_blocking(callback: Any) -> Any` keeps the same signature and return
  behavior.
- Backend RPC methods that call `Plugin._call` keep the same request/response
  behavior.

## Dependency Requirements

No third-party dependencies. The implementation uses Python standard library
modules already available on Python 3.12: `asyncio`, `contextvars`, `os`, and
`threading`.

## Testing Strategy

- Update the static `_run_blocking` regression so polling constructs are
  forbidden and event-driven completion constructs are required.
- Add/keep dynamic coverage for success, callback exception propagation,
  cancellation, cancellation logging, closed-loop late worker completion, and
  late worker exceptions after cancellation.
- Verify the red state with targeted tests before implementation.
- Run the required full validation suite before commit:
  - `./run.sh uv run ruff check . --fix`
  - `./run.sh uv run ruff format .`
  - `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  - `./run.sh uv run pytest`
  - `./run.sh pnpm run typecheck`
  - `./run.sh pnpm run build`
