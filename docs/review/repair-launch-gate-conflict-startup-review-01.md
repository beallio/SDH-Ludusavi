# Review — repair-launch-gate-conflict-startup (round 01)

Branch: `feat/repair-launch-gate-conflict-startup`
Reviewed against: `docs/plans/2026-07-14_repair-launch-gate-conflict-startup.md`

## Verdict

Changes requested. The bootstrap-to-scope bridge covers the intended startup race and
the full repository gates pass, but three failure paths can still strand or unexpectedly
release game processes. These paths violate the plan's fail-closed cleanup and lease
ownership requirements.

## Gate status

- `./run.sh scripts/orchestration/run-quality-gates`: passed.
- Frontend: 31 files / 286 tests passed; TypeScript typecheck and Rollup build passed.
- Python: 758 tests passed; coverage 88.14%; Ruff, formatting, and `ty` passed.
- Reviewed feature tip: `7aa5cbd8da02e422f143214e884230696a91fe59`.

## Required changes

1. Make a failed bootstrap `SIGCONT` attempt recoverable. In
   `LaunchScopeAcquirer.acquire`, `continue_attempted` is set before sending `SIGCONT`,
   so an exception suppresses `_release_if_same`. The newly frozen scope is then thawed
   while the bootstrap PID may remain individually stopped forever. Attempt the
   identity-checked release on every failure after a successful `SIGSTOP` unless a
   successful `SIGCONT` is known, and include any release failure in the bounded result.
   Replace the current test that expects no retry with a RED test proving this cleanup.

2. Do not thaw an existing lease's scope when same-scope reacquisition fails. The
   acquirer currently marks `owns_frozen_scope = True` even when `scope ==
   existing_scope` and it only verified a freeze owned by the prior lease. A failed
   handoff can therefore thaw the old lease's scope while the watchdog still records it
   as frozen, allowing the game to advance. Track whether this acquisition actually
   created the freeze, preserve the prior lease on failure, and add tests for both
   `SIGCONT` failure and post-handoff verification failure during same-scope rotation.

3. Keep every frozen scope recoverable during different-scope lease rotation. If thawing
   the old scope fails and the compensating thaw of the newly acquired scope also fails,
   `ProcessWatchdog.pause` returns while retaining only the old lease; the newly frozen
   scope is then untracked. Add a fail-safe recovery/lease representation and RED tests
   showing that both scopes remain discoverable for retry/watchdog/shutdown cleanup, or
   restructure the transition so this untracked state cannot occur.

Re-run the full orchestration quality gates after the corrections and update the session
evidence with the new RED/GREEN cases.

STATUS: CHANGES_REQUESTED
