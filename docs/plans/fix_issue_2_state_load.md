# Plan - Fix Issue 2: Malformed Persisted Shortcut ID

## Problem Definition
`SDHLudusaviService._load_state` can crash if `ludusaviLauncherShortcutAppId` in the state file is not a valid integer.

## Architecture Overview
Add error handling to `_load_state` when parsing the shortcut ID.

## Core Data Structures
N/A

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_2_state_load.py`
- Test cases:
    - State with `ludusaviLauncherShortcutAppId: "invalid"`
    - State with `ludusaviLauncherShortcutAppId: null`
    - Verify service starts and defaults to -1.

## Task List
1. Create branch `fix/issue-2-state-load`.
2. Create `tests/test_issue_2_state_load.py`.
3. Verify failure.
4. Apply fix to `py_modules/sdh_ludusavi/service.py`.
5. Verify fix.
6. Run full suite.
7. Commit.
