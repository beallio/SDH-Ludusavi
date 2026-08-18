# Review — fail-safe-autosync-timeouts (round 05)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 4 is not yet accepted.  The managed executor satisfies the planned public
contract and the process-tree tests, but review found one reproducible stale-PGID
signal window and one cancel-all aggregation defect.  Both are confined to the
new executor and should be corrected before the Task 5 RED round begins.

## Gate status

- Implementer round `f14c1b0` completed with a valid marker and a clean tree.
- The implementer's focused tests, descendant negative control, and full quality
  gates passed.
- Independent focused verification passed: 42 tests across constants, adapter,
  and managed-executor coverage.
- A deterministic review probe blocked `_complete_record()` after
  `communicate()` had set `returncode = 0`.  Cancelling that exact token during
  the block still called `killpg(4242, SIGTERM)`.  At that point the owned process
  is already gone, so PGID 4242 may identify an unrelated replacement process.

## Required changes

1. Add a deterministic regression test for the finish-before-deregistration
   window.  Hold final record cleanup after the fake process has completed,
   cancel its token, and prove no process-group signal is emitted.  The test must
   fail against `f14c1b0` before the implementation is changed and must also
   prove cancellation/cleanup complete without leaving the worker blocked.
2. Make process-group signalling refuse records whose owned `Popen` has already
   exited, even if the registry/completion-event cleanup is still in progress.
   Keep the state check and sent-signal bookkeeping synchronized, preserve token
   identity checks, and do not weaken termination of a genuinely live group.
3. Add a regression for cancel-all aggregation.  `cancel_all()` currently uses
   `all(...)` over the waits, so one failed wait prevents later captured records
   from receiving their bounded escalation/wait.  Visit every captured record,
   then return the combined success value.  Apply the same non-short-circuit
   rule to any shared/token-scoped wait aggregation so future multi-record
   scopes remain safe.
4. Re-run the focused Task 3/4 tests and the planned descendant-process negative
   control, then run the full quality gates.  Keep this correction limited to
   the executor and its tests; do not start Task 5 in this round.

STATUS: CHANGES_REQUESTED
