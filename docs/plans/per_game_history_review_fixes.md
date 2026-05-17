# Durable Per-Game Operation History Review Fixes

## Problem Definition
The initial implementation of durable per-game history has several issues identified in the code review:
1. Backup history is lost if the post-operation status refresh fails.
2. The UI priority for displaying history entries is fixed (Failure > Backup > Restore > Skip), which can show stale failures after later successes.
3. History entries from `state.json` are not fully validated, leading to potential frontend crashes (e.g., non-string timestamps).
4. Auto-exit skip history is under-tested (one test is a `pass` no-op).

## Architecture Overview
- **Backend (Service)**: 
    - Improve `_record_history` to optionally calculate a `last_operation` field (the newest of the 4 slots).
    - Hardened `_load_state` with schema validation for history entries.
    - Decouple backup completion from status refresh in `handle_game_exit` and `force_backup`.
- **Frontend (UI)**:
    - Simplify `selectedHistory` calculation by using the backend-provided `last_operation` (or a timestamp-based sort).
    - Update rendering to handle the robustly validated data.

## Core Data Structures
```python
# GameOperationHistoryEntry (validated)
{
    "operation": "backup" | "restore" | "start" | "exit",
    "trigger": "manual_backup" | "manual_restore" | "auto_start" | "auto_exit",
    "status": "backed_up" | "restored" | "skipped" | "failed",
    "reason": str | None,
    "message": str | None,
    "timestamp": str (ISO-like or %Y-%m-%d %H:%M:%S)
}

# GameOperationHistory (expanded)
{
    "last_backup": Entry | None,
    "last_restore": Entry | None,
    "last_skip": Entry | None,
    "last_failure": Entry | None,
    "last_operation": Entry | None # New: the newest of the above 4
}
```

## Public Interfaces
- No changes to RPC signatures. `refresh_games` will return the slightly expanded `history` objects.

## Testing Strategy
1. **Regression coverage for "backup succeeds, refresh fails"**:
    - Mock `_refresh_statuses_unlocked` to raise after a successful `_ludusavi().backup()`.
    - Verify `force_backup` returns success and history is recorded.
2. **Hardened State Loading**:
    - Test `_load_state` with various malformed history dicts.
3. **Auto-exit Skip coverage**:
    - Add parameterized tests for `local_current`, `not_processed`, `no_files_found`, and `preview_failed`.
4. **UI Latest Operation Display**:
    - Update `test_frontend_static.py` or add logic checks if possible.

## Execution Phases
1. **Infrastructure & Tests (Red)**: Add failing tests in `tests/test_history.py` for refresh failures and malformed state.
2. **Core Logic (Green)**: 
    - Update `_record_history` to calculate `last_operation`.
    - Harden `_load_state`.
    - Refactor `force_backup` and `handle_game_exit`.
3. **Validation & Refactor**: Ensure all tests pass.
4. **UI Fixes**: Update `src/index.tsx` to use `last_operation`.
5. **Final Verification**: Full test suite run.
