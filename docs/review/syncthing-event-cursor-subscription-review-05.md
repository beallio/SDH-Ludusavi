# Review 05 — syncthing-event-cursor-subscription

**Round:** 5
**Branch:** `feat/syncthing-event-cursor-subscription`
**Commit reviewed:** `ca86ac2` (`docs(syncthing): correct event subscription and upload status contract`)
**Prior review:** `eda4bd0` (review 04, Task 4 accepted)
**Reviewer:** orchestrator

## TASK 5: CHANGES REQUESTED

The documentation work is right and the audit trail is complete. One unrelated regression
in `README.md` has to be reverted before this task can be accepted.

### Verification performed

Gates re-run independently by the orchestrator against `ca86ac2`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             917 passed, coverage 89.53%
worktree           clean
review notes       none deleted
```

### What is correct

The `RemoteDownloadProgress` premise is properly rewritten. The old claim — that it is not
authoritative because remote puller requests may be absent — is gone, and the replacement
gives the real reason: peer completion's need counters persist across gaps between
transient block requests and express `needDeletes` even when bytes are zero, a state the
2026-08-09 capture actually contained and which block-request activity cannot represent.
That argument stands on evidence rather than on an absence that we now know proves nothing.

The subscription mechanism is documented where the next reader will need it: `id` is scoped
to the subscription selected by `events=`, `since` matches that scoped `id`, `globalID` is
process-wide and must not be used as a cursor, and every `/rest/events` call site including
cursor seeding uses the same filter.

Both ceilings, the stall window with its 60-second-plateau justification, and the new
terminal status are documented in the specs, with `syncthing_unavailable` explicitly
reserved for API and initialization failures.

Review 04's finding is resolved: the two constants are two `const` lines again. The commit
also drops a stray trailing-whitespace line in the same file. That is whitespace-only, and
I am not asking for it back.

The session log is complete against the plan: Task 1-4 hashes with subjects, a
`task_5_subject` rather than a self-referential hash, four review-note paths, per-task RED
proofs, validation results, and all four deferred items including the two that record the
constants as single-observation judgement calls.

### Finding

1. **Restore the Ludusavi operation-timeout facts deleted from `README.md`.** The commit
   replaced this line:

   ```text
   Backups and restores are limited to 15 minutes (status checks to 5 minutes); if Ludusavi exceeds this — for example, a stalled cloud sync — the operation is reported as failed instead of hanging, and any paused game is resumed automatically.
   ```

   with a version that keeps only "limited to 15 minutes" and drops the rest. Three
   user-facing facts were lost, and all three are still true in the code:

   - status checks are limited to 5 minutes — `LUDUSAVI_PREVIEW_TIMEOUT_SECONDS = 300.0`;
   - an exceeded operation is reported as failed rather than hanging;
   - a paused game is resumed automatically — `WATCHDOG_ABSOLUTE_RESUME_SECONDS =
     LUDUSAVI_OPERATION_TIMEOUT_SECONDS + 60.0`.

   None of this concerns Syncthing, and the auto-resume promise in particular is the
   reassurance a user needs when a backup stalls behind a paused game. Deleting it is
   outside Task 5's scope.

   Keep the new Syncthing sentence; restore the old clauses alongside it. Replace lines
   111-114 of `README.md` with exactly:

   ```text
   Backups and restores are limited to 15 minutes (status checks to 5 minutes); if Ludusavi
   exceeds this — for example, a stalled cloud sync — the operation is reported as failed
   instead of hanging, and any paused game is resumed automatically. Syncthing monitoring is
   advisory and never blocks launch or exit: when its post-game observation boundary is
   reached, the plugin reports the resulting upload state rather than presenting an ordinary
   slow sync as an API failure.
   ```

   Amend or add a commit for this, rerun the quality gates, and recreate the round-complete
   marker. Change nothing else in `README.md`. Record in the session log that the clauses
   were removed and restored, so the round-trip is visible in the audit trail rather than
   looking like they were never touched.

### Note carried forward

Unchanged: 917 pytest and 335 frontend tests demonstrate nothing about whether events reach
the watcher. Only plan verification step 4 does, and `steamdeck-legos` has been unreachable
since 09:24 today. That step is currently **blocked, not passed**, and must be reported that
way. Do not attempt to substitute the unit suite for it, and do not mark the plan's
verification section complete on the strength of the gates alone.

## Authorization

TASK 5: CHANGES REQUESTED

Fix finding 1 only. Do not begin any other work, do not revisit accepted tasks, and do not
author an approval note, finalize, merge, tag, or release. Approval is a human act and the
human approver has not yet reviewed this work.

STATUS: CHANGES_REQUESTED
