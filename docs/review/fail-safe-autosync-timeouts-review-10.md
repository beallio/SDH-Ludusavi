# Review — fail-safe-autosync-timeouts (round 10)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 6 and its retained-gate shutdown correction are accepted.  The backend
now owns the launch mutation gate, cancels managed command trees before thaw,
propagates exact gate identity across the RPC boundary, waits for frontend
release acknowledgement, and fails closed when either executor or guarded-
callback completion cannot be confirmed.  Proceed with Task 7 only.

## Gate status

- Commits `8db3c5e` and `bd66143` have valid round-complete markers and a clean
  tree.
- Independent Task 6 verification passed 46 executor/adapter tests, 56
  coordinator/watchdog tests, 168 lifecycle/service/RPC tests, 79 focused
  frontend tests, typecheck, build, targeted Ruff, and diff checks.
- Independent correction verification passed 206 watchdog/service/main tests
  and 69 focused frontend tests.  The new bounded regression proves a
  successful adapter shutdown cannot hide a blocked guarded callback: the gate
  stays frozen, service stop returns `cancellation_unconfirmed` with
  `retained_gate: true`, and Syncthing remains untouched.
- Implementer full Python/frontend/type/build/package gates and the planned
  backend-guard negative control passed after restoration.

## Required changes

1. Implement Task 7 as a RED tests-only round.  Add deterministic injected-
   timeout coverage for `OperationCoordinator.run_locked()` waiting for a lock
   that becomes available, timing out without invoking the queued callback, and
   preserving the existing fail-fast default for manual/registry callers.
2. Pin lifecycle call-site policy: automatic start/exit checks request the
   bounded wait and decide from data read after acquisition; start and exit
   mutations remain fail-fast, return `operation_running` if another operation
   wins, and perform no stale adapter mutation.
3. Add the queued-start gate regression: lose the exact lease while the
   coordinator wait is pending, then prove gate validation happens only after
   acquisition and produces `gate_lost` with zero adapter calls.
4. Add decision/controller tests showing `operation_running` is no longer
   silent for start or exit.  A timed-out check or fail-fast action must complete
   the visible error state and emit exactly one failure toast rather than hide
   it.
5. Use injected sub-second waits only, capture the expected RED failures while
   existing manual fail-fast cases remain green, commit tests only, run the full
   quality gates, and do not edit production code or begin Task 8.

STATUS: CHANGES_REQUESTED
