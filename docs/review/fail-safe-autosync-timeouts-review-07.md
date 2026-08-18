# Review — fail-safe-autosync-timeouts (round 07)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 5 is not yet accepted.  The tests-only commit establishes the main guarded
operation, mutation-routing, RPC, and frontend RED contracts, but three planned
shutdown/cleanup guarantees are not yet pinned strongly enough for Task 6 to
implement safely.

## Gate status

- Commit `5083ddc` has a valid round-complete marker, a clean tree, and changes
  only the five planned test files.
- Independent focused Python verification passed 176 ordinary tests with 25
  strict expected failures.
- Independent focused frontend verification passed 42 ordinary tests with two
  expected failures.
- Existing coverage already pins invalid `restore_backup` gates, daemon RPC
  workers, event-loop responsiveness, synchronous unload fallbacks, and
  post-shutdown call failure.  The gaps below concern the new guarded-operation
  lifecycle rather than those existing guarantees.

## Required changes

1. Pin normal guarded-operation cleanup for both success and adapter exception.
   After the callback completes, a later exact `resume()` must thaw once without
   invoking the completed operation's cancellation callback; repeated/late
   completion must not clear state twice.  When a pending release exists, retain
   the existing exactly-once thaw assertion.
2. Prove neither the watchdog state lock nor the per-PID lock is held while the
   mutation callback blocks, not only while its cancellation callback blocks.
   Use the existing deterministic lock probe before requesting release.
3. Add the fail-closed shutdown case required by Task 6: when managed executor
   shutdown cannot confirm cancellation/reaping, `SDHLudusaviService.stop()`
   must return a structured failure and keep the exact gate frozen with zero
   thaw calls.  A retry/fallback must not turn that result into an unconditional
   thaw.
4. Pin `main.py::_unload` ordering explicitly.  Its RPC executor shutdown must
   occur only after backend `stop()` has returned from cancellation and guarded
   callback unwind.  Cover the failed-stop/fallback path sufficiently to prove
   it cannot bypass the retained-gate result; keep the existing responsiveness,
   daemon-worker, and post-shutdown tests intact.
5. Strengthen the renewal-loss controller case so it proves cleanup remains
   paused at `pauseHandle.release()` until `resumeGameProcess` acknowledges
   backend cancellation (for example, history synchronization has not run
   before acknowledgement and does run afterward).  Continue to require exactly
   one visible failure.
6. Capture the new RED evidence, commit tests only, run the focused and full
   gates, and recreate the marker.  Do not edit production code or begin Task 6
   in this correction round.

STATUS: CHANGES_REQUESTED
