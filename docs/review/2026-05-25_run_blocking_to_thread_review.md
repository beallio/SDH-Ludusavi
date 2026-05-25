# `_run_blocking` `asyncio.to_thread` Review Finding

Date: 2026-05-25

## Finding Reviewed

A review suggested replacing `main.py::_run_blocking` with `asyncio.to_thread()` or
`loop.run_in_executor()` because the current implementation uses `os.pipe()` and
`loop.add_reader()`.

## Verdict

The finding has limited generic merit but should not be accepted as a refactor item
for this codebase as written.

`asyncio.to_thread()` is the standard first-choice API for running synchronous work
from async Python code. However, this repository has already tried and documented
that approach, then moved away from it after local validation showed executor-style
completion did not reliably wake the loop in this environment.

The current self-pipe implementation is intentional hardening, not leftover
boilerplate.

## Current Contract

`main.py::_run_blocking` must preserve these properties:

- Synchronous backend callbacks run off the Decky Loader event loop.
- `contextvars.copy_context()` propagation remains intact.
- The worker thread is daemonized so cancelled Decky RPC calls do not keep the
  plugin process alive.
- Worker completion wakes the event loop without polling.
- Cancellation returns `asyncio.CancelledError` promptly.
- Late worker completion after cancellation or loop shutdown is best effort and
  must not emit loop or thread errors.
- Pipe descriptors are cleaned up on setup failure and cancellation.
- Late reader callbacks after cancellation must not read from or close a reused
  file descriptor integer.

## Evidence In The Checkout

- `tests/test_main.py::test_run_blocking_uses_event_driven_daemon_future_without_polling`
  explicitly requires the self-pipe design and forbids `asyncio.to_thread()` and
  `run_in_executor()`.
- `tests/test_issue_7_cancellation.py` covers cancellation, late worker exceptions,
  loop shutdown, setup-failure fd cleanup, and reused-fd safety.
- `docs/plans/fix_run_blocking_event_driven_completion.md` documents the decision
  to keep a dedicated daemon worker while replacing polling with an event-driven
  self-pipe.
- `docs/agent_conversations/2026-05-24_run_blocking_event_driven_completion.json`
  records that `call_soon_threadsafe` and `run_in_executor` were avoided after
  local validation showed delayed worker completions did not wake the loop reliably.
- `docs/plans/2026-05-25_codex_gpt-5_fix_run_blocking_fd_reuse_race.md` documents
  the later fd-reuse hardening while preserving the current self-pipe contract.

## Validation

The relevant targeted suite passed on 2026-05-25:

```text
./run.sh uv run pytest tests/test_issue_7_cancellation.py tests/test_main.py::test_run_blocking_uses_event_driven_daemon_future_without_polling tests/test_main.py::test_call_does_not_block_event_loop_while_callback_runs
```

Result:

```text
11 passed in 0.78s
```

## Recommended Disposition

Reject the requested refactor as scoped. It is based on generally sound asyncio
style guidance, but it does not account for this repository's validated Decky
runtime constraints and regression coverage.

If the issue remains useful, retitle it as an investigation:

```text
investigate: revalidate asyncio.to_thread for _run_blocking under Decky runtime
```

Any future replacement must prove the same cancellation, late-completion, loop
wakeup, daemon-worker, and fd-cleanup behavior before changing `main.py`.

Minimum acceptance criteria for a future investigation:

- Prove `asyncio.to_thread()` or `run_in_executor()` wakes the event loop reliably
  in the actual Decky runtime and local pytest.
- Preserve or explicitly replace daemon-worker shutdown behavior.
- Keep context propagation.
- Preserve `Plugin._call()` public behavior and response mapping.
- Keep or replace every relevant assertion in `tests/test_issue_7_cancellation.py`.
- Add a failing regression test before changing `_run_blocking`.
- Run the full wrapper validation suite before commit.
