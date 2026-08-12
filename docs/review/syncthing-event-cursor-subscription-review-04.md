# Review 04 — syncthing-event-cursor-subscription

**Round:** 4
**Branch:** `feat/syncthing-event-cursor-subscription`
**Commit reviewed:** `4920826` (`feat(autosync): split watch caps and surface incomplete upload status`)
**Prior review:** `2fae0e9` (review 03, Task 3 accepted)
**Reviewer:** orchestrator

## TASK 4: ACCEPTED

### Scope

The six files Task 4 lists, plus
`docs/agent_conversations/2026-08-10_syncthing-event-cursor-subscription.json`, created
early to hold the reasoning review 03 required. That file belongs to Task 5; creating it a
round early to satisfy a review instruction is reasonable, and Task 5 must now extend it
rather than overwrite it. 99 insertions, 22 deletions.

### Verification performed

Gates re-run independently by the orchestrator against `4920826`:

```text
pnpm test          335 passed (was 334)
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             917 passed, coverage 89.53%
worktree           clean
review notes       none deleted
```

### Review 03 finding 1 — resolved as instructed

`POST_GAME_WATCH_HARD_CEILING_MS = 300_000`, five minutes, well below the backend's
900-second ceiling, with the comment stating exactly why: the backend handles measurable
peer need, and the shorter frontend cap bounds the silent awaiting-fresh state where there
is no need value to measure. `PRE_GAME_QUIESCENCE_TIMEOUT_MS` stays 120 seconds and is
pinned by an explicit assertion, so the pre-game launch gate cannot drift as a side effect.

The session log records the division of responsibility — frontend ceiling bounds the
no-evidence case, backend stall window bounds the have-evidence case — which is what I
asked for so the gap is closed deliberately rather than by accident.

### Terminal status

Post-game cap expiry now calls `stopWatchTerminally(context, "post_game_upload_incomplete")`
instead of `handlePollFailure(context, "watch_duration_timeout")`, and
`mapSyncthingFailureReason` maps that reason to the new `syncthing_upload_incomplete` kind.

The rendering choices are right. The label
`LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE` joins the existing
`LOCAL BACKUP SAVED - …` family, so it reads as an outcome and leads with the fact the
backup succeeded. The icon is amber alongside `syncthing_no_peers`, not the red reserved
for `error`, and it is grouped with `syncthing_complete` for auto-hide so it does not sit
on screen indefinitely.

The `ACTIONABLE_UNAVAILABLE_REASONS` decision the plan asked to be made deliberately was
made and recorded: excluded, because the local backup succeeded and waiting or restoring
peer connectivity is not a plugin configuration repair. I agree — that set drives
actionable-misconfiguration messaging, and this is neither.

### Mutation test — the gate is real

Reverted the terminal call to the old `handlePollFailure(context, "watch_duration_timeout")`:

```text
Tests  1 failed | 17 passed (18)
```

Restored; tree clean and the full suite green at 335 frontend / 917 pytest.

### Test quality

The strongest test is the one proving the cap actually moved: it records the poll count at
the old 120-second mark, asserts polling continued past it, asserts `stopWatch` was not
called and no status was published at that point, then advances to the new ceiling and
asserts `syncthing_upload_incomplete` is published. A test that only checked the constant's
value would pass even if the timeout branch still fired at the old boundary.

Every relevant assertion is paired with
`expect(mockOnStatus).not.toHaveBeenCalledWith("syncthing_unavailable", …)`, and the file
still carries five `syncthing_unavailable` assertions covering genuine initialization and
API failures, so the reserved meaning is pinned from both directions.

### Finding

1. **Revert the unrelated const-declaration churn (fold into Task 5).** Two lines became
   one:

   ```ts
   const EMPTY_SAMPLE_RETRY_MS = 250, ACTIVE_POLL_INTERVAL_MS = 500;
   ```

   Neither constant is part of this task, comma-joined declarations do not match the
   surrounding style, and it makes future line-level blame on those constants point at this
   commit for no reason. Restore them to two separate `const` lines in the Task 5 commit.
   This is style-only with no behaviour change; do not let it grow into any other edit in
   that file.

### Note carried forward

Still decisive and still open: 917 pytest and 335 frontend tests say nothing about whether
events reach the watcher. Only plan verification step 4 does. `steamdeck-legos` was
unreachable at 09:24 today. If it is still down when Task 5 completes, report that step as
blocked; do not record it as passed, and do not substitute the unit suite for it.

## Authorization

TASK 4: ACCEPTED
AUTHORIZED TASK: 5

Proceed with Task 5 — correct the documentation and record verification — as written in the
plan, plus finding 1 above. Extend the existing session-log JSON rather than replacing it;
its current `design_decisions` entries are part of the audit trail for Task 4. Task 5 only.
This is the final implementation task: mark the round complete and stop for review. Do not
author an approval note, finalize, merge, tag, or release. Approval is a human act and the
human approver has not yet reviewed this work.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 4 recorded above.

STATUS: CHANGES_REQUESTED
