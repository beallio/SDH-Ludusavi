# Review 02 — syncthing-completion-stop-race

**Round:** 2
**Branch:** `feat/syncthing-completion-stop-race`
**Commit reviewed:** `3ee4389` (`test(syncthing): cover the manager poll sequence after completion`)
**Prior review:** review 01, Task 1 accepted
**Reviewer:** orchestrator

## TASK 2: ACCEPTED

### Scope

One file, `tests/test_watcher.py`, 56 insertions, zero deletions. No production code was
touched, which Task 2 required.

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             933 passed (was 931), coverage 89.63%
worktree           clean
review notes       none deleted
```

### The harness goes through the manager

This was the whole point of the task, so I checked the helper rather than the test names:

```python
manager.watches[watch.watch_id] = watch
for now in range(2, 2 + poll_count):
    if not watch.stop_event.is_set():
        _tick_first_peer_completion(watch, float(now))
    response = manager.poll_watch(watch.watch_id)
    ...
    timestamps.append(sample["timestamp_unix"])
    settled_flags.append(sample["settled"])
```

Samples are observed through `SyncthingWatchManager.poll_watch()`, not by reading
`watch.latest_sample`. It also stops ticking once `stop_event` is set, which is what makes
it able to model a dead watcher still answering polls — the exact production condition.

### The control — the harness catches the defect that 930 tests missed

Plan verification step 4 requires the harness to demonstrably fail against the original
defect. I reapplied the stop on completion and ran the harness alone:

```text
>       assert settled_timestamps == [4.0, 5.0, 6.0]
E       assert [4.0, 4.0, 4.0] == [4.0, 5.0, 6.0]
FAILED test_manager_poll_sequence_keeps_three_distinct_settled_samples_after_first_peer_completion
1 failed, 1 passed
```

`[4.0, 4.0, 4.0]` is the production failure reproduced in a unit test: the watcher stops,
`latest_sample` freezes, and every subsequent poll returns the same `timestamp_unix`. The
frontend's duplicate-timestamp check discards each one, `settledCount` never reaches three,
and `SYNCTHING COMPLETE` never publishes. That is precisely what happened on device at
22:34 and what nothing in the suite could see before this commit.

The second harness test still passes under the mutation, correctly — it pins the
frozen-sample contract, which the mutation does not change.

### Test quality

`test_manager_poll_sequence_exposes_frozen_sample_for_stopped_registered_watch` deserves
specific credit. It asserts `timestamps == [4.0, 4.0, 4.0, 4.0]` for a stopped-but-registered
watch and says in a comment that it exists to make a future change to that contract explicit.
It documents the mechanism that caused the outage rather than fixing it, which is right:
`poll_watch()` returning the last sample verbatim is reasonable behaviour, and the defect
was the backend stopping early, not the manager answering honestly. Pinning it means the
next person who changes it has to do so deliberately.

The distinctness assertion is written two ways — the exact sequence `[4.0, 5.0, 6.0]` and
`len(set(...)) >= 3`. The exact form is what fails informatively under the mutation.

## Authorization

TASK 2: ACCEPTED
AUTHORIZED TASK: 3

Proceed with Task 3 — document the ownership rule and record verification — as written in
the plan. Note step 2 in particular: no `README.md` change is expected, because the
user-facing meaning of `SYNCTHING COMPLETE` is unchanged by this fix. Confirm that is still
true and record it in the session log rather than editing the file to no purpose.

Task 3 only. This is the final implementation task: mark the round complete and stop for
review. Do not author an approval note, finalize, merge, tag, or release. Approval is a
human act and the human approver has not yet reviewed this work.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 2 recorded above.

STATUS: CHANGES_REQUESTED
