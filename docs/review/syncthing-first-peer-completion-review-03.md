# Review 03 — syncthing-first-peer-completion

**Round:** 3
**Branch:** `feat/syncthing-first-peer-completion`
**Commit reviewed:** `b0f64b1` (`feat(syncthing): keep observing peers under debug logging`)
**Prior review:** `f569951` (review 02, Task 2 instruction amended)
**Reviewer:** orchestrator

## TASK 2: CHANGES REQUESTED

Real work this round, first attempt, and the backend logic is correct in isolation. But the
extended observation it adds is unreachable in the running plugin, so as written the feature
can never do anything on a real device.

### Verification performed

Gates re-run independently by the orchestrator against `b0f64b1`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             925 passed (was 921), coverage 89.56%
worktree           clean
review notes       none deleted
```

### What is correct

`_stop_after_post_game_peer_completion()` latches on first completion, evaluates
`logger.isEnabledFor(logging.DEBUG)` **at that moment** rather than caching it at
construction as the plan required, and branches cleanly: debug off sets `stop_event`
immediately, debug on falls through and keeps observing until
`incomplete_peers == 0 and awaiting_fresh_completion == 0`. It runs after `_tick_sample()`,
so the completed sample is always published before any stop decision.

Both gate directions are pinned, which is what the plan asked for:

```text
gate forced False -> FAILED …debug_extended_observation_stops_at_existing_stall_boundary
                     FAILED …debug_extended_observation_stops_at_existing_hard_ceiling
gate forced True  -> FAILED …first_peer_completion_stops_watch_when_debug_is_disabled
                     FAILED …debug_completion_keeps_observing_until_all_peers_finish
```

A gate tested in only one direction passes when it is stuck; these fail in both.

### Finding

1. **Extended observation is unreachable in production — the frontend stops the watch on
   completion.** `syncthingMonitorMachine.ts:250`:

   ```ts
   if (nextState.completionObserved) effects = { ...effects, stopWatch: true };
   ```

   and the RPC it drives:

   ```python
   def stop_watch(self, watch_id: str) -> dict[str, Any]:
       with self.lock:
           watch = self.watches.pop(watch_id, None)
       if watch:
           watch.stop()          # sets stop_event and joins the thread
   ```

   The moment the frontend publishes `SYNCTHING COMPLETE` it calls `stopWatch`, which pops
   the watch and sets `stop_event` regardless of what the backend decided. In debug mode the
   backend deliberately does *not* stop itself — and is then stopped from outside within
   roughly one 500 ms poll cycle. The extended log tail the feature exists to produce would
   never appear on device.

   The unit tests pass because they drive `SyncthingWatch` directly and never exercise the
   RPC path. This is the same shape as the event-cursor defect: green in isolation, inert in
   the assembled system.

   Fix in `SyncthingWatchManager.stop_watch()`: when the target watch is in debug extended
   observation, do not stop it — leave it running to self-terminate on its own condition,
   the stall window, or the hard ceiling, and return a status that reflects that it was left
   observing. Expose the mode through a narrow read-only property on `SyncthingWatch` rather
   than reaching into the private attribute.

   Two constraints. `stop_all()` must remain unconditional — plugin unload and shutdown
   have to force-stop everything, and a watch that survives teardown is a leak, not a
   diagnostic. And a watch left observing must still be removed from `self.watches` or
   otherwise prevented from blocking a subsequent watch for the same folder; check the
   replacement path and keep its existing behaviour intact.

   Add tests at the manager level, not just the watch level: `stop_watch` on a
   debug-extended watch leaves it running; `stop_watch` on a normal completed watch stops it
   as today; `stop_all` stops both. The first of those fails against the current code, which
   is the point — verify that before trusting it.

### Note

Task 2's file scope in the plan lists only `watcher.py` and `tests/test_watcher.py`.
`SyncthingWatchManager` lives in `watcher.py`, so this fix stays inside that scope. Do not
touch any frontend file: the frontend should remain unaware of the debug toggle, and the
published status must stay identical in both modes.

## Authorization

TASK 2: CHANGES REQUESTED

Fix finding 1 only. Do not revisit Task 1, do not begin Task 3, and do not author an
approval note, finalize, merge, tag, or release.

STATUS: CHANGES_REQUESTED
