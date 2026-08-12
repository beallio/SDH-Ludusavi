# Review 05 — syncthing-first-peer-completion

**Round:** 5
**Branch:** `feat/syncthing-first-peer-completion`
**Commit reviewed:** `0eee3b3` (`fix(syncthing): stop debug observation on teardown`)
**Prior review:** review 04, Task 2 changes requested
**Reviewer:** orchestrator

## TASK 2: ACCEPTED

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             930 passed (was 928), coverage 89.61%
worktree           clean
review notes       none deleted
```

### Review 04 finding — resolved, verified by re-running the production sequence

I re-ran the same script that exposed the leak rather than reading the new tests:

```text
stop_watch -> {'status': 'observing', 'watch_id': 'w1'}
stop_event set after stop_watch: False   (correct - still observing)
still in registry: False                 (replacement path preserved)
stop_event set after stop_all:  True     (was False)
```

`stop_all()` now merges `self.watches` and `self._observing_watches`, stops both, and clears
both. `self.watches` keeps its original meaning so a debug-extended watch still cannot block
a later watch on the same folder.

### Cleanup paths — all three checked

A watch can leave observation four ways, and each deregisters:

- self-termination once every peer finishes — `_deregister_finished_debug_observation()`;
- the stall window or hard ceiling terminal — same call in
  `_stop_if_post_game_upload_incomplete()`;
- `no_connected_peers` — same call on that terminal branch;
- TTL expiry — routes through `_on_expired`, whose manager callback pops from **both**
  dicts. I checked this one specifically because it is the path the new tests do not cover
  and the one most likely to have been missed.

### Locking

`stop_watch()` registers inside the lock but calls `watch.stop()` outside it, and
`stop_all()` collects under the lock and stops after releasing. Since `stop()` joins the
watch thread, and the deregister callback acquires the same lock from that thread, holding
the lock across a join would deadlock. It does not. Worth stating explicitly because the
correct and incorrect versions differ only by indentation.

### Carried forward — accepted, not blocking

There is a narrow race in `stop_watch()`. `is_debug_extending_peer_completion` is evaluated,
then the callback is attached, then the watch is registered. A watch that self-terminates
between the first and second step will have already run its deregister with no callback
attached, and is then registered into `_observing_watches` with nothing to remove it.

The consequence is one dictionary entry holding an already-stopped watch, cleared at
`stop_all()`. No thread survives, no polling continues, and the window is a few
instructions wide. Closing it would mean attaching the callback at construction or
re-checking under the lock after registration — both reasonable, neither worth a sixth
round on this task. Record it in the Task 3 session log as a known accepted race so it is
discoverable rather than rediscovered.

## Authorization

TASK 2: ACCEPTED
AUTHORIZED TASK: 3

Proceed with Task 3 — document the weaker guarantee and record verification — as written in
the plan. Three additions to the session log beyond what the plan lists:

1. The review 02 plan defect: Task 2 step 1 instructed a halt-and-report on an agent with no
   reporting channel, producing two rounds in which the round-complete marker was written
   with no code. Log it as a plan defect and record that neither `status` nor `recover`
   could detect it — only diffing the branch against the marker did.
2. The review 03 finding: extended observation was unreachable because the frontend stops
   the watch on completion, and the watch-level tests could not see it.
3. The review 04 finding and the accepted race above.

Task 3 only. This is the final implementation task: mark the round complete and stop for
review. Do not author an approval note, finalize, merge, tag, or release. Approval is a
human act and the human approver has not yet reviewed this work.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 2 recorded above.

STATUS: CHANGES_REQUESTED
