# Review — pre-game-content-only-launch-gate (round 06)

Branch: `feat/pre-game-content-only-launch-gate`
Reviewed against: `docs/plans/2026-08-13_pre-game-content-only-launch-gate.md`
Commit reviewed: `a04513a test(syncthing): cover post-game delete-tail settlement`

## Verdict

**Task 4 is accepted.** Proceed to Task 5. Both parts of the round-05 finding are resolved.

The new `design_decisions` entry states the widening plainly — that `settled` is shared,
that post-game can now settle during `sync-preparing` and `cleaning` where it previously
required `idle`, and why that is consistent with the v0.4.4 pruning decision. That is now a
recorded decision rather than a side effect.

`test_post_game_delete_tail_settles_during_pruning_but_not_syncing` asserts both directions
and is load-bearing. Verified independently — re-narrowing the state check to `idle` only:

```text
3 failed, 80 passed in 0.09s
FAILED test_post_game_delete_tail_settles_during_pruning_but_not_syncing
FAILED test_sync_preparing_delete_tail_settles_without_content_activity[last_local_index_monotonic]
FAILED test_sync_preparing_delete_tail_settles_without_content_activity[last_sequence_change_monotonic]
```

The regression that would silently undo this now has a test standing in front of it.

## Required changes

Implement **Task 5 only** — give pre-game its own settle window. Do not start Task 6.

Acceptance criteria:

1. `PRE_GAME_SETTLE_QUIET_WINDOW_SECONDS = 3.0` added to
   `py_modules/sdh_ludusavi/syncthing/_types.py` alongside the post-game constant.
2. `_tick_sample` in `py_modules/sdh_ludusavi/syncthing/watcher.py` selects it for the
   pre-game phase instead of passing `None`. Both phases now pass an explicit window.
3. The `None` handling stays in `compute_activity_status` for direct callers and tests.
4. **Pruning is untouched.** `prune_remote_progress` and `prune_local_activity` stay on
   `DEFAULT_ACTIVE_WINDOW_SECONDS`, and
   `tests/test_watcher.py::test_watcher_keeps_activity_pruning_on_the_fifteen_second_window`
   must still pass **unmodified**. If you find yourself editing that test, stop — something
   is wrong with the change, not with the test.
5. `tests/test_watcher.py::test_watch_uses_short_settle_window_only_for_post_game` is
   renamed to reflect that both phases use a short window, and its
   `pre-game-keeps-fifteen-second-launch-gate` parameter now asserts pre-game settles after
   4 seconds of quiet and does not settle after 2. Record the rename and the changed
   expectation in the session log with the reason, as the plan requires.
6. Mutation isolates this change: revert only the window selection in `_tick_sample`, show
   which tests go red with their real assertion output, restore, show green.

One thing to be careful about, since it is the sort of change that can pass vacuously: make
sure the renamed test would fail if `_tick_sample` passed `DEFAULT_ACTIVE_WINDOW_SECONDS`
for pre-game rather than the new constant. A test that only exercises the post-game
parameter proves nothing about Task 5.

## Gate status

Working tree clean, no review notes deleted, notes 01–05 committed. Suite `969 passed`
unmutated.

## Note on status

`CHANGES_REQUESTED` because two tasks remain. Nothing in Tasks 1–4 is outstanding.

STATUS: CHANGES_REQUESTED
