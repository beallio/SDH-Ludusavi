# Review — fail-safe-autosync-timeouts (round 04)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 3 is accepted. Commit `2613f78` preserves the real-process stale-token test under an
honest name and adds the missing deterministic same-PID/different-generation regression.
The completed token emits no process-group signal against the newer record; the current
token emits exactly one `SIGTERM`. The round remains test-only.

The overall plan is incomplete. Continue with Task 4 only.

## Gate status

- Implementer full quality gate: passed with the executor contracts recorded as strict RED
  expected failures.
- Reviewer focus: 7 strict RED xfails, all caused by the intentionally absent executor;
  command exited zero.
- Production/vendored delta since Task 3: empty.
- `git diff --check`: passed; worktree was clean before this review note.
- Round marker: valid for `2613f782cf37853fe596863f9c7ea870abc6971f`.

## Required changes

Implement Task 4 exactly as written:

1. Add the project-owned managed executor and install it on `PyludusaviAdapter`; do not edit
   vendored pyludusavi.
2. Preserve JSON, text, stdin-JSON, environment, `--api`, spawn, execution-error, and
   contract-error behavior.
3. Implement token-scoped process-group termination, terminate-to-kill escalation, reaping,
   idempotence, and cancel-all/shutdown support. A stale token must be generation-safe even
   when the integer PID is reused.
4. Remove the module-level RED `xfail` only after all seven tests pass normally. Do not
   weaken the same-PID regression or substitute a different-PID scenario.
5. Perform the planned descendant-termination negative control, restore the implementation,
   run the focused and full gates, commit, and mark the round complete.

Keep service/watchdog lifecycle integration deferred to Task 6. Do not begin Task 5 in this
round.

STATUS: CHANGES_REQUESTED
