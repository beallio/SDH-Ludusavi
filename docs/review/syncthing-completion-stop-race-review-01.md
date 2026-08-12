# Review 01 — syncthing-completion-stop-race

**Round:** 1
**Branch:** `feat/syncthing-completion-stop-race`
**Commit reviewed:** `b349da3` (`fix(syncthing): let the frontend own the completion stop`)
**Plan commit:** `a5c146e`
**Reviewer:** orchestrator

## TASK 1: ACCEPTED

### Work verified by diff, not by marker

Checked first, because the predecessor branch produced two rounds where the round-complete
marker was written with no code and no engine check could tell:

```text
git diff dev..HEAD --stat
  docs/plans/2026-08-11_syncthing-completion-stop-race.md   605 +++++
  py_modules/sdh_ludusavi/syncthing/watcher.py              22 +-
  tests/test_watcher.py                                     77 +-
```

Real work, first attempt, exactly the two files Task 1 scopes plus the plan.

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             931 passed (was 930), coverage 89.63%
worktree           clean
review notes       none deleted
```

### The fix

`_stop_after_post_game_peer_completion()` is renamed `_latch_post_game_peer_completion()`,
and the rename is honest — the method no longer stops anything on first confirmation:

```python
if not self._outbound_first_peer_completion_reached:
    self._outbound_first_peer_completion_reached = True
    self._debug_outbound_completion_observation = logger.isEnabledFor(logging.DEBUG)
    return
```

The debug flag is still latched, because `stop_watch()` reads it, but `stop_event` is
untouched. The backend now keeps publishing settled samples with advancing timestamps, so
the frontend can accumulate its three-distinct-timestamp quorum, publish
`SYNCTHING COMPLETE`, and stop the watch — the ownership that existed before the
regression.

Release is explicit rather than inferred. `begin_released_observation()` sets both the
callback and `_released_for_observation`, self-termination is guarded on that flag, and
`_deregister_finished_debug_observation()` checks it too. The plan asked for an explicit
flag specifically because inferring release from the callback's presence is the kind of
implicit signal that made this class of bug hard to see; the implementation does not take
that shortcut.

The five remaining `stop_event.set()` sites are the legitimate ones: external `stop()`, TTL
expiry, `no_connected_peers`, the guarded extended-observation completion, and the
stall/ceiling terminal. None of them fire on first-peer confirmation.

### Mutation tests — both plan gates proven

**Restoring the stop on completion** (plan verification step 2):

```text
FAILED test_post_game_first_peer_confirmation_keeps_publishing_settled_samples_in_both_modes[normal]
FAILED test_post_game_first_peer_confirmation_keeps_publishing_settled_samples_in_both_modes[debug]
FAILED test_unreleased_debug_watch_keeps_publishing_after_all_peers_finish
… 11 failed, 58 passed
```

The plan required the advancing-timestamp test to fail in **both** parametrised modes, and
both fail. That mattered: normal mode is what almost every user runs, and on the captured
device failure it was the worse of the two — the stop fired on the first qualifying tick, so
the frontend could receive at most one settled sample.

**Removing the released guard** (plan verification step 3):

```text
FAILED test_unreleased_debug_watch_keeps_publishing_after_all_peers_finish
1 failed, 68 passed
```

Exactly one failure, and it is the test written for that guard. The guard is the entire
difference between extended observation and a second instance of this bug, and it is
genuinely pinned rather than incidentally covered.

Both mutations reverted; 69 passed in the focused file, tree clean.

### Scope

The stall detector, both ceilings, the TTL path, `stop_all()`, the frontend, and the RPC
sample key set are all untouched, as the plan required. `_on_expired` still pops from both
dicts.

## Authorization

TASK 1: ACCEPTED
AUTHORIZED TASK: 2

Proceed with Task 2 — add the poll-sequence regression harness — as written in the plan.
Task 2 changes no production code. Its point is that the harness must drive polls **through
`SyncthingWatchManager.poll_watch()`**, not read `watch.latest_sample`; reading the
attribute directly is the shortcut that hid this regression behind 930 passing tests. Stop
for review when its atomic commit and the round-complete marker are in place.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 1 recorded above.

STATUS: CHANGES_REQUESTED
