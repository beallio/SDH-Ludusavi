# Fix `_run_blocking` Read FD Reuse Race

Date: 2026-05-25
Planner Model: codex_gpt-5
Review Source: `docs/review/2026-05-24_gemini_3_5_flash.md`

## Execution Skill

Execute this plan with the `implementer` skill. The implementation must follow that
skill's discovery, branch isolation, strict TDD, atomic commit, validation, and
review-gate workflow, while also honoring this repository's `AGENTS.md` protocol.

## Problem Definition

`main.py::_run_blocking` uses a loop-owned read file descriptor and a worker-owned
write file descriptor as a self-pipe wakeup. The event-loop reader callback closes
the read descriptor after draining the completion signal. The cancellation path also
removes the reader and closes that same read descriptor.

If cancellation closes `read_fd` while `read_completion_signal()` has already been
queued by the event loop, the queued callback can run later and call `os.close()` on
the same integer again. On Unix, file descriptor integers can be reused immediately.
A late second close can therefore close an unrelated resource that happened to reuse
the same descriptor number.

The implementation must make read descriptor cleanup idempotent inside the event-loop
thread and preserve the current `_run_blocking` contract:

- synchronous callbacks execute in a daemon worker thread
- `contextvars.copy_context()` propagation remains intact
- worker completion remains event-driven through `loop.add_reader`
- cancellation still raises `asyncio.CancelledError` promptly
- late worker completion after cancellation or loop shutdown remains best effort

## Architecture Overview

Add a single closure-scoped ownership guard for the read descriptor. All paths that
currently close or read from `read_fd` after cancellation should go through the guard:

- reader callback after `os.read`
- `loop.add_reader` / `thread.start` setup failure cleanup
- cancellation cleanup

The write descriptor remains worker-owned after the worker thread starts. Before
thread start succeeds, setup failure cleanup still closes the write descriptor.

```mermaid
sequenceDiagram
    participant Caller as Awaiting Task
    participant Loop as Event Loop
    participant Reader as read_completion_signal
    participant Worker as Worker Thread
    participant OS as OS FD Table

    Caller->>Loop: await _run_blocking(callback)
    Loop->>OS: os.pipe() => read_fd, write_fd
    Loop->>Loop: add_reader(read_fd, read_completion_signal)
    Loop->>Worker: start daemon thread
    Caller->>Loop: task.cancel()
    Loop->>Loop: remove_reader_if_active()
    Loop->>OS: close_read_fd()
    Worker-->>OS: write(write_fd, "x") after callback
    OS-->>Loop: reader callback may already be queued
    Reader->>Loop: remove_reader_if_active()
    Reader->>Reader: if read_fd_closed, skip os.read and close
    Reader->>Loop: future.done() => return
```

## Core Data Structures

- `read_fd_closed: bool`: closure-scoped flag protecting exactly-once read descriptor
  close attempts.
- `close_read_fd() -> None`: helper that sets `read_fd_closed` before calling
  `close_fd(read_fd)`.
- `read_fd_closed` guard in `read_completion_signal()`: prevents both a second
  `close()` and a late `os.read()` against a reused descriptor integer.
- Existing structures remain unchanged:
  - `future: asyncio.Future[Any]`
  - `completion: tuple[str, Any] | None`
  - `completion_lock: threading.Lock`
  - `reader_registered: bool`
  - `thread_started: bool`

## Public Interfaces

No public API changes.

- `_run_blocking(callback: Any) -> Any` keeps the same signature and behavior.
- `Plugin._call(...)` response mapping remains unchanged.
- Backend RPC methods remain unchanged.

## Implementation Steps

1. Add `read_fd_closed = False` next to `reader_registered` and `thread_started`.
2. Add `close_read_fd()` below `close_fd()`.
3. Replace every `close_fd(read_fd)` call in `_run_blocking` with
   `close_read_fd()`.
4. Guard `os.read(read_fd, 1)` in `read_completion_signal()` with
   `if not read_fd_closed`.
5. Keep `close_fd(write_fd)` unchanged in worker and pre-thread setup failure paths.
6. Do not add locks around `read_fd_closed`; all read descriptor close calls happen
   on the event-loop thread in current control flow.
7. Preserve the existing `remove_reader_if_active()` behavior before closing the read
   descriptor.

## Example Code

```python
read_fd_closed = False

def close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        return

def close_read_fd() -> None:
    nonlocal read_fd_closed
    if read_fd_closed:
        return
    read_fd_closed = True
    close_fd(read_fd)
```

Use the helper from all read descriptor cleanup paths:

```python
def read_completion_signal() -> None:
    remove_reader_if_active()
    if not read_fd_closed:
        try:
            os.read(read_fd, 1)
        except OSError:
            pass
        close_read_fd()
    ...

except asyncio.CancelledError:
    decky.logger.warning(
        "SDH-ludusavi operation was cancelled while worker may still be running"
    )
    remove_reader_if_active()
    close_read_fd()
    future.cancel()
    raise
```

## Testing Strategy

Strict TDD applies because this is behavior-changing runtime code.

Add a failing regression test first in `tests/test_issue_7_cancellation.py`.
The test should prove a queued reader callback cannot close a reused descriptor after
cancellation has already closed the original `read_fd`.

Recommended deterministic test shape:

1. Create a new event loop.
2. Monkeypatch `loop.add_reader` to capture the callback instead of relying on real
   selector timing.
3. Monkeypatch `main_module.os.pipe` to return controlled descriptors.
4. Start `_run_blocking` with a slow callback.
5. Cancel and await the task.
6. Open a new descriptor after cancellation to encourage descriptor reuse.
7. Invoke the captured reader callback manually.
8. Assert the newly opened descriptor remains valid and no byte was read from it.

Example test skeleton:

```python
def test_run_blocking_reader_callback_after_cancel_does_not_close_reused_fd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.new_event_loop()
    captured_reader: list[Callable[[], None]] = []

    def capture_reader(_fd: int, callback: Callable[[], None]) -> None:
        captured_reader.append(callback)

    async def scenario() -> int:
        monkeypatch.setattr(loop, "add_reader", capture_reader)
        task = asyncio.create_task(_run_blocking(lambda: time.sleep(0.05)))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        replacement_fd = os.open(os.devnull, os.O_RDONLY)
        captured_reader[0]()
        return replacement_fd

    try:
        replacement_fd = loop.run_until_complete(scenario())
        os.fstat(replacement_fd)
    finally:
        _close_if_open(replacement_fd)
        loop.close()
```

Adjust the exact monkeypatching as needed to match current test helpers. The important
assertion is that the replacement descriptor survives the late callback and the late
callback does not read from the replacement descriptor.

Existing tests to rerun:

- `tests/test_issue_7_cancellation.py`
- `tests/test_main.py::test_run_blocking_uses_event_driven_daemon_future_without_polling`
- `tests/test_main.py::test_call_does_not_block_event_loop_while_callback_runs`

## Validation

Targeted validation:

```bash
./run.sh uv run pytest tests/test_issue_7_cancellation.py tests/test_main.py::test_run_blocking_uses_event_driven_daemon_future_without_polling tests/test_main.py::test_call_does_not_block_event_loop_while_callback_runs
```

Full validation before commit:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

## Acceptance Criteria

- `read_fd` can only be closed once by `_run_blocking`.
- A late reader callback cannot `os.read()` from a reused descriptor after
  cancellation has closed the original read descriptor.
- Cancellation still logs the existing warning.
- Callback success and exception propagation still behave as before.
- Setup failures still close both pipe descriptors when the worker did not start.
- Late worker completion after cancellation produces no event-loop or thread errors.
