# Review — fail-safe-autosync-timeouts (round 09)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 6 is not yet accepted.  The guarded mutation and cancellation paths pass
their planned tests, but service shutdown loses the watchdog's retained-gate
failure when adapter shutdown itself reports success.  That lets shutdown
report success and stop Syncthing while a guarded callback is still running and
the exact game launch gate remains frozen.

## Gate status

- Commit `8db3c5e` has a valid round-complete marker and a clean tree.
- Independent focused verification passed 46 executor/adapter tests, 56
  coordinator/watchdog tests, 168 lifecycle/service/RPC tests, and 79 frontend
  tests.  Typecheck, build, targeted Ruff, and diff checks also passed.
- A deterministic review probe used an adapter whose `shutdown()` returned
  true while its guarded restore callback stayed blocked.  `service.stop()`
  retried the guarded release for about 6.1 seconds, retained the lease, but
  returned `{"status": "stopped"}` and called Syncthing `stop_all()` anyway.
  This contradicts Task 6's requirement to wait for guarded callbacks before
  thawing or stopping Syncthing and to return a failed retained-gate result when
  completion cannot be confirmed.

## Required changes

1. Add a deterministic regression for the adapter-success/guarded-callback-
   blocked branch.  Keep its timing short through injection or a test-local
   timeout.  Assert that the exact lease is retained, no thaw occurs,
   `service.stop()` returns the structured `cancellation_unconfirmed` failure
   with `retained_gate: true`, and Syncthing is not stopped.
2. Make watchdog shutdown report whether every guarded release and thaw was
   confirmed.  Have `SDHLudusaviService.stop()` propagate a failed retained-
   gate result whenever watchdog shutdown leaves any lease, even if
   `gateway.shutdown()` returned true.  Only stop Syncthing and report
   `{"status": "stopped"}` after the watchdog confirms that no gate remains.
3. Preserve the existing executor-first ordering, callbacks outside watchdog
   locks, bounded retries, and `_unload` behavior that suppresses its
   synchronous fallback for `retained_gate: true`.  Do not weaken the already
   passing adapter-shutdown-failure branch.
4. Re-run the Task 5/6 focused suites, the planned backend-guard negative
   control, and the full quality gates.  Keep this correction within Task 6 and
   do not begin Task 7.

STATUS: CHANGES_REQUESTED
