# Plan - Fix Issue 3: Status Refresh Robustness

## Problem Definition
`SDHLudusaviService._refresh_statuses_unlocked` assumes each game returned by the adapter is a mapping. If it receives a non-mapping item, it crashes during error logging.

## Architecture Overview
Add type validation for each game item in the refresh loop.

## Core Data Structures
N/A

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_3_refresh_robustness.py`
- Test cases:
    - Adapter returns `[{"name": "Good"}, None, {"name": "Also Good"}]`
    - Verify "Good" and "Also Good" are processed.
    - Verify an error is logged for `None` but refresh continues.

## Task List
1. Create branch `fix/issue-3-refresh-robustness`.
2. Create `tests/test_issue_3_refresh_robustness.py`.
3. Verify failure.
4. Apply fix to `py_modules/sdh_ludusavi/service.py`.
5. Verify fix.
6. Run full suite.
7. Commit.
