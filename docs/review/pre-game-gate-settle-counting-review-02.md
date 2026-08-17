# Review — pre-game-gate-settle-counting (round 02)

Branch: `feat/pre-game-gate-settle-counting`
Reviewed against: `docs/plans/2026-08-13_pre-game-gate-settle-counting.md`
Commit reviewed: `ea1edfd fix(syncthing): settle pre-game delete tails`

## Verdict

**Tasks 1 and 2 are accepted.** Proceed to Task 3. The branch is green again, so the
red-tree deadlock is resolved.

Both requested test additions landed: `contentPendingSample` covers the `UPDATE_NEEDED`
state and asserts the count stays `[0, 0, 0, 0, 0, 0]`, and `contentDownloadSample` now
carries `update_in_progress: true`, matching what the backend actually emits alongside
`downloading: true`.

The production change is exactly the specified shape, with a comment recording why the two
decisions are separate.

## Your mutation A was right and the plan's wording was wrong

The plan told you mutation A should re-add `settledCount = 0` to the display branches. I ran
that literally and it produced **zero** failures, because the `!sample.settled` guard means
the `update_in_progress` branch is never entered during a delete tail, so a reset placed
inside it can never fire. As specified in the plan, mutation A was not a discriminator.

Your interpretation — reset on `update_in_progress` *independently of* the display guard —
is the correct one, and I reproduced your result exactly:

```text
× releases after three settled delete-tail samples
× resets a delete-tail count when content appears mid-tail
Tests  2 failed | 61 passed (63)
```

Mutation B reproduced too, failing only the display case:

```text
× never claims downloading during a settled delete tail
Tests  1 failed | 62 passed (63)
```

I also ran a third mutation restoring the original fused `else if` chain wholesale, which
fails all three delete-tail cases (`3 failed | 60 passed`).

Together these establish something worth writing down, and it is the substance of the
change: **the `!sample.settled` guard alone is sufficient to make the counting work**, and
the de-fusing is what stops a future reset from re-breaking it. The two halves are
independently covered, which is exactly what the plan wanted the mutations to demonstrate,
even though it described one of them incorrectly.

## Gate status

Quality gates exit 0: 33 frontend files / 341 tests, typecheck, build, ruff, `ty`, and 974
Python tests at 89.84% coverage. Working tree clean, no review notes deleted, review note 01
committed.

## Required changes

Implement **Task 3 only** — the documentation and naming work. No production behaviour
changes in this task.

1. Rename `tests/test_watcher.py::test_pre_game_launch_gate_releases_during_delete_only_tail`
   so it says what it proves — that the *backend publishes* settled samples during a
   delete-only tail — and add a comment pointing at the reducer tests as the coverage for
   the gate actually releasing. Do not weaken its assertions.
2. Record the contract in `docs/specs/sdh_ludusavi_sync.md`: displayed status and settle
   count are independent decisions; a delete-only tail displays nothing and then publishes
   `COMPLETE`; settling requires three consecutive content-complete samples; post-game is
   unaffected because the reset is phase-guarded.

Add one thing to the spec beyond what the plan asked for, because this round established it:
state that `!sample.settled` on the display branch is load-bearing for the *gate*, not only
for the strip. Someone tidying that condition away would silently restore the 52-second
stall, and the reducer tests are what would catch them.

## Note on status

`CHANGES_REQUESTED` because Task 3 remains. Nothing in Tasks 1 or 2 is outstanding.

STATUS: CHANGES_REQUESTED
