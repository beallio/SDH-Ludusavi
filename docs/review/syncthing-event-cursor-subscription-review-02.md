# Review 02 — syncthing-event-cursor-subscription

**Round:** 2
**Branch:** `feat/syncthing-event-cursor-subscription`
**Commit reviewed:** `86ac8f8` (`fix(syncthing): re-seed the cursor when a subscription resets`)
**Prior review:** `23f6753` (review 01, Task 1 accepted)
**Reviewer:** orchestrator

## TASK 2: ACCEPTED

### Scope

Exactly the two files Task 2 lists: `py_modules/sdh_ludusavi/syncthing/watcher.py` and
`tests/test_watcher.py`. 95 insertions, **zero deletions** — no existing test or assertion
was modified this round.

### Verification performed

Gates re-run independently by the orchestrator against `86ac8f8`:

```text
pnpm test          334 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             912 passed (was 909), coverage 89.43%
worktree           clean
review notes       none deleted
```

### The production change

Six lines at the top of `_tick_events()`:

```python
event_ids = [int(event.get("id", self.cursor)) for event in events]
if any(event_id < self.cursor for event_id in event_ids):
    self.cursor = max(event_ids)
    logger.info("Syncthing event subscription reset detected; re-seeding event cursor.")
```

I traced this against both paths rather than reading it for plausibility.

**Reset path.** Cursor at 500, batch arrives with ids `[1, 2, 3]`. Without the guard the
existing `max(self.cursor, ...)` advance holds the cursor at 500 and every subsequent poll
matches nothing — the original bug, reproduced mid-watch. With the guard the cursor drops
to 3 first, and the existing `max()` then keeps it at 3 rather than dragging it back up.
The guard is genuinely load-bearing, not decorative.

**Normal path.** Cursor at 248, batch `[249, 250]`. `any(id < 248)` is false, the guard does
nothing, and the existing advance carries the cursor to 250. Untouched.

**Events are still processed.** The guard only adjusts the cursor; the `for` loop below it
still feeds every event through `process_event()`. The plan required that a reset batch be
processed rather than discarded, and it is.

Two details worth crediting. The `event.get("id", self.cursor)` default means an event
missing an `id` contributes the current cursor, which is never less than itself — so a
malformed event cannot spuriously trigger a reset. And the log cannot repeat: once
re-seeded, subsequent batches carry higher ids, so a single reset produces a single record.

### Mutation test — the gate is real

Plan verification step 3 requires proving the Task 2 tests can fail. I removed the reset
branch and ran the focused suite:

```text
FAILED test_event_subscription_reset_reseeds_cursor_and_processes_returned_events
FAILED test_event_subscription_reset_logs_once_without_sensitive_event_details
2 failed, 44 passed
```

Restored; `git status` clean and the full suite green at 912. Note that two tests fail, not
one — the behavioural assertion and the logging assertion are independently anchored to the
guard, so neither is riding on the other.

### Test quality

The reset test asserts more than the cursor value. It checks `call_count == 2` *and*
compares the actual event objects passed to `process_event` against the batch, so
"processed rather than discarded" is pinned by identity rather than inferred from a count.

The forward-motion test is the negative control for this round: it would fail if the guard
were written to re-seed unconditionally rather than only on a detected reset, which is the
obvious wrong implementation.

The logging test uses distinct sentinels — `SECRET-REMOTE-ID`, `SECRET-FOLDER`,
`RAW-EVENT-PAYLOAD` — for the device, folder, and payload it must not leak, so a failure
tells you *which* category leaked instead of just that something did.

### Note carried forward (no action)

Unchanged from review 01 and still the decisive gap: 912 green tests demonstrate nothing
about whether events reach the watcher, because the suite was green throughout the period
the stream was dead. Only plan verification step 4, the live device probe, closes that.
`steamdeck-legos` was unreachable at 09:24 today. If it is still down when Task 5 completes,
report the step as blocked; do not record it as passed.

## Authorization

TASK 2: ACCEPTED
AUTHORIZED TASK: 3

Proceed with Task 3 — stop a stalled post-game watch with a truthful reason — as written in
the plan. Task 3 only. Note the plan's instruction in step 4 of that task: if
`compute_activity_status()` and `_log_peer_completion_transition()` still compute the
incomplete and awaiting-fresh conditions independently, extract that predicate to one
function and call it from all sites rather than adding a third copy. Stop for review when
the atomic commit and the round-complete marker are in place. Do not begin Task 4 while
waiting.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 2 recorded above.

STATUS: CHANGES_REQUESTED
