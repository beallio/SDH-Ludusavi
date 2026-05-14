# Plan - Fix Issue 7: Async Cancellation for Blocking Operations

## Problem Definition
`_run_blocking` in `main.py` uses a manual thread and `asyncio.sleep` loop which doesn't handle `asyncio.CancelledError` properly, leaving a daemon thread running and potentially holding locks.

## Architecture Overview
Refactor `_run_blocking` to use `loop.run_in_executor` with a default thread pool executor.

## Core Data Structures
N/A

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_7_cancellation.py`
- Test cases:
    - Run `_run_blocking` with a task that sleeps.
    - Cancel the async task.
    - Verify `asyncio.CancelledError` is raised immediately.

## Task List
1. Create branch `fix/issue-7-cancellation`.
2. Create `tests/test_issue_7_cancellation.py`.
3. Verify current behavior.
4. Apply fix to `main.py`.
5. Verify fix.
6. Run full suite.
7. Commit.
