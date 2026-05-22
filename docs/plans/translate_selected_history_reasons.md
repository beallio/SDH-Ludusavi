# Translate Selected History Reasons to User-Friendly Messages

## Problem Definition
The "Last Operation" UI section displays raw status reasons (e.g., `Skipped (local_current)`) directly from `selectedHistory.reason` instead of rendering human-readable messages (e.g., `Skipped (local save is already current)`). Additionally, failures should show their specific error message from `selectedHistory.message`.

## Architecture Overview
We will update `getLastOperationText` inside `src/index.tsx` to:
1. Accept an optional/nullable `message` argument as the third parameter.
2. Translate raw `skipped` reason keys to user-friendly messages matching those in `summarizeOperationResult`.
3. Render `failed` operations using `message` or `reason` (fallback to "Failed" if both are absent).
4. Update the calls in `src/index.tsx` to pass `selectedHistory.message` to `getLastOperationText`.

## Core Data Structures
None changed. `GameOperationHistoryEntry` already defines `reason: string | null` and `message: string | null`.

## Public Interfaces
None changed.

## Dependency Requirements
None.

## Testing Strategy
We will add a static frontend test to `tests/test_frontend_static.py` checking that:
1. `getLastOperationText` signature includes `message` parameter.
2. The translation switch block mapping `local_current` and other keys exists in `getLastOperationText`.
3. Call sites in the TSX file pass three arguments `(selectedHistory.status, selectedHistory.reason, selectedHistory.message)`.

We will verify this test fails (RED phase) before writing the implementation in `src/index.tsx`.
After implementation, we will verify all checks and tests pass (GREEN phase).
