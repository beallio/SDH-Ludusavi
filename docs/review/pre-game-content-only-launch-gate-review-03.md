# Review — pre-game-content-only-launch-gate (round 03)

Branch: `feat/pre-game-content-only-launch-gate`
Reviewed against: `docs/plans/2026-08-13_pre-game-content-only-launch-gate.md`
Commit reviewed: `bbe0447 fix(syncthing): ignore deleted items in receive gate`

## Verdict

**Task 2 is accepted.** Proceed to Task 3. No changes are required to Task 2.

Every acceptance criterion from round 02 is met. `receive_needed` is now
`runtime.need_bytes > 0 or runtime.need_content_items > 0`, with `need_total_items` and
`need_deletes` both gone, and the comment records the `Counts.TotalItems()` reason.

I re-ran the mutation independently rather than reading the session log. Reverting only the
`receive_needed` expression to its delete-contaminated form gives:

```text
2 failed, 950 passed in 22.83s
FAILED test_receive_needed_ignores_deleted_items_in_folder_status
FAILED test_receive_needed_blocks_content_items_even_without_bytes
```

That matches the session log exactly, including the assertion messages. Restored, the suite
is `952 passed`.

Worth recording, because it strengthens the safety argument: the safety case
(`need_bytes=0`, `need_files=1`) fails under the old expression, not merely under a broken
new one. The previous predicate would have reported no missing content in that state
because `need_total_items` was zero. The new predicate catches it. That is the unfinished
temp-file case, and it is now genuinely covered.

## Gate status

Working tree clean, no review notes deleted, notes 01 and 02 committed as audit records.
Full suite `952 passed` unmutated; quality gates exit 0 per the session log (frontend 33
files / 335 tests, typecheck, build, ruff, `ty` all clean, coverage 89.68% against 83%).

## Observation carried forward — not a defect

`test_post_game_content_complete_peer_with_deletes_stays_settled` does **not** go red under
the Task 2 mutation, because it exercises peer completions rather than folder-status need
counters. That is expected and fine: it is positioned as a guard against a future
regression, not as a discriminating test for Task 2.

It becomes load-bearing in Task 4, which is the task that can plausibly break post-game
settling. Keep it, and when you reach Task 4 make sure your mutation there shows this test
reacting if post-game behaviour changes.

## Required changes

Implement **Task 3 only** — stop delete item events from registering as activity. Do not
start Task 4 in this round.

Acceptance criteria I will check:

1. `ItemStarted` with `action == "delete"` does not add the item to `active_items`.
2. `ItemFinished` with `action == "delete"` does not arm `last_item_finished_monotonic`,
   but **does** still `pop` the item key from `active_items`, so a mismatched pair cannot
   strand an entry.
3. A missing `action` is treated as content, not as a delete. An unknown event must fail
   towards blocking the gate. Cover the absent-`action` case explicitly — it is the one
   most likely to be got wrong, and getting it wrong releases the gate early.
4. `action == "update"` keeps today's behaviour.
5. The mutation isolates this change: revert only the action handling, show which tests go
   red with their real assertion output, restore, show green.

Record red-before and green-after output verbatim in the session log.

## Note on status

This note is `CHANGES_REQUESTED` because the plan as a whole is incomplete — three tasks
remain after Task 3 — not because anything in Task 1 or Task 2 is outstanding.

STATUS: CHANGES_REQUESTED
