# Plan: Show Syncthing Uploading from Peer Completion (syncthing-peer-completion-upload-status)

## Context

### Problem Definition

After a successful post-game Ludusavi backup, the status strip currently shows
`SYNCTHING PREPARING` and may jump directly to `SYNCTHING COMPLETE` even while a
connected peer is still downloading the changed backup data. The August 7 Steam Deck
log demonstrated that exact sequence: the backup completed, PREPARING appeared one
second later, and COMPLETE followed about 26 seconds later, with no intervening
`Syncthing activity observed` or uploading status.

The current backend subscribes to `RemoteDownloadProgress` and treats a non-empty event
as upload evidence. That event describes the remote puller's transient per-file block
requests; it is not a durable sender-side progress signal and was absent during the
observed sync. The post-game frontend can therefore see a local index mutation and later
three settled samples without ever seeing `sample.uploading=true`.

A read-only viability check against the available Steam Deck's Syncthing 2.1.2 event
history found the stronger signal. Two connected peers emitted folder-scoped
`FolderCompletion` events at 93.56119493792454% with 8,942,011 needed bytes, 32 needed
items, and 19 needed deletes, then separately reached 100%. The same window contained
zero `RemoteDownloadProgress` events. Replaying those events would have sustained an
uploading state for about 41 seconds. Syncthing 2.1.2 emits `FolderCompletion` for every
configured remote device when local or remote index state changes; its summary service
normally pumps at roughly two-second intervals.

Implement a folder- and peer-scoped post-game outbound state using `FolderCompletion`. Show
`SYNCTHING UPLOADING` while a currently connected peer that shares the watched backup
folder is behind, while the watcher is awaiting that peer's first completion report
after a local index mutation, or during a short observation hold that prevents a
same-event-batch mutation/completion pair from disappearing between frontend polls.
Keep `RemoteDownloadProgress` as supplemental evidence. Publish COMPLETE only after the
local folder is settled and all currently connected relevant peers have reported fully
caught up after the mutation.

### Architecture Overview

- Keep the existing deepest-folder resolution and relevant-peer connectivity boundary.
  `/rest/system/connections` continues to provide connectivity only; global/per-device
  connection byte counters remain prohibited as activity evidence.
- Add `FolderCompletion` to the filtered Syncthing event subscription. Accept an event
  only when both its `folder` matches the resolved backup folder and its `device` belongs
  to that folder's configured remote-device set.
- For post-game watches only, initialize completion state with
  `/rest/db/completion?folder=<folder>&device=<device>` for each currently connected
  relevant peer, then update that state from events. A peer is incomplete when
  completion is below 100 or any of `needBytes`, `needItems`, or `needDeletes` is
  positive. Pre-game watches must not call this endpoint or use peer completion to
  extend the launch gate.
- Record when the watched folder's local index sequence advances. A completion snapshot
  older than that mutation does not acknowledge the mutation. Until every currently
  connected relevant peer has a newer completion snapshot, outbound propagation is
  pending and `uploading` remains true.
- Hold newly observed outbound evidence for 2.5 seconds. This is an internal observation
  hold, not a fabricated percentage: it covers Syncthing's approximately two-second
  summary cadence and guarantees several observations by the existing 500 ms frontend
  poller even when `LocalIndexUpdated` and the final 100% `FolderCompletion` arrive in
  one REST event batch.
- Preserve post-game upload evidence across the backup handoff. The frontend must not
  consume its three settled samples or promote the state to COMPLETE before
  `handoff_confirmed`; after handoff, three distinct settled samples retain the existing
  stability check and make UPLOADING visibly precede COMPLETE.
- Preserve pre-game classification and settlement exactly. Existing folder-local
  download, scan, need, index, and `RemoteDownloadProgress` evidence remains the only
  pre-game input; connected peers catching up to the Deck must not add launch latency.
- Emit bounded transition diagnostics with counts and aggregate need values only. Never
  log, serialize, or return Syncthing device IDs.

### Core Data Structures

- Add an internal `PeerCompletion` record in
  `py_modules/sdh_ludusavi/syncthing/_types.py` containing the backend-only device ID,
  completion percentage, need byte/item/delete counts, and the monotonic observation
  time.
- Extend `LocalActivity` with outbound-index observation and hold-deadline timestamps.
  These are monotonic process-local values and never enter RPC payloads.
- Keep peer completion records in `SyncthingWatch`, keyed by backend-only device ID.
  Derive the relevant connected set from `FolderSelection.device_ids` intersected with
  the latest `ConnectionSnapshot.connected_devices`.
- Extend internal `ActivityStatus` diagnostics as needed with count/aggregate fields for
  transition logging. Do not expose raw device IDs or peer percentages.
- Keep `SyncthingActivitySample` and all existing frontend status names unchanged:
  `uploading` remains a boolean and no numeric progress bar is added.

Do not use `FolderCompletion.sequence` as a local acknowledgement token. Syncthing 2.1.2
defines it as the selected remote device's own database sequence, so it is not comparable
to the Steam Deck's local sequence. Freshness is established by event ordering and
monotonic observation time; completeness comes from the percentage and need counters.

### Public Interfaces

No public RPC, persisted setting, or frontend wire-format change is allowed. Preserve:

- `start_syncthing_activity_watch(phase, game_name?, app_id?)`;
- `get_syncthing_activity(watch_id)` and `stop_syncthing_activity_watch(watch_id)`;
- the start result and activity sample keys already defined in `src/types/index.ts`;
- existing status strings, icons, BrowserView layout, 900 ms local-backup dwell,
  detection grace, watch TTL, and pre-game launch-gate behavior.

The user-visible semantic refinement is limited to post-game outbound status: UPLOADING
now means the Deck has folder-scoped evidence that connected relevant peers are catching
up (or have not yet acknowledged the new local index), and post-game COMPLETE means the
local folder is settled and those connected relevant peers have reported no outstanding
need. It still does not guarantee an offline or disconnected configured peer has the
save. Pre-game completion retains its current local settlement meaning.

### Dependency Requirements

No Python, TypeScript, package, system, or Syncthing version dependency changes are
required. Use the existing local Syncthing REST/event API client. The implementation
must remain compatible with the installed Syncthing 2.1.2 response shape and tolerate
valid numeric JSON values without adding a third-party parser.

### Testing Strategy

- Follow strict TDD inside every behavior-changing atomic task: add the focused failing
  test, run it against production code, record the expected failure, implement the
  minimum behavior, and rerun green before the task's full quality gate.
- Unit-test event filtering, numeric validation, peer freshness, need-counter
  classification, and the observation hold with injected monotonic times; no test may
  rely on wall-clock sleeps.
- Exercise the complete watcher boundary with mocked local REST responses and ordered
  event batches, including initialization races, multi-peer progress, connection loss,
  privacy-safe diagnostics, and stable RPC serialization.
- Add a negative pre-game boundary test proving it neither calls the completion endpoint
  nor lets peer lag delay the existing launch-settlement path.
- Exercise the frontend as a pure transition system and through `SyncthingMonitor` fake
  timers, proving the upload state survives a pre-handoff settle and only advances after
  three new post-handoff samples.
- Run explicit production-branch mutation tests and negative folder/device controls so
  a passing replay cannot come from a test-only path or unscoped Syncthing traffic.
- Preserve the planning-time live Deck trace as viability evidence and defer installed
  build/UI acceptance until the development prerelease exists after finalization.

### Scope and Acceptance Boundaries

- Scope activity to the resolved backup folder and its configured remote devices.
- Preserve incoming/download classification and `RemoteDownloadProgress` behavior.
- Apply new peer-completion freshness, need counters, observation hold, and completion
  gating only when `SyncthingWatch.phase == "post_game"`.
- A malformed completion payload must not crash the watcher or leak its raw payload; it
  must be ignored or converted to the existing sanitized watch failure according to the
  initialization/event error boundary tested in the relevant task.
- A peer that was never connected is not a completion target. If every relevant peer
  disconnects, retain the existing terminal `no_connected_peers` result. If one of
  several peers disconnects, evaluate completion against the relevant peers that remain
  connected and document that boundary.
- Do not add a numeric progress UI, new setting, new RPC field, polling loop in the
  frontend, release-version change, stable tag, or unrelated Syncthing refactor.
- Preserve the user-owned untracked `docs/issues-to-import.md`; do not stage, edit,
  format, or commit it.

**Slug used throughout this plan:** `syncthing-peer-completion-upload-status`

---

## Orchestration Contract

**Slug:** `syncthing-peer-completion-upload-status`

**Plan file:**

```text
docs/plans/2026-08-09_syncthing-peer-completion-upload-status.md
```

**Implementation branch:**

```text
feat/syncthing-peer-completion-upload-status
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-peer-completion-upload-status_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-peer-completion-upload-status_finalized
```

**Review notes:**

```text
docs/review/syncthing-peer-completion-upload-status-review-*.md
```

Each review note ends with exactly one status trailer:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

---

## Required Agent Protocol

1. Use the **implementer** skill.
2. Work from the repository root.
3. Branch from `dev`.
4. Commit this plan as the first commit on the implementation branch.
5. Follow TDD where behavior changes are testable.
6. Run quality gates before marking any round complete.
7. Do not write your own review.
8. Do not create files under `docs/review/`.
9. Do not delete files under `docs/review/`.
10. Review notes are durable audit records and must be committed.
11. Resolving a review note means:
    - implement the requested changes;
    - run quality gates;
    - commit the code/docs changes;
    - commit the review note itself if it is not already committed;
    - recreate the round-complete marker.
12. After finalization, stop polling and exit cleanly.

### Atomic task review gate

This plan deliberately uses one implementation task per orchestration round.

1. The initial round authorizes **Task 1 only**.
2. Complete the authorized task end to end: write its RED tests, prove the expected
   failure, implement GREEN, refactor, run that task's focused checks and the full
   quality gates, make only that task's atomic Conventional Commit, mark the round
   finished, and exit.
3. Do not begin the next numbered task, prepare its tests, or make opportunistic edits
   while waiting for review.
4. On continuation, read the latest committed review note. If it requests corrections,
   fix only the same task and stop for review again. Advance only when the note states
   both `TASK N: ACCEPTED` and `AUTHORIZED TASK: N+1`.
5. The orchestration engine uses `STATUS: CHANGES_REQUESTED` for every non-final
   continuation. A note that accepts Task N and authorizes Task N+1 therefore still ends
   in `STATUS: CHANGES_REQUESTED`; that trailer is a mechanical resume signal, not a
   rejection of the accepted task.
6. `STATUS: APPROVED` is reserved for human approval after Task 4 and all prior task
   reviews are complete. Never interpret approval of one task as approval of the plan.
7. If a review note is missing, ambiguous, skips a task number, or authorizes more than
   one task, stop without changing files and report the gate violation.

---

## Scope discipline

- Implement only the units the plan lists. Do not modify files outside the plan's scope.
- Do not change runtime behavior beyond what the plan specifies. A `refactor` or
  `cleanup` commit must preserve observable behavior.
- Never edit a test's expected value to make a behavior change pass. If a test
  legitimately must change, that change must be required by the plan or a review
  note, and you must record the rationale in the session log.
- If you spot an unrelated improvement, do not make it here — note it in the
  session log for a separate plan.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/syncthing-peer-completion-upload-status
```

Commit this plan first:

```bash
git add docs/plans/2026-08-09_syncthing-peer-completion-upload-status.md
git commit -m "docs(plan): add syncthing-peer-completion-upload-status implementation plan"
```

---

## Implementation Tasks

### Task 1 — Model folder-completion evidence and classification

**Initially authorized. Stop for review after this task.**

Files in scope:

- `py_modules/sdh_ludusavi/syncthing/_types.py`
- `py_modules/sdh_ludusavi/syncthing/activity.py`
- `py_modules/sdh_ludusavi/syncthing/__init__.py`
- `tests/test__types.py`
- `tests/test_activity.py`
- `tests/test_syncthing.py`

Follow RED-GREEN-REFACTOR within this task:

1. Add failing tests proving `EVENT_TYPES` includes `FolderCompletion` and the new
   parser/reducer accepts only the watched folder plus a configured remote device.
   Unrelated folders, the local device, unknown devices, missing identifiers, non-object
   payloads, non-finite percentages, and invalid counters must not create upload evidence
   or expose payload/device contents in errors.
2. Add table-driven classification tests for:
   - a connected relevant peer below 100%;
   - 100% with positive `needBytes`, `needItems`, or `needDeletes`;
   - all counters zero at 100%;
   - a pre-mutation completion snapshot becoming stale after a watched-folder
     `LocalIndexUpdated` sequence advance;
   - a fresh post-mutation 100% snapshot acknowledging that mutation;
   - two peers progressing independently, where one complete peer cannot hide another
     incomplete or not-yet-fresh peer;
   - a disconnected or unrelated peer not holding the watched folder active;
   - `RemoteDownloadProgress` continuing to set uploading independently;
   - the 2.5-second outbound evidence hold surviving a mutation and final completion in
     the same event batch, then expiring deterministically under a supplied monotonic
     `now`.
3. Assert `settled=false`, `update_in_progress=true`, and `status=ACTIVE_TRANSFER`
   whenever any valid outbound condition is active. Assert all three return to their
   idle/settled values only after relevant peers are fresh and complete and the hold has
   expired.
4. Add a disabled-tracking control that supplies the same incomplete peer data but
   preserves the prior local-only/pre-game classification. Design the new classifier
   input to default to the compatibility-preserving disabled state until Task 2 wires it
   explicitly for post-game watches.
5. Run the focused suite and record the expected failing assertions before production
   edits:

   ```bash
   ./run.sh uv run pytest tests/test__types.py tests/test_activity.py tests/test_syncthing.py
   ```

6. Add the internal `PeerCompletion` model, strict bounded numeric parsing helpers, and
   the 2.5-second hold constant. Extend `process_event()` and
   `compute_activity_status()` only as needed by the tests. Keep device IDs backend-only
   and keep `_serialize_sample()` byte-for-byte compatible in key set.
7. Use completion/need counters for completeness and monotonic timestamps for freshness;
   do not compare local and remote sequence numbers. Preserve all existing local scan,
   download, need, error, and remote-progress classification rules.
8. Run the focused suite again, then the plan quality gates. Commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/_types.py py_modules/sdh_ludusavi/syncthing/activity.py py_modules/sdh_ludusavi/syncthing/__init__.py tests/test__types.py tests/test_activity.py tests/test_syncthing.py
   git commit -m "feat(syncthing): model peer completion activity"
   ```

Run `scripts/orchestration/mark-finished syncthing-peer-completion-upload-status` and
exit. Task 2 is forbidden until an atomic review note authorizes it.

### Task 2 — Integrate peer completion into the watcher and diagnostics

**Authorized only by a committed review note accepting Task 1. Stop for review after
this task.**

Files in scope:

- `py_modules/sdh_ludusavi/syncthing/activity.py`
- `py_modules/sdh_ludusavi/syncthing/watcher.py`
- `tests/test_activity.py`
- `tests/test_watcher.py`

1. Write failing watcher tests before production edits. Cover initialization ordering,
   per-peer REST baselines, event updates, connectivity changes, settlement gating,
   privacy-safe logs, and the unchanged RPC sample shape.
2. Add a helper for `/rest/db/completion` that validates one peer response and a helper
   that captures baselines for the connected relevant set. Invoke them only for a
   post-game watch. That watch must establish a race-safe baseline in this order: initial
   folder state, event cursor, peer completion snapshots, then a second
   folder-status/sequence observation. A mutation detected by either the event stream or
   the second/current status observation must arm outbound evidence; an event after the
   cursor must not be lost merely because the baseline call already reflects its result.
3. Post-game initialization must fail through `watch_initialization_failed` with a
   bounded, sanitized message if the completion endpoint is unavailable or malformed.
   Never echo the response body or device ID. A pre-game watch must make no completion
   request and must remain available under the same mocked endpoint failure. Transient
   completion-event parse failures after initialization must preserve the last good
   state and let later valid events recover.
4. For post-game classification, pass only
   `FolderSelection.device_ids ∩ connected_devices` and explicitly enable peer tracking.
   On a newly connected relevant peer after a mutation, wait for its fresh completion
   report. On one peer disconnecting while another remains, stop gating on the
   disconnected peer; preserve the existing terminal `no_connected_peers` behavior when
   the intersection becomes empty.
5. Prove with deterministic watcher tests that this captured event sequence produces
   sustained upload and then completion eligibility without `RemoteDownloadProgress`:
   two relevant peers at 93.56119493792454%, aggregate need 8,942,011 bytes / 32 items /
   19 deletes, one peer reaching 100%, and the second reaching 100% later. Also prove an
   unrelated folder and unrelated device cannot influence the watched sample.
6. Add transition-only diagnostics, not per-tick logs. The start/incomplete/acknowledged
   transitions must include phase, connected relevant peer count, incomplete peer count,
   awaiting-fresh-completion count, and aggregate needed bytes/items/deletes. Do not log
   folder paths, device IDs, raw JSON, or one line per poll. Add `caplog` assertions for
   both required fields and forbidden identifiers.
7. Add a pre-game regression proving no `/rest/db/completion` request occurs and the same
   incomplete peer payload cannot hold pre-game `settled` false. Preserve cursor
   monotonicity, tick ordering, copied poll results, thread TTL,
   replacement/stop behavior, and sample serialization. The public sample key set must
   remain exactly `status`, `folder_state`, `update_in_progress`, `settled`,
   `downloading`, `uploading`, and `timestamp_unix`.
8. Prove RED with:

   ```bash
   ./run.sh uv run pytest tests/test_activity.py tests/test_watcher.py
   ```

   Implement GREEN, refactor, rerun the focused suite and quality gates, then commit only
   this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/activity.py py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_activity.py tests/test_watcher.py
   git commit -m "feat(syncthing): track connected peer completion"
   ```

Mark the round finished and exit. Task 3 is forbidden until its review note authorizes
it.

### Task 3 — Preserve uploading through the post-game handoff

**Authorized only by a committed review note accepting Task 2. Stop for review after
this task.**

Files in scope:

- `src/controllers/syncthingMonitorMachine.ts`
- `src/controllers/syncthingMonitorMachine.test.ts`
- `src/controllers/syncthingMonitor.activity.test.ts`
- `src/controllers/gameLifecycleDecision.test.ts`

1. Add RED state-machine tests for a post-game watch that observes upload before the
   backup handoff, then receives at least three settled samples before the handoff.
   Assert it retains `latestStatus=uploading`, does not set `completionObserved`, and
   does not publish or stop as complete before `handoff_confirmed`.
2. After `handoff_confirmed`, require three new distinct settled samples. Assert the
   handoff outcome is uploading, the lifecycle decision publishes
   `syncthing_uploading`, the first two post-handoff settled samples retain uploading,
   and the third publishes `syncthing_complete` and stops the watch. This is the visible
   minimum dwell; do not add another BrowserView timer.
3. Add the parallel fast-sync case where a local/index mutation was observed but no
   outbound evidence was caught. It must remain pending before handoff and may complete
   only after three post-handoff settled samples. Preserve the existing detection-grace
   fallback if no mutation is ever observed.
4. Prove pre-game settlement, duplicate timestamp suppression, rank monotonicity,
   concurrent upload/download direction, cancellation, failure mapping, and generation
   ownership remain unchanged.
5. Prove RED with:

   ```bash
   ./run.sh pnpm exec vitest run src/controllers/syncthingMonitorMachine.test.ts src/controllers/syncthingMonitor.activity.test.ts src/controllers/gameLifecycleDecision.test.ts
   ```

6. Implement the smallest state-machine change: post-game settled samples may advance
   completion only after `handoffActivated` is true. Do not change backend/frontend RPC
   types or status-surface code. Refactor, rerun the focused suite and quality gates,
   then commit only this unit:

   ```bash
   git add src/controllers/syncthingMonitorMachine.ts src/controllers/syncthingMonitorMachine.test.ts src/controllers/syncthingMonitor.activity.test.ts src/controllers/gameLifecycleDecision.test.ts
   git commit -m "fix(autosync): preserve uploading through backup handoff"
   ```

Mark the round finished and exit. Task 4 is forbidden until its review note authorizes
it.

### Task 4 — Document the contract and record verification

**Authorized only by a committed review note accepting Task 3. Stop for final review
after this task.**

Files in scope:

- `README.md`
- `DEVELOPMENT.md`
- `docs/specs/sdh_ludusavi_sync.md`
- `docs/specs/custom_status_bar_ui.md`
- `docs/agent_conversations/2026-08-09_syncthing-peer-completion-upload-status.json`

1. Update user-facing status definitions. Post-game UPLOADING is sustained by
   watched-folder peer completion/need evidence, and post-game COMPLETE means the Deck
   is locally settled plus every currently connected relevant peer has reported no
   outstanding need after the local index mutation. State explicitly that
   disconnected/offline configured peers are not covered and that pre-game settlement
   retains its local/incoming launch-gate semantics.
2. Update developer/spec documentation to describe the REST baseline, filtered
   `FolderCompletion` reducer, freshness rule, 2.5-second observation hold,
   post-handoff three-sample completion gate, count-only diagnostics, and why
   `RemoteDownloadProgress` remains supplemental rather than authoritative.
3. Correct the old specification language that says device membership never contributes
   to remote acknowledgement and that COMPLETE is local-only. Preserve the
   connection-counters-are-not-activity invariant.
4. Add the required JSON session record with the date, objective, files modified, each
   task's RED proof, design decisions, Task 1-3 commit hashes, the Task 4 commit subject,
   review-note paths available through Task 3, exact focused/full validation results,
   the live viability evidence above, and explicitly deferred post-release Steam Deck
   verification. Do not attempt a self-referential Task 4 hash; its final review note
   and Git history are the durable record of that commit.
5. Run documentation/static tests and then the full quality gates:

   ```bash
   ./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py
   ```

6. Commit only this unit:

   ```bash
   git add README.md DEVELOPMENT.md docs/specs/sdh_ludusavi_sync.md docs/specs/custom_status_bar_ui.md docs/agent_conversations/2026-08-09_syncthing-peer-completion-upload-status.json
   git commit -m "docs(syncthing): define peer completion status"
   ```

Mark the round finished and exit. The orchestrator must perform final review; the
implementer must not self-approve, finalize, deploy, or start another task.

---

## Quality Gates

Run before marking any round complete:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

The round is not complete unless:

1. all requested implementation work is done;
2. all relevant tests pass;
3. build/typecheck gates pass;
4. review notes have not been deleted;
5. the working tree is clean;
6. all code/docs changes are committed.

The shared checkout already contains the user-owned untracked
`docs/issues-to-import.md`. For this plan, "clean" means
`git status --short --untracked-files=no` is empty and the only full-status entry is
that exact pre-existing file. Any other tracked or untracked entry fails the gate. Do
not move, ignore, stage, edit, or commit the user-owned file merely to make the display
empty.

---

## Verification

### Automated acceptance

Run every command independently and require a zero exit status:

```bash
./run.sh uv run pytest tests/test__types.py tests/test_activity.py tests/test_syncthing.py tests/test_watcher.py
./run.sh pnpm exec vitest run src/controllers/syncthingMonitorMachine.test.ts src/controllers/syncthingMonitor.activity.test.ts src/controllers/gameLifecycleDecision.test.ts
./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git diff --check
git status --short --untracked-files=no
git status --short
```

Expected final `git status --short --untracked-files=no` output is empty. Expected full
`git status --short` output is exactly `?? docs/issues-to-import.md` if the orchestration
checkout retains the pre-existing user file, or empty if an isolated checkout does not
contain it. Record the observed case explicitly; any other output fails verification.

### Required negative controls

1. Temporarily make the production `FolderCompletion` incompleteness predicate return
   false, run the focused backend test that replays the 93.56% peer lag, and require that
   test to fail because uploading is no longer sustained. Immediately restore the exact
   one-line mutation with an inverse edit and rerun the focused test green.
2. Temporarily remove the `handoffActivated` guard from the production post-game settle
   branch, run the focused pre-handoff-completion test, and require it to fail. Restore
   the guard with an inverse edit and rerun the test green.
3. Feed the same incomplete `FolderCompletion` payload under an unrelated folder ID and
   an unconfigured device ID. Both controls must remain idle/settled for the watched
   folder, demonstrating that the positive replay is not satisfied by unscoped traffic.
4. Do not use `|| true`, masked pipelines, broad test-name filters, or a test-only code
   path. Record the exact failing assertion and restored passing command in the session
   record.

### Deferred Steam Deck acceptance

The planning-time read-only event replay already established viability on the available
Steam Deck, but no test file was written and no plugin build was installed. On-device UI
acceptance is deferred until final approval merges to `dev` and the existing finalization
hook requests a development prerelease. Do not publish a stable release or push a tag.

After that development prerelease is installed on `steamdeck`:

1. Enable debug logging, start and exit a game whose backup changes enough to sustain a
   peer transfer, and keep at least one device sharing the backup folder connected.
2. Observe the required visible order:
   `BACKING UP LOCAL SAVE -> GAME SAVE UP TO DATE -> SYNCTHING PREPARING -> SYNCTHING UPLOADING -> SYNCTHING COMPLETE`.
3. Repeat with a very small change. UPLOADING must still appear before COMPLETE; the
   post-handoff three-sample gate should keep it visible even if all peer completion
   reports reached 100% during the backup.
4. Pull only fresh logs into `/tmp/sdh_ludusavi/steamdeck/logs`:

   ```bash
   ./run.sh uv run python scripts/pull_plugin_logs.py --host steamdeck
   ./run.sh uv run python scripts/analyze_plugin_logs.py --strict /tmp/sdh_ludusavi/steamdeck/logs
   ```

5. Confirm the transition diagnostics show connected/incomplete/awaiting peer counts and
   aggregate need values changing to zero, contain no raw device IDs or response JSON,
   and align with the UPLOADING and COMPLETE status timestamps.
6. Disconnect every relevant peer and repeat an exit. Preserve the successful local
   backup and show `LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE`; do not claim upload
   or completion. Reconnect afterward so Syncthing can propagate the saved data.

Do not block code finalization on this deferred hardware check, because the development
prerelease is created by finalization. Record its pending state in the session log and
perform it as the explicit post-release acceptance follow-up.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-peer-completion-upload-status
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-peer-completion-upload-status_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-peer-completion-upload-status`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-peer-completion-upload-status-review-*.md
```

When a review note exists or a new review note appears:

1. Read the full review note.
2. If the note ends with:

   ```text
   STATUS: CHANGES_REQUESTED
   ```

   then resume work.

3. Clear the round-complete marker:

   ```bash
   scripts/orchestration/clear-finished syncthing-peer-completion-upload-status
   ```

4. Address every requested change.
5. Run quality gates:

   ```bash
   scripts/orchestration/run-quality-gates
   scripts/orchestration/check-review-notes-not-deleted
   ```

6. Commit code/docs fixes.
7. Commit the review-note file itself if it is not already committed:

   ```bash
   git add docs/review/syncthing-peer-completion-upload-status-review-*.md
   git commit -m "docs(review): record syncthing-peer-completion-upload-status review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-peer-completion-upload-status
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-peer-completion-upload-status` after the next review note is created.

---

## Approval Handling

If the latest review note ends with:

```text
STATUS: APPROVED
```

then:

1. Confirm every previous review item has been addressed.
2. Confirm all review notes are committed:

   ```bash
   scripts/orchestration/check-review-notes-committed syncthing-peer-completion-upload-status
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-peer-completion-upload-status
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-peer-completion-upload-status_finalized
   ```

6. Stop polling and exit cleanly.

---

## Review Rules

Do not write your own review.

Do not create files under:

```text
docs/review/
```

Do not delete files under:

```text
docs/review/
```

Only the orchestrator writes review notes. Your job is to read them, resolve them, commit them as audit records, and continue the loop.

---

## Finalization Rules

Only finalize after a review note with:

```text
STATUS: APPROVED
```

Finalization is performed with:

```bash
scripts/orchestration/finalize syncthing-peer-completion-upload-status
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-peer-completion-upload-status_finished
/tmp/sdh_ludusavi/syncthing-peer-completion-upload-status_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
