# Review: Replace `_run_blocking` with a shared `ThreadPoolExecutor`

- **Date:** 2026-06-11
- **Branch:** `refactor/run-blocking-executor`
- **Plan:** `docs/plans/run_blocking_thread_pool_executor.md`
- **Result:** PASSED (round 2)

## Scope reviewed

Commits `47e3597` (plan), `ec94fc4` (implementation), `ea2c61e` (session log),
`9e8a0bb` (restored contract tests).

## Round 1 — CHANGES REQUIRED

Implementation matched the plan exactly: shared
`ThreadPoolExecutor(max_workers=4, thread_name_prefix="sdh-rpc")` in `Plugin.__init__`,
`_call` delegating to the new ~15-line `_run_blocking` (contextvars preserved via
`functools.partial(context.run, callback)`, cancellation warning log kept, no shield),
`shutdown(wait=False, cancel_futures=True)` first in `_unload`'s `finally`. AST pin test
rewritten as specified; new post-shutdown `_call` test added; the six behavioral contract
tests in `tests/test_main.py` passed unmodified.

One finding: `tests/test_issue_7_cancellation.py` was deleted wholesale. Four of its tests
were legitimately obsolete (monkeypatched `os.pipe` / `add_reader` / `Thread.start`
internals), but five were implementation-agnostic behavioral contracts — including the only
test pinning the cancellation warning log — and had to be restored against the new
signature.

## Round 2 — PASSED

`tests/test_run_blocking_contract.py` restores the five contract tests exactly as required
(success, cancellation, cancellation warning log, worker exception propagation, late
worker exception after cancellation produces no loop error), adapted to
`_run_blocking(executor, callback)`. `main.py` and `tests/test_main.py` unchanged since
round 1. Session log updated.

## Gates (verified independently by reviewer)

- `./run.sh uv run ruff check .` — passed
- `./run.sh uv run ruff format --check .` — 108 files already formatted
- `./run.sh uv run ty check py_modules/sdh_ludusavi/` — passed
- `./run.sh uv run pytest` — 516 passed

## End-to-end verification (plan §Verification)

- `grep -n "os.pipe\|add_reader\|asyncio.shield" main.py` → no output
- `ThreadPoolExecutor(max_workers=4` → one hit (`Plugin.__init__`)
- `run_in_executor` → one hit (`_run_blocking`)
- `shutdown(wait=False, cancel_futures=True)` → one hit (`_unload` `finally`)
- `_run_blocking` reduced from ~96 lines to ~15
