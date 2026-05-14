# Plan - Fix Issue 8: UI Feedback for Refresh Dependency Errors

## Problem Definition
The frontend ignores `dependency_error` from the backend during game refresh, which can hide critical setup issues.

## Architecture Overview
Update `applyRefreshResult` in `src/index.tsx` to handle `dependency_error` by showing an error toast and returning a success boolean. Use this boolean to decide whether to show a success toast.

## Core Data Structures
N/A (TypeScript types already include `dependency_error`)

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_8_ui_error.py`
- Test cases:
    - Verify `src/index.tsx` contains logic to check `result.dependency_error`.
    - Verify `toaster.toast` is called with error details when `dependency_error` is present.
    - Verify success toast is only shown when refresh actually succeeds.

## Task List
1. Create branch `fix/issue-8-ui-error`.
2. Create `tests/test_issue_8_ui_error.py`.
3. Verify failure (missing logic).
4. Apply fix to `src/index.tsx`.
5. Verify fix.
6. Run full suite.
7. Commit.
