# Review — fail-safe-autosync-timeouts (round 12)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 7 and its test-matrix correction are accepted.  The RED suite now pins
bounded coordinator waiting, fresh post-acquisition checks, fail-fast behavior
for every automatic mutation, gate revalidation after a queued check, and one
visible failure for both check-level and action-level contention.  Proceed with
Task 8 only.

## Gate status

- Commits `3b0ece4` and `1e26af8` have valid round-complete markers, clean
  trees, and contain tests only.
- Independent focused Python verification passed 120 existing tests with nine
  strict expected failures: two coordinator cases, two automatic-check cases,
  four automatic-mutation cases, and one queued gate-loss case.
- Independent focused frontend verification passed 57 existing tests with 12
  expected failures covering start/exit checks plus restore, both conflict
  choices, and exit backup at both the decision and controller layers.
- Diff checks and the tests-only scope check passed.  Implementer full
  Python/frontend/type/build/package gates passed with the RED markers intact.

## Required changes

1. Implement Task 8's optional keyword-only coordinator wait timeout while
   preserving a fail-fast default.  Add
   `LIFECYCLE_OPERATION_WAIT_SECONDS = 30.0`, plumb the optional timeout through
   service coordination, and remove the racy injected/preflight
   `is_coordinator_running` lifecycle check.
2. Use the bounded wait only for automatic start and exit checks.  Perform each
   preview after acquiring the coordinator.  Keep automatic start restore,
   both conflict actions, exit backup, manual operations, registry refreshes,
   and unrelated calls fail-fast.
3. Preserve the Task 6 atomic rule: guarded start mutations validate and pin
   the exact lease only after their fail-fast coordinator acquisition.  Map
   contention to the existing structured `operation_running` result with zero
   adapter mutation.
4. Remove `operation_running` from silent decision handling and make it visible
   for start/exit checks and all automatic actions.  Each path must complete
   status and emit exactly one failure notification.  Update
   `docs/status_bar_game_state_flows.html` and its structural test so the
   diagram no longer describes contention as hidden.
5. Remove all Task 7 `xfail`/`it.fails` markers only after their complete bodies
   pass.  Run both planned mutation checks (restore non-blocking acquisition and
   temporarily restoring `operation_running` to silent reasons), restore the
   production code, run focused and full gates, commit Task 8 only, and do not
   begin Task 9.

STATUS: CHANGES_REQUESTED
