# Review 03 — syncthing-event-cursor-subscription

**Round:** 3
**Branch:** `feat/syncthing-event-cursor-subscription`
**Commit reviewed:** `3a6e4c8` (`feat(syncthing): stop a stalled post-game watch with a truthful reason`)
**Prior review:** `4a66900` (review 02, Task 2 accepted)
**Reviewer:** orchestrator

## TASK 3: ACCEPTED

### Scope

The three files Task 3 lists, plus `activity.py`, which the plan's step 4 explicitly
authorized for the predicate extraction. 265 insertions, 56 deletions — the deletions are
the two duplicated predicate bodies being replaced by calls to the shared helpers, not
removed coverage.

### Verification performed

Gates re-run independently by the orchestrator against `3a6e4c8`:

```text
pnpm test          334 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             917 passed (was 912), coverage 89.53%
worktree           clean
review notes       none deleted
```

### Predicate extraction — review 02 finding resolved

`peer_completion_is_incomplete()` and `summarize_peer_completions()` now live in
`_types.py`, and all three former copies call them: `compute_activity_status()`,
`process_event()`, and `_log_peer_completion_transition()`. The stall detector is the
fourth caller rather than a fourth copy, which is what the instruction was for.

I checked the refactor is behaviour-preserving rather than assuming it:
`incomplete_peer = diagnostics.incomplete_peers > 0` and
`awaiting_fresh_peer_completion = diagnostics.awaiting_fresh_completion > 0` are
equivalent to the any-style loops they replace, and `process_event()`'s hold-extension
condition is the same predicate. 917 tests pass including the whole peer-completion suite
from the previous plan, which is the real evidence here — those tests were written against
the old inline logic.

### Constants

Both carry the reasoning the plan asked for. `OUTBOUND_STALL_WINDOW_SECONDS = 90.0` is
justified against the observed straggler that held `needDeletes` unchanged for roughly
sixty seconds while still progressing, so the window clears the one real measurement we
have. `POST_GAME_WATCH_HARD_CEILING_SECONDS = 900.0` is framed as a backstop rather than
the normal path.

The watch TTL is widened to the ceiling plus sixty seconds for post-game only, so the
thread cannot be reaped before its own ceiling logic runs. `self.phase` is assigned before
that computation, so the `_peer_completion_tracking` property is safe at that point — I
checked, since an ordering slip there would be an `AttributeError` at construction.

### Stall detection

The mechanism is sound. Progress is tracked as `aggregate_outstanding_need`
(bytes + items + deletes) and the stall clock resets whenever that total falls, so a peer
grinding through deletes with zero bytes outstanding still counts as progressing — which is
exactly the 2026-08-09 case. Trackers reset when no peer is incomplete, so an
incomplete→complete→incomplete cycle does not accumulate a false stall.

The terminal result uses the existing `{"status": "failed", "reason": ..., "message": ...}`
shape that `no_connected_peers` already uses, so no RPC sample key was added and the
seven-key surface is untouched. The message carries no device IDs, counts, folder paths, or
payloads.

### Mutation test — the gate is real

Forced the stop branch to never fire:

```text
FAILED test_post_game_unchanged_outbound_need_stops_with_sanitized_truthful_reason
FAILED test_post_game_watch_stops_at_hard_ceiling_despite_outbound_progress
2 failed, 49 passed
```

Restored; tree clean and the full suite green at 917. The stall path and the ceiling path
are independently anchored — killing one branch fails both tests, so neither is standing in
for the other.

The five tests cover all four cases the plan required plus the ceiling: progress past the
stall window keeps the watch alive, unchanged need stops it with a sanitized reason, an
all-complete-and-fresh watch settles without the terminal reason, a pre-game watch never
emits it, and the ceiling fires even while progress continues.

### Findings

1. **`awaiting_fresh_completion` has no stall bound (address in Task 4).** The detector
   returns early when `diagnostics.incomplete_peers == 0`, so a watch where every connected
   peer is *silent* — `awaiting_fresh_completion > 0` with `incomplete_peers == 0` — is
   never treated as stalled and runs to the 900-second ceiling. That is the precise state
   the 2026-08-09 device run was stuck in for 111 seconds, and this change lengthens that
   pathological case from the old 120-second frontend cap to fifteen minutes.

   I am not asking you to restructure Task 3. Tasks 1 and 2 make the silent state far less
   reachable, and "need decreasing" genuinely cannot be measured for peers reporting
   nothing. But the gap should not be closed by accident, so handle it deliberately in
   Task 4: set the frontend post-game ceiling well below 900 seconds so a silent watch is
   still bounded by something a user would wait through, and record in the session log that
   the frontend ceiling is what bounds the no-evidence case while the backend stall window
   bounds the have-evidence case. If you conclude a backend-side bound on sustained
   awaiting-fresh is better, say so in the log and leave it for a follow-up plan rather
   than widening Task 4.

2. **Growing need can bias the stall clock (note only, no action).** The decrease timestamp
   only advances when the total falls, so a watch where outstanding need keeps *rising* —
   a second mutation landing mid-watch — accrues stall time despite real activity. It self-
   corrects as soon as the total falls below its previous value, and a post-game watch is
   unlikely to see sustained growth. Recording it so it is not rediscovered as a mystery.

### Note carried forward

Unchanged and still decisive: 917 green tests say nothing about whether events reach the
watcher. Only plan verification step 4 does. `steamdeck-legos` was unreachable at 09:24
today; if it is still down when Task 5 completes, report that step blocked, not passed.

## Authorization

TASK 3: ACCEPTED
AUTHORIZED TASK: 4

Proceed with Task 4 — split the watch caps and surface the new terminal status — as written
in the plan, plus finding 1 above. The backend reason string to map is
`post_game_upload_incomplete`. Task 4 only. Stop for review when the atomic commit and the
round-complete marker are in place. Do not begin Task 5 while waiting.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 3 recorded above.

STATUS: CHANGES_REQUESTED
