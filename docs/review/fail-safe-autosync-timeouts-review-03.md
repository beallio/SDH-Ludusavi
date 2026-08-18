# Review — fail-safe-autosync-timeouts (round 03)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 3 is test-only and five of its six public contracts are well specified: pyludusavi
compatibility, environment/spawn behavior, timeout process-tree termination, token-isolated
concurrent cancellation, and adapter installation. The focused suite reports six strict RED
xfails, all currently caused by the intentionally absent `sdh_ludusavi.ludusavi_executor`
module, and no production or vendored files changed.

One safety assertion is not yet proven and must be corrected before Task 4 begins.

## Gate status

- Implementer full gate: 977 ordinary backend passes and 6 strict RED xfails; frontend
  build/typecheck, Ruff, `ty`, and review-note integrity passed.
- Reviewer focus with the corrected plan command: 6 strict RED xfails, all carrying the
  expected missing-executor reason; command exited zero.
- Production/vendored delta from `aca0982`: empty.
- Worktree: clean at review time.
- Round marker: valid for `b084f99482b80ee130398234bc52208ba86fbf16`.

## Required changes

1. `test_completed_token_cannot_cancel_a_later_operation_even_if_a_pid_is_reused` does not
   reuse a PID. It runs a normal later helper and therefore receives a different OS PID; the
   test proves token isolation/idempotence but not the stale-token/PID-reuse edge named by
   the plan and test.
2. Keep that real-process coverage but give it an honest name. Add a separate deterministic
   fake-process regression in which two sequential managed operation records expose the same
   integer PID under different tokens/generations. After the second record is active,
   cancelling the completed first token must issue no terminate/kill action against the
   second fake process group; cancelling the second token must target it exactly once.
3. Keep the new regression strict RED against the missing implementation, run the focused
   suite and full quality gate, commit tests only, and mark the round complete.

Do not begin Task 4 or add the executor module in this round.

STATUS: CHANGES_REQUESTED
