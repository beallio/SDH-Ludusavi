# Review — fail-safe-autosync-timeouts (round 01)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 1 is accepted with no blocking defect. Commit `acf76d8` is test-only and stays inside
the plan's first RED boundary. It pins the requested 180-second operation and preview
ceilings, the `max(operation, preview) + 60` watchdog derivation, the 210-second status
ceiling, every adapter route named by the plan (including the previously missing snapshot
restore), and late-failure visibility.

The overall plan is not complete, so this is not an approval. Continue with Task 2 only.

## Gate status

- `scripts/orchestration/run-quality-gates`: passed.
- Frontend: 33 files and 341 tests passed; typecheck and build passed.
- Backend: 967 tests passed, 10 strict expected failures recorded for the RED policy, and
  coverage remained above the required threshold at 89.84%.
- Review-note deletion check: passed.
- Round marker: valid for `acf76d82ebff430d8d9dbd22b7313ef966f12485`.
- Worktree: clean at review time.

## Required changes

Implement Task 2 exactly as written in the plan:

1. Set real operations and previews/status checks to `180.0` seconds.
2. Derive the watchdog boundary as
   `max(LUDUSAVI_OPERATION_TIMEOUT_SECONDS, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) + 60.0`.
3. Set the running-status ceiling to `210_000` milliseconds.
4. Remove the Task 1 `xfail`/`it.fails` wrappers so every policy test becomes an ordinary
   passing test; do not weaken or delete the literal assertions.
5. Update only the linked timeout comments and documentation named by Task 2. Preserve the
   independent Syncthing 300/900-second monitoring limits.
6. Perform and record the required negative-control timeout mutation, run the full quality
   gates, commit the GREEN change, and mark the round complete.

Do not begin Task 3 in this round.

STATUS: CHANGES_REQUESTED
