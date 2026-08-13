# Review — pre-game-content-only-launch-gate (round 04)

Branch: `feat/pre-game-content-only-launch-gate`
Reviewed against: `docs/plans/2026-08-13_pre-game-content-only-launch-gate.md`
Commit reviewed: `dbd1a9b fix(syncthing): ignore delete item activity`

## Verdict

**Task 3 is accepted.** Proceed to Task 4. No changes are required to Task 3.

The implementation is right on every point, including the subtle one: the `pop` in
`ItemFinished` sits outside the `action` check, so a delete still prunes a stranded entry
while declining to arm the timestamp. `data.get("action") != "delete"` treats a missing
`action` as content, which is the fail-towards-blocking direction the review asked for.

Mutation verified independently — reverting both `action` checks gives:

```text
2 failed, 954 passed in 22.63s
FAILED test_item_events_distinguish_deletes_from_content[delete]
FAILED test_delete_item_finished_prunes_mismatched_active_item_without_rearming
```

The `update` and `missing-action` parameters stay green under that mutation, which is
exactly right: they are guards proving content handling is unchanged, not discriminators
for the new branch.

## Gate status

Working tree clean, no review notes deleted, notes 01–03 committed. Suite `956 passed`
unmutated (954 + the 2 that the mutation turned red).

## Required changes

Implement **Task 4 only** — the content-only pre-game settle predicate. Do not start
Task 5 in this round.

This is the task that actually releases the launch gate, and it is the one with real
correctness risk. A mistake here restores a half-downloaded save. Work slowly.

Acceptance criteria:

1. `settled` no longer requires `folder_state == "idle"` outright. A state in
   `PREPARING_STATES` is acceptable **only when content is present**, where content present
   means all of: `not receive_needed`, `local_activity.active_download_files == 0`,
   `not remote_progress`, and no active content items.
2. `syncing` still blocks. Deletions never reach that state, so a `syncing` folder is
   moving content. Test this explicitly.
3. `SCANNING_STATES`, `ERROR_STATES`, `PAUSED_STATES`, non-zero `runtime.pull_errors` and a
   non-empty `runtime.watch_error` all still block, exactly as today.
4. `settle_local_index_recent` and `settle_sequence_change_recent` are dropped from the
   settle predicate, because `LocalIndexUpdated` carries no action field and cannot be
   filtered. `settle_local_change_recent` and `settle_scan_progress_recent` stay.
5. `update_in_progress` and the `status` string are unchanged. They drive diagnostics and
   the post-game path.
6. All five red tests from the plan exist, including the two negative controls:
   `sync-preparing` with `need_files=1` must **not** settle, and `pull_errors=1` with
   `sync-preparing` and zero content need must **not** settle.

Two additional things I want to see, beyond the plan's list:

7. **Post-game must be proven unaffected.** Your mutation for this task must show
   `test_post_game_content_complete_peer_with_deletes_stays_settled` reacting if post-game
   settling changes. If that test stays green no matter what you do to the settle predicate,
   say so plainly in the session log rather than implying it covered post-game.
8. **A test that the gate still blocks on a partially-downloaded snapshot.** Construct the
   state where `need_bytes == 0` but `need_files == 1` *and* the folder state is
   `sync-preparing` — the combination of the temp-file hazard and the new state tolerance.
   It must not settle. This is the single most important assertion in the plan.

Record red-before and green-after output verbatim, and state explicitly in the session log
which of the five gating mechanisms from the plan's Context each new test exercises.

## Note on status

This note is `CHANGES_REQUESTED` because the plan as a whole is incomplete — two tasks
remain after Task 4 — not because anything in Tasks 1–3 is outstanding.

STATUS: CHANGES_REQUESTED
