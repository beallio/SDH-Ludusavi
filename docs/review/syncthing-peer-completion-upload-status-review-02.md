# Review 02 — syncthing-peer-completion-upload-status

**Round:** 2
**Branch:** `feat/syncthing-peer-completion-upload-status`
**Commit reviewed:** `fbd4caa` (`feat(syncthing): track connected peer completion`)
**Prior review:** `113619d` (review 01, Task 1 accepted)
**Reviewer:** orchestrator

## TASK 2: ACCEPTED

### Scope

Exactly the four files Task 2 lists: `activity.py`, `watcher.py`, `tests/test_activity.py`,
`tests/test_watcher.py`. 531 insertions, 6 deletions. Five of the six deletions are the
refactor of `_run()`'s inline baseline into `_initialize()`; the sixth is discussed under
finding 1.

### Verification performed

Quality gates re-run independently by the orchestrator against `fbd4caa`:

```text
pnpm test          331 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             906 passed (was 892), coverage above the 83% gate
worktree           clean
review notes       none deleted
```

### Plan conformance

1. **Initialization ordering.** `_initialize()` runs initial folder state → event cursor →
   peer baselines → second folder-status observation, exactly as plan item 2 requires.
   `test_post_game_initialization_captures_peer_baselines_before_second_status_poll`
   records the call order in a list and asserts it, rather than inferring ordering from
   side effects.
2. **The baseline race is genuinely closed.** Because the cursor is taken *before* the
   baseline calls, an event after the cursor is still delivered even when the baseline
   response already reflects it. And because the second status poll runs *after* the
   baselines, a mutation it detects stamps `outbound_index_observed_monotonic` later than
   every baseline `observed_monotonic`, so all peers are correctly treated as
   not-yet-fresh. The ordering is load-bearing in both directions and the implementation
   gets both right.
3. **Sanitized initialization failure.** `get_peer_completion()` converts any API
   exception into a generic `RuntimeError`, and the watcher logs only
   `type(exc).__name__` — not the message. The `raise ... from exc` chain is never logged
   with `exc_info`, so the original body cannot reach the log that way either.
   `test_post_game_completion_initialization_failure_is_sanitized` pins the exact
   `watch_initialization_failed` message and asserts both `SECRET-REMOTE-ID` and the raw
   body string are absent from `caplog.text`.
4. **Folder/device are not trusted from the response.** `/rest/db/completion` does not
   repeat the requested folder or device, so `get_peer_completion()` injects the
   backend-known values via `{**data, "folder": ..., "device": ...}` before handing off to
   the Task 1 scoped parser. Response-supplied `folder`/`device` keys are overridden
   rather than honored. Correct, and it reuses the already-reviewed validation instead of
   duplicating it.
5. **Pre-game is provably untouched.**
   `test_pre_game_initialization_never_requests_peer_completion` patches
   `get_peer_completion` with an `AssertionError` side effect *and* asserts
   `assert_not_called()`. Belt and braces; either alone would be sufficient.
6. **Captured-sequence proof.**
   `test_post_game_peer_completion_events_gate_settlement_and_ignore_unscoped_traffic`
   replays the plan's real capture: both peers at 93.56119493792454% with 8,942,011 /
   32 / 19, then DEV-A to 100%, then DEV-B to 100%. Uploading stays true across the first
   two ticks and only clears once both peers settle — with no `RemoteDownloadProgress`
   anywhere in the sequence, which is the whole point of the plan. The middle batch
   injects an unrelated-folder event and an unconfigured-device event, and the closing
   `set(watch.peer_completions) == {"DEV-A", "DEV-B"}` proves neither entered state.
   The test zeroes the hold deadline and the index/sequence recency fields between ticks;
   that is isolation of the peer-completion gate from the pre-existing time-window
   heuristics, not a relaxed assertion — the hold is separately proven in Task 1.
7. **Connectivity transitions.**
   `test_newly_connected_peer_waits_for_a_fresh_completion_and_disconnects_stop_gating`
   covers both directions: a newly connected peer with no snapshot holds `uploading` true
   after a mutation, and dropping that peer from `connected_devices` releases the gate to
   `settled`. `_connected_relevant_device_ids()` recomputes the intersection every tick,
   so the terminal `no_connected_peers` path is reached unchanged when it empties.
8. **Diagnostics.** Transition logs carry phase, connected relevant peer count, incomplete
   count, awaiting-fresh count, and aggregate needed bytes/items/deletes. Three ticks
   produce two records, proving the dedupe. Privacy is asserted positively *and*
   negatively: `"DEV-A" not in caplog.text` and `"test-folder" not in caplog.text`.
9. **Review 01 finding 1 is resolved.**
   `test_malformed_completion_event_keeps_last_good_state_and_never_leaks_payload` feeds a
   `"RAW-COMPLETION-PAYLOAD"` sentinel through the event path and asserts it never reaches
   the log while the prior good state survives. This is exactly the regression guard
   requested, and it is stronger than asked — it pins recovery as well as non-leakage.
10. **RPC surface unchanged.** The exact seven-key sample set is asserted in
    `tests/test_activity.py` and `tests/test_watcher.py`. `PeerCompletion` and the new
    `LocalActivity` timestamps remain backend-only.

### Findings

1. **Document the modified test input, and restore the lost combination (Task 3 round).**
   `test_watch_ignores_other_folder_traffic_shared_with_relevant_peer` had its mocked
   folder-status sequence changed from `6, 7` to `5, 5` — the one edit in this commit that
   touches an existing test's data. The reasoning is sound and I agree with it: the helper
   builds a `post_game` watch at `sequence=5`, so the old `6, 7` inputs advanced the
   *watched* folder's local index, which under this plan legitimately arms outbound
   evidence and makes `uploading` true. The old input no longer means what the test was
   written to mean, and holding the sequence flat preserves the test's actual intent —
   unrelated-folder traffic must not activate the watched folder. The assertions
   themselves were not touched.

   Two things are nevertheless required. First, the plan's scope-discipline rule states
   that a test change must have its rationale recorded in the session log; record it
   there, naming the test, the old and new values, and the reason above. Second, the
   original input combination — a watched-folder sequence advance while a relevant peer is
   busy on an unrelated folder — is now covered by no test at all. Add a companion test
   asserting that this combination yields `uploading=true` *because of the local mutation*
   and not because of the other folder's traffic, with the unrelated peer's other-folder
   completion still absent from `watch.peer_completions`. This closes the gap rather than
   leaving it implied.

2. **Consider deduping diagnostics on the transition label (non-blocking).**
   `_log_peer_completion_transition()` dedupes on the full six-tuple, so every change in
   aggregate needed bytes emits a line. Syncthing pumps `FolderCompletion` roughly every
   two seconds, so a 40-second sync produces on the order of twenty INFO lines rather than
   the three the plan's "start/incomplete/acknowledged" framing implies. This is not a
   per-tick log and it is not a defect — the counters are in the required field list, so
   logging their changes is a defensible reading. Raising it only because plugin logs on a
   Steam Deck are read by hand. If Task 4's device verification shows the volume is noisy,
   dedupe on the label and log the counters only on entry to `incomplete`. No change
   required this round.

## Authorization

TASK 2: ACCEPTED
AUTHORIZED TASK: 3

Proceed with Task 3 — preserve uploading through the post-game handoff — as written in the
plan, plus finding 1 above. Task 3 only. Stop for review when its atomic commit and the
round-complete marker are in place. Do not begin Task 4 or prepare its documentation while
waiting.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 2 recorded above.

STATUS: CHANGES_REQUESTED
