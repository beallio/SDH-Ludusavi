# Review 04 — syncthing-first-peer-completion

**Round:** 4
**Branch:** `feat/syncthing-first-peer-completion`
**Commit reviewed:** `133a2e0` (`fix(syncthing): preserve debug peer observation`)
**Prior review:** review 03, Task 2 changes requested
**Reviewer:** orchestrator

## TASK 2: CHANGES REQUESTED

Review 03's reachability finding is resolved — an extended watch now survives the frontend's
`stopWatch`. But the second constraint in that finding was not met: the watch also survives
`stop_all()`, so it now outlives plugin teardown.

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             928 passed (was 925), coverage above gate
worktree           clean
review notes       none deleted
```

### What is correct

`is_debug_extending_peer_completion` is a narrow read-only property rather than external
access to a private attribute, and it correctly folds in `not self.stop_event.is_set()` so a
watch that has already stopped is never reported as extending. `stop_watch()` still pops the
watch from `self.watches`, so a debug-extended watch cannot block a later watch on the same
folder — the replacement path is preserved. The frontend is untouched and the published
status is unchanged in both modes.

### Finding

1. **A debug-extended watch now survives `stop_all()`.** Review 03 required two things at
   once: remove the watch from `self.watches` so it cannot block a replacement, *and* keep
   `stop_all()` able to force-stop everything. As implemented these conflict — popping the
   watch satisfies the first and defeats the second, because `stop_all()` iterates only
   `self.watches`.

   I verified the production sequence directly rather than reading the tests:

   ```text
   registered; extending = True
   stop_watch -> {'status': 'observing', 'watch_id': 'w1'}
   stop_event set after stop_watch: False   (correct - still observing)
   still in registry: False
   stop_event set after stop_all:  False    <-- survives teardown
   ```

   `test_manager_stop_all_stops_debug_extended_and_normal_watches` passes because it calls
   `stop_all()` on a watch still in the registry. It never calls `stop_watch()` first, so it
   does not model what actually happens: the frontend stops the watch on completion, and
   only later does the plugin unload. That is the same gap as review 03 — a test that
   exercises a sequence the system never performs.

   Fix: track observing watches in a second collection on the manager, populated when
   `stop_watch()` leaves one running and drained by `stop_all()`. `self.watches` keeps its
   current meaning for replacement; the new collection exists solely so teardown can reach
   them. Remove an entry when the watch self-terminates so the collection cannot grow
   unbounded across a session.

   The bound today is real but not a substitute: the thread is a daemon and self-terminates
   at the hard ceiling, so worst case is a stray watcher polling Syncthing for up to fifteen
   minutes after the plugin unloads. That is a resource leak against a local REST API, and
   the constraint was explicit.

   Required tests, in this order:
   - `stop_watch` then `stop_all` on a debug-extended watch sets `stop_event` — this fails
     against the current code; confirm that before trusting it;
   - `stop_watch` then `stop_all` still leaves `self.watches` empty, so replacement is
     unaffected;
   - a watch that self-terminates is not retained by the new collection.

Scope stays `py_modules/sdh_ludusavi/syncthing/watcher.py` and `tests/test_watcher.py`. Do
not touch the frontend.

## Authorization

TASK 2: CHANGES REQUESTED

Fix finding 1 only. Do not revisit Task 1, do not begin Task 3, and do not author an
approval note, finalize, merge, tag, or release.

STATUS: CHANGES_REQUESTED
