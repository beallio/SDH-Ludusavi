# Review — pre-game-content-only-launch-gate (round 07)

Branch: `feat/pre-game-content-only-launch-gate`
Reviewed against: `docs/plans/2026-08-13_pre-game-content-only-launch-gate.md`
Commit reviewed: `7cedf9e fix(syncthing): shorten pre-game settle window`

## Verdict

**Task 5 is accepted.** Proceed to Task 6, the final task.

Every criterion is met. The constant is in place, `_tick_sample` selects it for pre-game so
both phases now pass an explicit window, the `None` fallback is retained for direct callers,
and the test was renamed with both pre-game parameters rather than one.

`test_watcher_keeps_activity_pruning_on_the_fifteen_second_window` is untouched and still
passes — I checked the diff, not just the result.

The renamed test is load-bearing, which was my specific concern about vacuous passing.
Verified by pointing pre-game back at `DEFAULT_ACTIVE_WINDOW_SECONDS`:

```text
1 failed, 77 passed in 0.64s
FAILED test_watch_uses_short_settle_window_for_both_phases[pre-game-settles-after-four-seconds]
```

## Required changes

This is the last round of implementation. It has two parts, and the plan requires both in
this round.

### Part 1 — Task 6, pre-game quiescence diagnostics

Per the plan: a transition-only pre-game diagnostic in
`py_modules/sdh_ludusavi/syncthing/watcher.py`, modelled on
`_log_peer_completion_transition`.

1. `INFO` level, emitted only when the tuple of reported values changes, never on a timer.
2. Reports `phase`, `folder_state`, `need_bytes`, `need_content_items`, `need_deletes`,
   `active_download_files`, `active_items` count, and `settled`.
3. Never logs device IDs, file names, folder paths or raw API payloads.
4. The three `caplog` tests the plan specifies, including the privacy assertion that seeds
   the watch with a folder path and device IDs and asserts those literal strings are absent
   from `caplog.text`. Follow the existing pattern in
   `test_peer_completion_diagnostics_are_transition_only_and_privacy_safe`.

This matters beyond tidiness: the 52-second stall had to be diagnosed from Syncthing's own
log because the plugin logged nothing across the whole window. These lines are what makes
the deferred device verification interpretable when it eventually runs.

### Part 2 — the end-to-end replay, which is the negative control for the whole plan

Add `tests/test_watcher.py::test_pre_game_launch_gate_releases_during_delete_only_tail`,
driving `manager.poll_watch()` through a poll sequence rather than calling `_tick_sample`
directly. Use the existing poll-sequence helpers in that file.

Replay the measured 2026-08-12 `steamdeck-legos` sequence exactly as the plan describes:
`sync-preparing`; `needBytes=0`, `needFiles=0`, `needDirectories=0`, `needSymlinks=0`,
`needDeletes=46`, `needTotalItems=46`; a trickle of `ItemStarted`/`ItemFinished` pairs with
`action="delete"` about two seconds apart; and a `LocalIndexUpdated` after each delete batch
advancing the sequence number.

Assert three distinct settled samples are published, and that the monotonic time from the
first poll to the third settled sample is **under 10 seconds**.

Then add the variant with `needFiles=1` throughout and assert the watch **never** publishes
a settled sample across the whole sequence. An implementation that merely stopped blocking
would pass the first assertion and fail this one, which is the point.

Confirm in the session log that the first variant fails against `dev` — it should never
settle there, since all five mechanisms block it — so the control is real rather than
assumed.

### Part 3 — final verification record

In the session log for this round, record:

1. Full `scripts/orchestration/run-quality-gates` output tallies verbatim.
2. The mutation for Task 6 (revert the diagnostic, show the caplog tests going red).
3. A consolidated statement of what remains **unverified**, taken from the plan's own list:
   real device behaviour, Syncthing versions other than v2.1.2, the in-flight temp-file
   hazard having no live reproduction, whether 3.0s is the right window, and the untouched
   stall window and ceilings. State it plainly; an unstated gap reads as a covered one.

## Gate status

Working tree clean, no review notes deleted, notes 01–06 committed. Suite `970 passed`
unmutated.

## Note on status

`CHANGES_REQUESTED` because Task 6 and the replay control remain. Nothing in Tasks 1–5 is
outstanding.

STATUS: CHANGES_REQUESTED
