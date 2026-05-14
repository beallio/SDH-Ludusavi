# Plan - Fix Issue 6: Scoped Environment for Ludusavi Subprocess

## Problem Definition
`ludusavi.py` clears `LD_LIBRARY_PATH` globally at import time. This should be scoped to the Ludusavi subprocess.

## Architecture Overview
Remove the global `os.environ` mutation. Create a helper `_ludusavi_env()` and pass it to the `Ludusavi` constructor (which passes it to the executor).

## Core Data Structures
N/A

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_6_env_scoping.py`
- Test cases:
    - Verify `LD_LIBRARY_PATH` is preserved in `os.environ` after importing the module.
    - Verify that the `Ludusavi` instance is initialized with a custom environment if needed, or that the execution paths use the scoped environment.

## Task List
1. Create branch `fix/issue-6-env-scoping`.
2. Create `tests/test_issue_6_env_scoping.py`.
3. Verify failure (global mutation).
4. Apply fix to `py_modules/sdh_ludusavi/ludusavi.py`.
5. Verify fix.
6. Run full suite.
7. Commit.
