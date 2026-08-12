# Review 01 — syncthing-debug-observation-exit

**Round:** 1
**Branch:** `feat/syncthing-debug-observation-exit`
**Commit reviewed:** `a46c7a9` (`fix(syncthing): observe until pending deletes drain`)
**Plan commit:** `565be83`
**Reviewer:** orchestrator

## TASK 1: ACCEPTED

### Work verified by diff first

```text
py_modules/sdh_ludusavi/syncthing/watcher.py   13 +-
tests/test_watcher.py                          35 +-
```

Real work, first attempt, exactly the two files Task 1 scopes plus the plan.

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             946 passed, coverage 89.69% (was 89.68%)
worktree           clean
review notes       none deleted
```

### The implementation

```python
# Content completion caused the frontend to release this watch, so incomplete_peers is
# zero by construction here. Pending deletes must keep debug observation alive.
if (
    diagnostics.incomplete_peers == 0
    and diagnostics.awaiting_fresh_completion == 0
    and diagnostics.peers_pending_deletes == 0
):
    self.stop_event.set()
    self._deregister_finished_debug_observation()
    return

if time.monotonic() - self.watch_started_monotonic >= POST_GAME_WATCH_HARD_CEILING_SECONDS:
    self.stop_event.set()
    self._deregister_finished_debug_observation()
```

The comment records the reasoning rather than the change, and it is the reasoning that
matters here: `incomplete_peers` is zero by construction after release, so a future reader
tidying "redundant" terms out of that condition would silently restore the original defect.

Both stop paths deregister from `_observing_watches`, so the manager registry cannot retain
a stopped watch. The ceiling reuses `POST_GAME_WATCH_HARD_CEILING_SECONDS` and
`self.watch_started_monotonic`; no new constant was introduced and
`_stop_if_post_game_upload_incomplete()` was not restructured.

### Mutation tests — all three guarantees proven independently

**Dropping the deletes term:**

```text
FAILED test_released_debug_observation_continues_until_pending_deletes_drain
FAILED test_released_debug_observation_stops_at_hard_ceiling_before_thread_ttl
2 failed, 75 passed
```

**Dropping the ceiling bound:**

```text
FAILED test_released_debug_observation_stops_at_hard_ceiling_before_thread_ttl
1 failed, 76 passed
```

**Dropping the released guard:**

```text
FAILED test_unreleased_debug_watch_keeps_publishing_after_all_peers_finish
1 failed, 76 passed
```

Three mutations, three distinct failure sets. The ceiling and the deletes term are
separately anchored, and the release guard carried over from the predecessor branch still
fails on its own test — a change to the exit condition cannot weaken the protection around
the frontend's completion quorum without something going red.

Both mutations reverted after each run; 77 passed in the focused file, tree clean.

### Test naming

`test_released_debug_observation_stops_at_hard_ceiling_before_thread_ttl` names the
distinction that matters. The pre-fix behaviour was not "unbounded" — it was bounded at the
thread TTL sixty seconds later, through a warning path that publishes a `watch_ttl_expired`
sample. Asserting the ceiling terminal specifically, rather than merely that the watch
stopped, is what makes that test meaningful.

## Authorization

TASK 1: ACCEPTED
AUTHORIZED TASK: 2

Proceed with Task 2 — document the exit contract and record verification — as written in the
plan. Two things to get right: the spec currently says observation continues "until all
peers finish or an existing terminal boundary is reached", which is exactly the ambiguity
that permitted this defect, so replace it with the precise condition and record that
`incomplete_peers` cannot serve as the exit test because it is zero by construction after
release. And record that this defect also explains the 2026-08-11 23:25 result previously
logged as unexplained, while noting the debug-gate fix shipped for that was a real but
separate defect.

Task 2 only. This is the final implementation task: mark the round complete and stop for
review. Do not author an approval note, finalize, merge, tag, or release.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 1 recorded above.

STATUS: CHANGES_REQUESTED
