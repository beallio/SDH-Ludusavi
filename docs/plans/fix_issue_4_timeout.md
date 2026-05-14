# Plan - Fix Issue 4: Finite Timeouts for Ludusavi Operations

## Problem Definition
`pyludusavi` operations default to `timeout=None`, which can block the plugin indefinitely.

## Architecture Overview
Introduce `DEFAULT_OPERATION_TIMEOUT_SECONDS = 60` and apply it as the default for `backup` and `restore` in `pyludusavi.main.Ludusavi`.

## Core Data Structures
N/A

## Public Interfaces
- `Ludusavi.backup(..., timeout=60)`
- `Ludusavi.restore(..., timeout=60)`

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_4_timeout.py`
- Test cases:
    - Call `backup()` without timeout argument, verify it uses 60s.
    - Call `restore()` without timeout argument, verify it uses 60s.
    - Call with explicit `timeout=None`, verify it works.

## Task List
1. Create branch `fix/issue-4-timeout`.
2. Create `tests/test_issue_4_timeout.py`.
3. Verify failure (current default is None).
4. Apply fix to `py_modules/pyludusavi/main.py`.
5. Verify fix.
6. Run full suite.
7. Commit.
