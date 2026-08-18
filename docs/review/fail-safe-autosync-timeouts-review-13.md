# Review — fail-safe-autosync-timeouts (round 13)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 8 is not yet accepted.  The coordinator and lifecycle implementation
satisfy the bounded-wait/fail-fast contract, but the user-visible integration
does not match the newly documented result and the start-side failure cleanup
retains a pre-game watch after contention aborts auto-sync.

## Gate status

- Commit `92fc803` has a valid round-complete marker and a clean tree.
- Independent focused verification passed 133 coordinator/service/diagram
  tests, 107 lifecycle-decision/controller/status-surface tests, TypeScript
  typecheck, diff checks, vendored-package scope, and removal of all Task 7 RED
  markers.  Implementer full gates and both planned mutation checks passed.
- `gameLifecycleDecision` now completes and notifies for
  `operation_running`, but `autoSyncStatusSurface.complete()` has no branch for
  that reason.  Its generic skipped fallback publishes `unknown`, while the
  updated diagram promises `UNABLE TO SYNC`.  The existing surface suites pass
  because no integration assertion covers this reason.
- Start check/restore/conflict contention also sets
  `retainPreGameWatch: true` because the result is `skipped` rather than
  `failed`.  Cleanup therefore leaves the pre-game Syncthing watch active after
  auto-sync has stopped, allowing later watch activity to replace the failure
  status while the game is running.

## Required changes

1. Add a status-surface regression for a skipped `operation_running` result and
   make `complete()` publish the `error` status (`UNABLE TO SYNC`), matching the
   diagram.  Preserve exactly one toast: notification remains the controller's
   responsibility, not the surface's.
2. Treat `operation_running` as a failed start outcome for watch retention in
   `evaluateStartCheck`, `evaluateStartRestore`, and
   `evaluateStartConflictResolution`.  Return
   `retainPreGameWatch: false` so normal cleanup cancels the pre-game watch
   before releasing the launch gate.  Add decision assertions and at least one
   controller assertion that the active watch is stopped on this path.
3. Keep the bounded coordinator wait, fail-fast mutations, exact post-lock gate
   validation, structured reason, one completion, and one failure toast
   unchanged.  Re-run the two Task 8 mutation checks, focused surface/lifecycle
   suites, and full quality gates.  Keep this correction within Task 8 and do
   not begin Task 9.

STATUS: CHANGES_REQUESTED
