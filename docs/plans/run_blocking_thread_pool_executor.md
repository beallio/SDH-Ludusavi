# Replace `_run_blocking` with a shared `ThreadPoolExecutor`

**Plan name (used for markers/files):** `run_blocking_thread_pool_executor`

## Problem Definition

`main.py`'s `_run_blocking` (lines 450–545, ~96 lines) spawns a dedicated daemon thread per
RPC call and signals completion back to the event loop through an `os.pipe` +
`loop.add_reader` mechanism. That machinery existed because a worker could hang *forever*
(unbounded subprocess timeouts) and daemon threads die with the process, while
`ThreadPoolExecutor` threads are non-daemon and would hold Decky's process open on shutdown.

That justification is gone. Backlog items B2 and B3 landed: every Ludusavi/rclone subprocess
call is now bounded (`LUDUSAVI_OPERATION_TIMEOUT_SECONDS = 900`,
`LUDUSAVI_PREVIEW_TIMEOUT_SECONDS = 300`, `backups_list` at pyludusavi's 30s default,
discovery `_VERIFY_TIMEOUT_SECONDS`), and the watchdog has an unconditional resume ceiling
(`WATCHDOG_ABSOLUTE_RESUME_SECONDS = 960`). The worst a worker can run is ~15 minutes, so a
bounded, shared, non-daemon thread pool is safe — at worst a pathological shutdown waits out
an in-flight operation, and `shutdown(wait=False, cancel_futures=True)` in `_unload`
discards anything still queued.

This change deletes the pipe/reader/daemon-thread machinery and routes all RPC offloading
through one `ThreadPoolExecutor(max_workers=4, thread_name_prefix="sdh-rpc")`.

### Facts verified during planning (2026-06-11) — re-verify in Step 1

- All B2/B3 prerequisite gates pass in the current tree.
- The AST pin test `test_run_blocking_uses_event_driven_daemon_future_without_polling` is at
  `tests/test_main.py:145`.
- The must-pass-unmodified behavioral tests are at `tests/test_main.py:174–252`.
- A bare `await loop.run_in_executor(self._executor, callback)` silently drops
  `contextvars` propagation, which the current implementation provides via
  `contextvars.copy_context()` / `context.run(callback)`. Nothing in `py_modules/` uses
  contextvars today (verified by grep), but to keep semantics identical we preserve it with
  `functools.partial(context.run, callback)` — the same trick `asyncio.to_thread` uses.
- Python is 3.12 (`.python-version`, `requires-python = ">=3.12"`), so
  `shutdown(cancel_futures=True)` (3.9+) is available.
- One *new* (acceptable, slightly better) behavior: a call still **queued** (not yet
  running) when its awaiting coroutine is cancelled will never execute
  (`concurrent.futures` cancels unstarted work). Today every call starts immediately, so
  this path never existed. Do not try to "fix" this.

## Architecture Overview

- `Plugin.__init__` owns a single `ThreadPoolExecutor(max_workers=4,
  thread_name_prefix="sdh-rpc")`. The executor spawns threads lazily on first submit, so
  construction is free.
- `_call` keeps its exact exception-mapping contract and delegates to a module-level
  `async def _run_blocking(executor, callback)` that is a thin wrapper around
  `loop.run_in_executor`.
- `_unload` shuts the executor down with `shutdown(wait=False, cancel_futures=True)` in its
  `finally` block, after the `unload_stop` offload (which itself uses the executor).
- `max_workers=4` rationale: one slot for the single long-running operation, one for a
  refresh, headroom for frontend status/log pollers. The coordinator rejects concurrent
  operations fast, but the rejection happens *inside* the worker callback, so a queued call
  needs a free thread just to return `operation_running`. If queue latency ever shows up in
  diagnostics, the fix is a bigger pool, not thread-per-call.

## Core Data Structures

- `Plugin._executor: ThreadPoolExecutor` — the shared pool, created in `__init__`, shut down
  in `_unload`.
- No other new state. The pipe FDs, completion tuple, locks, and reader-registration flags
  in the old `_run_blocking` are all deleted.

## Public Interfaces

- No RPC signature changes. Every `Plugin` async method keeps its name, parameters, and
  return shapes.
- `_run_blocking(executor: ThreadPoolExecutor, callback: Any) -> Any` — module-level, gains
  the `executor` parameter (internal helper; the AST test depends on the name and
  module-level position).

## Dependency Requirements

Stdlib only (`concurrent.futures`, `functools`). No new packages; `pyproject.toml` and
`uv.lock` unchanged.

## Testing Strategy

TDD (red → green). Rewrite the AST pin test to assert the new implementation shape; add one
new `_unload` shutdown test; the six existing behavioral tests are the contract and must
pass **unmodified**. Details in Steps 3–4 below.

---

## Execution protocol for the implementing agent

1. **Invoke the `implementer` skill first** (Skill tool, skill: `implementer`). Follow its
   guardrails for the whole session.
2. Perform read-only verification (`pwd`, `ls`, `git status`, inspect `pyproject.toml` /
   `uv.lock` / `run.sh`), then output the `AGENT_PROTOCOL_HANDSHAKE` block required by
   `CLAUDE.md` §1 before any modification.
3. Run all project tooling through `./run.sh` (e.g. `./run.sh uv run pytest`). Never run
   bare `pytest`/`ruff`/`ty`. Caches live under `/tmp/sdh_ludusavi/` via the wrapper.
4. **Branch:** start from the current tip of `fix/thread-safety-history-registry` (it
   contains B2, B3, and the item-7 history/registry locks this work sequences after).
   Create `refactor/run-blocking-executor` from it:
   `git checkout -b refactor/run-blocking-executor`
5. If `git status --short` shows uncommitted changes you did not create — other than this
   plan document, which is expected to be present and untracked — stop and report
   (CLAUDE.md §18).
6. Do NOT push, tag, or release anything. Local commits only.
7. Do NOT modify anything under `py_modules/pyludusavi/` (upstream-adjacent package).

---

## Step 1 — Prerequisite gates (read-only; STOP on any failure)

Run each command and check the expected result:

| # | Command | Expected |
|---|---------|----------|
| 1 | `grep -rn "timeout=None" py_modules/sdh_ludusavi/` | no output |
| 2 | `grep -c "LUDUSAVI_PREVIEW_TIMEOUT_SECONDS" py_modules/sdh_ludusavi/ludusavi.py` | ≥ 4 (currently 7) |
| 3 | `grep -n "WATCHDOG_ABSOLUTE_RESUME_SECONDS" py_modules/sdh_ludusavi/constants.py py_modules/sdh_ludusavi/watchdog.py` | constant defined (= operation timeout + 60) and used in `watchdog.py` |
| 4 | `grep -n "timeout=" py_modules/pyludusavi/discovery.py` | shows `_VERIFY_TIMEOUT_SECONDS` bounds (currently lines 93 and 102) |
| 5 | `./run.sh uv run pytest tests/test_watchdog.py -q` | passes; includes the absolute-resume-ceiling test (~line 111) |
| 6 | `./run.sh uv run pytest -q` | full suite green before any change |

If gate 1–4 fails, B2/B3 did not land as specified — **do not proceed**; report which gate
failed instead. (Planning-time check on 2026-06-11: all passed.)

## Step 2 — Commit this plan document (commit 1)

This file (`docs/plans/run_blocking_thread_pool_executor.md`) already exists in the working
tree. On your new branch, stage and commit it:

```
docs(plans): add run_blocking thread pool executor plan
```

## Step 3 — RED: rewrite/add tests (do NOT commit while red — pre-commit runs pytest)

All edits in `tests/test_main.py`.

### 3a. Rewrite the AST pin test (currently `tests/test_main.py:145–171`)

Replace `test_run_blocking_uses_event_driven_daemon_future_without_polling` entirely
(rename it — do not delete the slot) with:

```python
def test_run_blocking_uses_shared_executor_without_pipes_or_threads() -> None:
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    run_blocking = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_blocking"
    )
    names = {node.id for node in ast.walk(run_blocking) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(run_blocking) if isinstance(node, ast.Attribute)}

    assert "run_in_executor" in attributes
    assert "copy_context" in attributes
    assert "pipe" not in attributes
    assert "add_reader" not in attributes
    assert "remove_reader" not in attributes
    assert "Thread" not in attributes
    assert "shield" not in attributes
    assert "sleep" not in attributes
    assert "to_thread" not in attributes
    assert "queue" not in names
```

### 3b. Add the new `_unload` shutdown test

Place it after `test_unload_logs_synchronous_stop_fallback_failure` (~line 495):

```python
def test_unload_shuts_down_executor_and_post_shutdown_call_fails_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    asyncio.run(plugin._unload())

    result = asyncio.run(plugin._call("post_unload", lambda: "should not run"))

    assert result["status"] == "failed"
    assert logger.exceptions == ["post_unload failed"]
```

(This matches the `_unload` ordering guarantee: shutdown happens in `_unload`'s `finally`,
so a post-unload `_call` fails cleanly — the executor raises
`RuntimeError("cannot schedule new futures after shutdown")`, which `_call` maps to a
`{"status": "failed"}` dict. Do not assert on the RuntimeError message text.)

### 3c. Verify red

`./run.sh uv run pytest tests/test_main.py -q` → exactly these two tests fail
(3a fails its assertions against the current implementation; 3b fails because
`Plugin` has no `_executor`). Every other test still passes.

## Step 4 — GREEN: implement in `main.py`

### 4a. Imports (top of `main.py`)

Add:

```python
import functools
from concurrent.futures import ThreadPoolExecutor
```

Keep `asyncio`, `contextvars`, `os`, `threading` — all still used (`os.environ` at
`main.py:421`, `threading.Lock` for `_backend_lock`, `contextvars` in the new
`_run_blocking`).

### 4b. `Plugin.__init__` (main.py:52–54)

Add the shared executor:

```python
def __init__(self) -> None:
    self._backend: SDHLudusaviService | None = None
    self._backend_lock = threading.Lock()
    self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sdh-rpc")
```

### 4c. `_call` (main.py:406)

Change the single line:

```python
return await _run_blocking(callback)
```

to:

```python
return await _run_blocking(self._executor, callback)
```

**Everything else in `_call` — the `OperationLockedError` / `Exception` /
`CancelledError` / `BaseException` clause ordering and the returned dicts — stays
byte-for-byte identical.** Exceptions (including `BaseException` subclasses) propagate out
of `run_in_executor` exactly as they did out of the pipe machinery, because
`concurrent.futures` worker threads catch `BaseException` and set it on the future.

### 4d. Replace `_run_blocking` (main.py:450–545) entirely

Delete the whole function (pipe creation, `add_reader`, FD close handling,
completion-signal write, `asyncio.shield`) and replace with — keep it a module-level
`async def` named `_run_blocking` so the AST test can find it in `tree.body`:

```python
async def _run_blocking(executor: ThreadPoolExecutor, callback: Any) -> Any:
    """
    Run a synchronous callback on the shared RPC executor without blocking
    the event loop. Cancelling the awaiting coroutine cannot interrupt a
    callback that is already running; the work finishes in the background
    and its result is discarded.
    """
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    try:
        return await loop.run_in_executor(executor, functools.partial(context.run, callback))
    except asyncio.CancelledError:
        decky.logger.warning(
            "SDH-ludusavi operation was cancelled while worker may still be running"
        )
        raise
```

Semantics consciously preserved:
- **Exception mapping:** untouched in `_call` (4c).
- **Cancellation:** equivalent to today's `asyncio.shield` arrangement for a *running*
  callback — the await raises `CancelledError`, the warning is logged, the worker finishes
  in the background. (Queued-not-started callbacks are additionally cancelled for real;
  acceptable, see Problem Definition.)
- **contextvars:** preserved via `copy_context` + `functools.partial(context.run, callback)`.

### 4e. `_unload` shutdown (main.py:378, the `finally` block)

Add the executor shutdown as the **first** statement of the existing `finally` block, so it
runs after the `unload_stop` offload (which itself uses the executor) on success,
failure-fallback, and cancellation paths alike:

```python
finally:
    self._executor.shutdown(wait=False, cancel_futures=True)
    log_fn = getattr(backend, "log", None) if backend is not None else None
    ...  # existing logging unchanged
```

`shutdown()` is idempotent, so repeated `_unload` calls are safe.

### 4f. Verify green

`./run.sh uv run pytest -q` → entire suite passes, including unmodified:

- `test_call_does_not_block_event_loop_while_callback_runs` (tests/test_main.py:174)
- `test_call_maps_operation_locked_error_from_worker_thread` (:197)
- `test_call_maps_generic_exception_from_worker_thread` (:218)
- `test_call_maps_base_exception_from_worker_thread` (:235)
- `test_unload_does_not_block_event_loop_while_stop_runs` (:391)
- `test_is_game_cache_current_does_not_block_event_loop` (:700)

**HARD RULE: if any of those tests needs editing to pass, the replacement has changed
semantics — stop, revert the test edit, and reassess the implementation instead.** They are
the real contract.

## Step 5 — Quality gates, then commit 2

```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

All must pass. Restrict any formatting fallout to files changed this session (`main.py`,
`tests/test_main.py`). Then commit tests + implementation together (committing the red tests
separately is impossible because the pre-commit hook runs pytest):

```
refactor(rpc): replace pipe-based _run_blocking with shared ThreadPoolExecutor
```

Stage only: `main.py`, `tests/test_main.py`.

## Step 6 — Session log (commit 3)

Write `docs/agent_conversations/2026-06-11_run_blocking_thread_pool_executor.json` (or
today's actual date) with: date, task objective, files modified, tests added, design
decisions (executor in `__init__`, contextvars preserved via partial, shutdown in `_unload`
finally, no shield), results (test counts, gate outcomes). Commit:

```
docs: agent session log for run_blocking thread pool executor
```

## Step 7 — Completion marker and review-notes loop

1. Write an **empty** file:
   `/tmp/SDH-ludusavi/run_blocking_thread_pool_executor_finished`
   (note: this is the literal directory `/tmp/SDH-ludusavi/` — the existing marker
   convention directory, distinct from the `run.sh` cache dir `/tmp/sdh_ludusavi/`).
   Create the directory first if it does not exist.
2. Then poll in a loop for follow-up review notes:
   - Every **60 seconds**, check for
     `/tmp/SDH-ludusavi/run_blocking_thread_pool_executor_review.md`.
   - **If it appears and states the review PASSED:** no action required — end the session.
   - **If it appears with findings:** read it, address every note (using TDD where the note
     changes behavior), re-run the full Step 5 quality gates, commit the fixes with a
     Conventional Commit, rename the consumed file to
     `/tmp/SDH-ludusavi/run_blocking_thread_pool_executor_review_addressed.md`
     (increment a numeric suffix if it already exists), re-create the `_finished` marker
     (the reviewer may have deleted it), and continue polling with a fresh 30-minute window.
   - **If 30 minutes pass with no review file:** end the session, reporting that no review
     notes arrived.

---

## Do-not-touch list (for the implementer)

- `py_modules/pyludusavi/**` — upstream-adjacent, off limits.
- The six behavioral tests listed in 4f — must pass unmodified.
- `_call`'s exception-mapping clauses and returned dicts.
- The `log()` RPC (main.py:193) — intentionally stays on the event loop; do not route it
  through the executor.
- No pushes, tags, releases, or version bumps.

## Verification (end-to-end)

1. Full suite: `./run.sh uv run pytest` → green.
2. Machinery gone: `grep -n "os.pipe\|add_reader\|asyncio.shield" main.py` → no output.
3. Pool present: `grep -n "ThreadPoolExecutor(max_workers=4" main.py` → one hit in
   `Plugin.__init__`; `grep -n "run_in_executor" main.py` → one hit in `_run_blocking`.
4. Shutdown wired: `grep -n "shutdown(wait=False, cancel_futures=True)" main.py` → one hit
   inside `_unload`'s `finally`.
5. Line count: `_run_blocking` shrinks from ~96 lines to ~15.
6. Definition of Done (CLAUDE.md §16): ruff check ✓, ruff format ✓, ty ✓, pytest via
   `./run.sh` ✓, README unchanged (no user-visible behavior change), no dependency changes,
   caches under /tmp ✓, session log recorded ✓.
