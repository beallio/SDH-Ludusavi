# Review 01 — syncthing-peer-completion-upload-status

**Round:** 1
**Branch:** `feat/syncthing-peer-completion-upload-status`
**Commit reviewed:** `5bc0c6f` (`feat(syncthing): model peer completion activity`)
**Plan commit:** `f626874`
**Reviewer:** orchestrator

## TASK 1: ACCEPTED

### Scope

The commit touches exactly the six files Task 1 lists and nothing else:

```text
py_modules/sdh_ludusavi/syncthing/_types.py
py_modules/sdh_ludusavi/syncthing/activity.py
py_modules/sdh_ludusavi/syncthing/__init__.py
tests/test__types.py
tests/test_activity.py
tests/test_syncthing.py
```

550 insertions, 2 deletions. Both deletions are substitutions, not weakenings: the
`uploading = bool(remote_progress)` line that the new classifier replaces, and an import
line in `tests/test__types.py` that was extended. No existing assertion was removed,
relaxed, or retargeted, which is the failure mode the plan's scope-discipline section
names explicitly.

### Verification performed

Quality gates re-run independently by the orchestrator against `5bc0c6f`, not taken on
trust from the implementer:

```text
pnpm test          331 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             892 passed, coverage 89.06% (gate 83%)
worktree           clean
review notes       none deleted
```

### Plan conformance

1. **`EVENT_TYPES` includes `FolderCompletion`.** Added to the filtered subscription in
   `_types.py`, asserted in `tests/test__types.py`.
2. **Folder- and peer-scoped acceptance.** `_parse_peer_completion()` requires
   `data["folder"] == folder.folder_id` *and* `device in folder.device_ids`. The
   parametrized rejection table covers an unrelated folder, the local device, an
   unconfigured device, a missing `device`, a missing `folder`, a non-object `data`
   payload, non-finite `completion` (NaN and inf), out-of-range `completion` (-0.1,
   100.1), negative `needBytes`, fractional `needItems`, and a boolean `needDeletes`.
   The bool case matters — `isinstance(True, int)` is true in Python, and
   `_bounded_number()` rejects it explicitly rather than silently reading `True` as `1`.
3. **No payload leakage.** The parse path contains no logging at all, so a malformed
   payload cannot reach the log. This satisfies the requirement by construction.
   See finding 1 below on guarding it.
4. **Classification table.** `test_connected_peer_completion_classifies_outbound_need`
   is parametrized over exactly the plan's five cases and uses the real numbers from the
   August 7 Steam Deck capture (93.56119493792454, 8_942_011 needed bytes, 32 needed
   items, 19 needed deletes) rather than invented placeholders.
5. **Freshness by monotonic timestamp, not sequence comparison.** Staleness is
   `completion.observed_monotonic < local_activity.outbound_index_observed_monotonic`.
   No local/remote sequence numbers are compared anywhere, as plan item 7 requires.
6. **Independent peers.** `incomplete_peer` and `awaiting_fresh_peer_completion` latch
   true across the loop over `connected_relevant_device_ids`, so a settled peer cannot
   mask an incomplete or not-yet-fresh one.
7. **Observation hold.** `OUTBOUND_OBSERVATION_HOLD_SECONDS = 2.5` is extended by
   `max()` on both a watched-folder index advance and an *incomplete* `FolderCompletion`,
   and deliberately not extended by a terminal 100%/zero-counter completion — correct, or
   the hold could never expire. Expiry is evaluated against the caller-supplied `now`, so
   the test is deterministic with no sleeping.
8. **Same-batch collapse is covered.** When `LocalIndexUpdated` and the final 100%
   completion share a timestamp, the freshness check alone would treat the snapshot as
   fresh (`<` is strict). The hold is what keeps `uploading` true across that batch, which
   is precisely the role the plan assigns it. Verified by
   `test_outbound_observation_hold_survives_same_batch_mutation_and_completion`.
9. **Downstream flags.** `uploading` feeds `active_transfer`, which forces
   `status="ACTIVE_TRANSFER"`, `update_in_progress=True`, and `settled=False`. Plan item
   3 holds.
10. **Default-disabled compatibility.** `peer_completion_tracking` defaults to `False` in
    both `process_event()` and `compute_activity_status()`, and
    `connected_relevant_device_ids` defaults to an empty frozenset. The disabled-tracking
    control test and the pre-game classifier test in `tests/test_syncthing.py` confirm
    identical prior classification with the same incomplete peer data. Pre-game behavior
    is untouched, and Task 2 can wire the flag explicitly.
11. **RPC surface unchanged.** `_serialize_sample()` is not modified;
    `test_peer_completion_does_not_change_activity_sample_keys` pins the key set.
    `PeerCompletion` and the two new `LocalActivity` timestamps stay backend-only.

### Notes carried forward (not defects, no action this round)

- `outbound_index_observed_monotonic` and the hold deadline are written on any watched
  index advance regardless of `peer_completion_tracking`. They are only ever *read* under
  the flag, so pre-game classification is unaffected. Harmless as written; no change
  requested.
- A connected relevant peer that never reports a post-mutation completion keeps
  `awaiting_fresh_peer_completion` true indefinitely at this layer. That is the specified
  classifier behavior. The terminal condition lives in the watcher — the plan's
  `no_connected_peers` boundary and the partial-disconnect rule — and is Task 2's
  responsibility. Flagged here so it is not lost, not as a Task 1 defect.
- `_MAX_COMPLETION_COUNTER` round-trips through `float`, so a counter within one ULP of
  2^63 is rejected. Unreachable for real byte and item counts. No action.

### Findings

1. **Add a no-log regression guard for malformed payloads (fold into Task 2).** The
   requirement that a rejected completion payload never leaks its contents currently holds
   because the parse path logs nothing — but nothing *pins* that. A future maintainer
   adding a debug line to `_parse_peer_completion()` would silently break the guarantee
   with every test still green. When Task 2 adds the watcher's initialization and event
   error boundary, extend one malformed-payload case with a `caplog` assertion that no
   record emitted from the syncthing logger contains the device ID or the raw payload.
   This is additive test coverage; do not restructure the Task 1 parser to accommodate it.

## Authorization

TASK 1: ACCEPTED
AUTHORIZED TASK: 2

Proceed with Task 2 — integrate peer completion into the watcher and diagnostics — as
written in the plan, plus finding 1 above. Task 2 only. Stop for review when its atomic
commit and the round-complete marker are in place. Do not begin Task 3, prepare its
tests, or make opportunistic edits while waiting.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 1 recorded above.

STATUS: CHANGES_REQUESTED
