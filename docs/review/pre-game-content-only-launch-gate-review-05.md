# Review — pre-game-content-only-launch-gate (round 05)

Branch: `feat/pre-game-content-only-launch-gate`
Reviewed against: `docs/plans/2026-08-13_pre-game-content-only-launch-gate.md`
Commit reviewed: `0033aec fix(syncthing): settle content-complete delete tails`

## Verdict

Task 4's implementation is correct and the test coverage is the strongest in the plan so
far. One finding, and it is a scope/documentation issue rather than a safety defect.

I traced every term of the old `settle_update_in_progress` to its new home and confirmed
only the two intended relaxations happened — `preparing` is now tolerated, and the
local-index and sequence quiet windows are gone. `active_transfer`, `receive_needed`,
`SCANNING_STATES`, `settle_scan_progress_recent`, `settle_local_change_recent`,
`active_items`, `item_finished_recent`, `active_download_files`, `remote_progress`,
`pull_errors` and `watch_error` are all still blocking. Nothing was dropped by accident.

Mutation verified independently: removing only the `or preparing` tolerance gives

```text
2 failed, 966 passed in 22.69s
FAILED test_sync_preparing_delete_tail_settles_without_content_activity[last_local_index_monotonic]
FAILED test_sync_preparing_delete_tail_settles_without_content_activity[last_sequence_change_monotonic]
```

matching the session log.

Criterion 7 from round 04 was answered properly. The `post_game_guard` mutation shows
`test_post_game_content_complete_peer_with_deletes_stays_settled` genuinely reacting rather
than passing vacuously. The `failure_recovery` entry — first gate run at 12 failed, the
scanning-check and `active_transfer` diagnosis, then the fix — is exactly the kind of
honest reporting the plan asks for.

Criterion 8 is met by `test_sync_preparing_content_item_remains_unsettled`: `need_bytes=0`,
`need_files=1`, state `sync-preparing`, does not settle. That is the assertion that stands
between this change and restoring a partial save.

## Required changes

### 1. The post-game path was widened, and that is not recorded anywhere

`settled` is shared by both phases, so tolerating `PREPARING_STATES` changed post-game too.
I probed it directly:

```text
POST-GAME state=idle            settled=True   status=IDLE
POST-GAME state=sync-preparing  settled=True   status=PREPARING
POST-GAME state=cleaning        settled=True   status=PREPARING
POST-GAME state=syncing         settled=False  status=ACTIVE_TRANSFER
```

Before Task 4, post-game required `idle`. Now post-game can settle in `sync-preparing` and
`cleaning`. Round 04 criterion 5 said `update_in_progress` and `status` are unchanged
because they drive the post-game path, and the plan scopes the behaviour change to
pre-game. This widening is neither stated in `design_decisions` nor covered by a test.

**I am not asking you to revert it.** Making the state tolerance phase-conditional would add
a branch for no safety benefit, and the widening looks correct on its merits: post-game
`sync-preparing` with content present means nothing to receive, no downloads, no peer
pulling from us and no active items, so the only outstanding work is local pruning — which
v0.4.4 deliberately decided must not gate status.

What is missing is that this is on the record as a decision rather than a side effect. Do
both of these:

- Add a `design_decisions` entry stating plainly that `settled` is shared, that post-game
  can now settle during `sync-preparing` and `cleaning` where it previously required
  `idle`, and why that is safe and consistent with the v0.4.4 pruning decision.
- Add a test asserting post-game settles in `sync-preparing` when a content-complete peer
  has pending deletes, and does **not** settle in `syncing`. Name it so its intent is
  obvious. It should fail if someone later re-narrows the state check to `idle` only,
  which is precisely the regression that would silently undo this.

Do not change any production code for this finding unless the new test reveals a real
problem. If it does, report what it found rather than adjusting the test.

## Gate status

Working tree clean, no review notes deleted, notes 01–04 committed. Suite `968 passed`
unmutated, coverage 89.82% against 83%. Quality gates exit 0 per the session log.

## Note on status

This note is `CHANGES_REQUESTED` for the finding above and because two tasks remain after
Task 4. Nothing in Tasks 1–3 is outstanding.

STATUS: CHANGES_REQUESTED
