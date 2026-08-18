# Review — fail-safe-autosync-timeouts (round 11)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 7 is not yet accepted.  The tests-only commit captures bounded coordinator
waiting, fresh automatic checks, restore/exit-backup lock races, delayed gate
loss, and check-level visibility, but it does not cover every mutation and
action-level visibility branch required by the plan.

## Gate status

- Commit `3b0ece4` has a valid round-complete marker, a clean tree, and changes
  only test files.
- Independent focused Python verification passed 120 existing tests with seven
  strict expected failures.  Focused frontend verification passed 57 existing
  tests with four expected failures.  Diff and tests-only scope checks passed.
- The service contention parametrization covers start restore and exit backup,
  but omits conflict `keep_local` and conflict `restore_backup` even though Task
  7 explicitly requires start conflict mutations to stay fail-fast and make no
  stale write.
- Decision/controller coverage exercises `operation_running` from start and
  exit checks only.  It does not pin visible handling for the start restore,
  either conflict action, or exit backup results.  Those action results use
  separate decision functions and can still be silently completed without the
  required single failure toast.

## Required changes

1. Extend the fail-fast service mutation test to cover all four automatic
   actions: start restore, conflict `keep_local`, conflict `restore_backup`, and
   exit backup.  For each, let a different operation acquire the coordinator
   after the check/decision, assert structured `operation_running`, and assert
   zero backup/restore adapter calls.
2. Add decision tests for action-level `operation_running` results through
   `evaluateStartRestore`, `evaluateStartConflictResolution` for both choices,
   and `evaluateExitBackup`.  Each must complete the status and request exactly
   one failure notification.
3. Add controller coverage proving the corresponding action RPC results produce
   one completion and one failure toast rather than merely testing check RPC
   results.  Parametrization is welcome, but include restore, both conflict
   resolutions, and exit backup.
4. Keep this correction tests-only, preserve the existing seven Python and four
   frontend RED cases, capture the additional expected failures, run the full
   quality gates, and do not begin Task 8.

STATUS: CHANGES_REQUESTED
