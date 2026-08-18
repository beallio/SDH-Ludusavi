# Review — fail-safe-autosync-timeouts (round 06)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 4 and its review correction are accepted.  The managed executor now
preserves the pyludusavi command contract, terminates managed process groups,
does not signal a completed record during final deregistration, and waits every
captured record before reporting cancellation success.  Proceed with Task 5
only.

## Gate status

- Correction commits `ef1c72e` and `58358e1` have a valid round-complete marker
  and a clean working tree.
- The requested finish-before-deregistration, cancel-all aggregation, and
  token-scoped aggregation regressions are present and passing.
- The post-commit suite exposed a test-only `/proc` disappearance race; the
  helper now treats that normal process-exit window as stopped and has a
  deterministic regression.
- Independent focused verification passed all 46 constants, adapter, and
  managed-executor tests.
- Implementer full quality gates and the descendant-process negative control
  passed after restoration of the production signal path.

## Required changes

1. Implement Task 5 exactly as a RED tests-only round.  Add deterministic
   thread/event coverage for watchdog lease identity/generation checks, pin and
   deferred-thaw ordering, lock release, failed-operation recording, and no
   late success after cancellation.
2. Pin fail-closed mutation behavior for start restore and both conflict
   decisions: no exact gate means zero adapter mutations; the exact valid gate
   permits one guarded mutation.
3. Pin the `pid` plus `lease_id` contract across backend entry points, service,
   compatibility signatures, TypeScript RPC declarations, controller types,
   and lifecycle calls.
4. Add the planned renewal-loss integration case and stop/unload cancellation
   ordering cases, preserving event-loop responsiveness, daemon workers,
   synchronous fallback, and post-shutdown failure behavior.
5. Capture the expected RED failures against current production code, commit
   tests only, run the plan's gates, and mark the round complete.  Do not edit
   watchdog, lifecycle, RPC, service, or frontend production code and do not
   begin Task 6 in this round.

STATUS: CHANGES_REQUESTED
