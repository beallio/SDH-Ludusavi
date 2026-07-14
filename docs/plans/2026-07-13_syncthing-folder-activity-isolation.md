# Plan: Isolate Syncthing BrowserView Activity by Folder (syncthing-folder-activity-isolation)

## Context

### Problem Definition

The autosync BrowserView is intended to report activity for the Syncthing folder that
contains Ludusavi's configured backup root. Folder-tagged Syncthing database state and
events are already filtered to that resolved folder, but
`py_modules/sdh_ludusavi/syncthing/activity.py::get_connection_snapshot()` also reads
the aggregate `total.inBytesTotal` and `total.outBytesTotal` values from
`/rest/system/connections`. `SyncthingWatch` converts those device-wide totals into
rates, and `compute_activity_status()` may classify a recent watched-folder mutation as
downloading or uploading when the bytes actually belong to another Syncthing folder.
This remains possible when both folders are shared with the same remote device because
Syncthing multiplexes all of that device's folders over the same connection.

Remove connection-byte totals from activity classification. Separate-folder traffic
must never publish `SYNCTHING DOWNLOADING`, `SYNCTHING UPLOADING`, delay
`SYNCTHING COMPLETE`, or otherwise keep the BrowserView active. Preserve the existing
relevant-peer connectivity guard and derive transfer direction only from state or
events explicitly associated with the resolved backup folder.

### Architecture Overview

- `SDHLudusaviService.start_syncthing_activity_watch()` continues to obtain Ludusavi's
  configured `backupPath` and `SyncthingWatchManager.start_watch()` continues to select
  the deepest Syncthing folder containing that path.
- `/rest/system/connections` remains a connectivity source only. The watcher continues
  intersecting connected device IDs with `FolderSelection.device_ids` so it can reject
  or stop a watch when every peer configured for the backup folder is offline.
- Folder activity remains authoritative:
  - `/rest/db/status?folder=<folder-id>` supplies watched-folder state and need counters;
  - `DownloadProgress` is read only from the payload entry keyed by the watched folder;
  - `RemoteDownloadProgress`, `StateChanged`, `FolderSummary`, scan, item, and index
    events are accepted only when their `folder` equals the watched folder ID.
- `compute_activity_status()` must not accept or consult aggregate connection rates.
  Incoming transfer evidence is watched-folder syncing/download/item state. Outgoing
  transfer evidence is non-empty `RemoteDownloadProgress` for the watched folder.
  Folder-specific scan/index/need signals may keep `update_in_progress` true without
  inventing a transfer direction.
- The RPC sample and frontend state-machine contracts remain unchanged. BrowserView
  isolation is enforced before serialization, so `src/controllers/syncthingMonitor.ts`
  and `src/controllers/syncthingMonitorMachine.ts` continue consuming the same
  `status`, `folder_state`, `update_in_progress`, `settled`, `downloading`,
  `uploading`, and `timestamp_unix` fields.

Syncthing's documented connection counters are global/per-device rather than
per-folder. Do not attempt to sum counters for the backup folder's peers: that still
mixes folders shared with the same device. Use the existing folder-tagged event and
database APIs instead:

- https://docs.syncthing.net/rest/system-connections-get.html
- https://docs.syncthing.net/events/downloadprogress.html
- https://docs.syncthing.net/v1.0.0/events/remotedownloadprogress.html
- https://docs.syncthing.net/rest/db-status-get.html

### Core Data Structures

- Simplify `ConnectionSnapshot` to the connected-device set needed by peer
  availability checks. Remove `in_bytes_total` and `out_bytes_total` if no remaining
  caller needs them.
- Remove the internal `ConnectionRates` data structure and the corresponding
  `rates`, `aggregate_downloading`, and `aggregate_uploading` fields from
  `ActivityStatus`; none are part of the frontend RPC sample.
- Keep `FolderRuntime`, `LocalActivity`, `RemoteProgress`, `FolderSelection`, and the
  serialized `SyncthingActivitySample` shape stable except for internal constructor or
  function-signature adjustments needed after deleting rate state.

### Public Interfaces

No public RPC, persisted setting, or frontend wire-format change is allowed. Keep:

- `start_syncthing_activity_watch(phase, game_name?, app_id?)`;
- `get_syncthing_activity(watch_id)`;
- `stop_syncthing_activity_watch(watch_id)`;
- the existing start-watch result and activity-sample keys;
- existing BrowserView status names, copy, icons, timing, ownership, and lifecycle
  precedence.

### Dependency Requirements

No Python, JavaScript, system, or Syncthing dependency changes are required. Do not add
new polling endpoints merely to replace connection rates. The existing folder status
and event stream are sufficient for this isolation fix.

### Scope and Acceptance Boundaries

- This change isolates distinct Syncthing folder IDs, including distinct folders shared
  with the same remote device.
- It does not add per-game or per-file filtering inside the resolved Ludusavi backup
  folder. Activity elsewhere in that same Syncthing folder remains in scope for the
  BrowserView.
- Preserve pre-game/post-game watch ownership, detection grace, 120-second frontend
  duration, 180-second backend TTL, connected-peer handling, cancellation, handoff,
  settlement, and error behavior.
- Do not change release versions, tags, packaging, or release workflows as an
  implementation task. Any later release is owned by the generated orchestration
  finalization flow after explicit execution and approval.

**Slug used throughout this plan:** `syncthing-folder-activity-isolation`

---

## Orchestration Contract

**Slug:** `syncthing-folder-activity-isolation`

**Plan file:**

```text
docs/plans/2026-07-13_syncthing-folder-activity-isolation.md
```

**Implementation branch:**

```text
feat/syncthing-folder-activity-isolation
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-folder-activity-isolation_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-folder-activity-isolation_finalized
```

**Review notes:**

```text
docs/review/syncthing-folder-activity-isolation-review-*.md
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
git checkout -b feat/syncthing-folder-activity-isolation
```

Commit this plan first:

```bash
git add docs/plans/2026-07-13_syncthing-folder-activity-isolation.md
git commit -m "docs(plan): add syncthing-folder-activity-isolation implementation plan"
```

---

## Implementation Tasks

### 1. Establish the regression fence first (RED)

Add focused tests before changing runtime code.

1. In `tests/test_activity.py`, add a failing classification test that gives the
   watched folder a recent local/index/sequence mutation and supplies connection-rate
   traffic in both directions, but supplies no watched-folder download state,
   `DownloadProgress`, active item, or `RemoteDownloadProgress`. Assert:
   - `downloading is False`;
   - `uploading is False`;
   - aggregate traffic alone cannot make the status `ACTIVE_TRANSFER`.
   This must fail against the current rate fallback before implementation.
2. Add `process_event()` isolation coverage using two folder IDs and the same device
   ID. Feed `RemoteDownloadProgress`, `StateChanged`, `FolderSummary`,
   `FolderScanProgress`, `ItemStarted`, `ItemFinished`, `LocalChangeDetected`, and
   `LocalIndexUpdated` events for the unrelated folder and assert that none mutate the
   watched folder's state, runtime, remote progress, or local activity.
3. Add `DownloadProgress` coverage proving that an entry for only the unrelated folder
   neither starts nor clears the watched folder's active downloads, while a watched
   folder entry does start them and the documented final empty payload clears them.
4. Add positive controls proving watched-folder `DownloadProgress` still yields
   downloading and watched-folder `RemoteDownloadProgress` still yields uploading,
   including when the event's device also shares the unrelated folder.
5. Run the focused RED command and preserve its expected assertion failure in the
   implementation/session record:

   ```bash
   ./run.sh uv run pytest tests/test_activity.py tests/test_syncthing.py
   ```

Do not weaken existing expected behavior to manufacture the RED result.

### 2. Make connection polling connectivity-only (GREEN)

Update `py_modules/sdh_ludusavi/syncthing/activity.py`, `_types.py`, and `watcher.py`:

1. Change `get_connection_snapshot()` to validate the response and return only the set
   of connected devices. It must continue rejecting a missing/non-object
   `connections` map and must keep device IDs out of exceptions, logs, and RPCs.
2. Remove `get_connection_totals()`, `compute_rates()`, `ConnectionRates`,
   `DEFAULT_MIN_RATE_BYTES_PER_SECOND`, and connection-total fields that become unused.
   Confirm with `rg` that no production caller or compatibility export remains before
   deleting each symbol.
3. Rename `_tick_connections()` to `_tick_connectivity()` if that makes its narrowed
   responsibility clearer. It must update `connected_devices`, preserve the last known
   set when the endpoint fails, and retain the existing terminal
   `no_connected_peers` behavior for devices configured on the watched folder.
4. Remove per-watch previous-total timestamps and rate state. Do not replace them with
   per-device counters because a device connection can carry multiple folders.
5. Update constructor usage and focused tests mechanically for the narrowed
   `ConnectionSnapshot`. Preserve keyword construction where it makes the connected
   device meaning explicit.

### 3. Make activity direction exclusively folder-derived

Refactor `compute_activity_status()` and its callers:

1. Remove rate and minimum-rate parameters plus aggregate fields from the internal
   result.
2. Compute `downloading` only from watched-folder evidence already held by the watch:
   folder state `syncing`, a positive watched-folder `active_download_files`, or active
   watched-folder items.
3. Compute `uploading` only from non-empty, non-expired `RemoteProgress` created by a
   `RemoteDownloadProgress` event whose `folder` matches the watch.
4. Keep scan, local-change, local-index, sequence-change, need counters, item-finished
   grace, preparing states, and error states in `update_in_progress` and status
   selection. These folder-scoped signals may represent preparation/indexing without
   claiming upload or download.
5. Preserve `settled` as an idle watched folder with no update, download, remote
   progress, pull error, or watch error. Separate-folder activity must neither reset
   the local activity window nor postpone the three-sample frontend completion rule.
6. Keep `_serialize_sample()` and `src/types/index.ts::SyncthingActivitySample`
   unchanged. Run the backend sample-shape and watcher timing tests to prove the wire
   contract remains stable.

### 4. Prove watcher-level isolation and preserve peer behavior

Extend `tests/test_watcher.py` and adjust existing tests only where internal rate types
or snapshot constructors were deliberately removed:

1. Drive a `SyncthingWatch` tick with high/changing connection totals in the mocked
   endpoint plus events for a different folder sharing the same connected device.
   Assert the serialized sample does not set `uploading`, `downloading`, or an active
   transfer-derived status for the watched folder.
2. In the same test family, feed watched-folder download and remote-download progress
   and assert the serialized booleans still change correctly.
3. Retain coverage that unrelated connected devices do not satisfy peer availability,
   one relevant connected peer permits the watch, loss of the final relevant peer
   terminates it, and transient connection endpoint failures retain the last known
   peer set.
4. Preserve watch initialization, cursor ordering, TTL, replacement, stop, unload, and
   copied-sample behavior.

### 5. Preserve the frontend and BrowserView contract

The frontend should require no production-code change because folder isolation occurs
in the backend sample producer. Confirm with existing Vitest coverage that:

- an idle sample with `uploading=false`, `downloading=false`, and no update publishes
  no Syncthing transfer status;
- watched-folder upload/download samples still map to their current BrowserView status;
- post-game pending, monotonic upload/complete progression, three settled samples,
  handoff timing, cancellation, and failure precedence remain unchanged.

If a frontend test is missing for the first invariant, add it to
`src/controllers/syncthingMonitorMachine.test.ts`; do not add folder IDs or paths to the
frontend activity sample merely for testing.

### 6. Update durable documentation and record the session

1. Update `README.md` status documentation to state that Syncthing activity reflects
   the Syncthing folder containing Ludusavi's backup path and that traffic from other
   Syncthing folders is excluded even when the same peer shares them.
2. Update `docs/specs/custom_status_bar_ui.md` with the backend sourcing invariant:
   connection data determines relevant-peer availability only; folder-tagged state and
   events determine BrowserView activity and direction.
3. Update `DEVELOPMENT.md` if needed to document the connectivity-versus-activity API
   boundary for future maintainers.
4. Add `docs/agent_conversations/2026-07-13_syncthing-folder-activity-isolation.json`
   containing the date, objective, files modified, RED tests, design decision, results,
   exact validation commands/results, and any deferred on-device verification.
5. Use atomic Conventional Commits after the plan commit. A suitable implementation
   commit is `fix(syncthing): isolate BrowserView activity by folder`; documentation
   may remain with that coherent fix or use a separate `docs(syncthing): ...` commit.

### 7. Acceptance criteria before round completion

- Global and per-device connection byte counters have no path into `downloading`,
  `uploading`, `active_transfer`, `update_in_progress`, `settled`, or the BrowserView.
- Activity in folder B cannot affect a watch for folder A, including when both folders
  are shared with the same remote device and folder A recently mutated.
- Watched-folder incoming and outgoing evidence still produces the existing status
  booleans and BrowserView transitions.
- Relevant-peer online/offline handling still uses folder-configured device membership.
- The backend RPC sample keys and all frontend public types/status names remain stable.
- No new dependency, setting, RPC, polling endpoint, release change, or per-file/game
  filtering is introduced.
- Tests, documentation, session record, quality gates, review-note integrity, commits,
  and clean-tree checks are complete.

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

---

## Verification

Run focused backend isolation tests during RED/GREEN work:

```bash
./run.sh uv run pytest tests/test_activity.py tests/test_syncthing.py tests/test_watcher.py
```

Run the focused frontend regression suite without changing the wire contract:

```bash
./run.sh pnpm run test:unit -- src/controllers/syncthingMonitorMachine.test.ts src/controllers/syncthingMonitor.activity.test.ts src/controllers/syncthingMonitor.failures.test.ts
```

Run documentation/source consistency checks:

```bash
rg -n "ConnectionRates|compute_rates|get_connection_totals|aggregate_downloading|aggregate_uploading|in_bytes_total|out_bytes_total" py_modules tests
git diff --check
```

The `rg` command must return no production references to removed rate-based activity
symbols; test-only historical wording is allowed only when it explicitly asserts their
absence. Then run the repository's complete gates:

```bash
./run.sh pnpm run verify
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

Expected automated result: frontend tests/build/typecheck, Ruff check/format, `ty`, and
the complete pytest suite pass; review notes are intact; `git diff --check` is clean;
and `git status --short` is empty after commits.

Manual deterministic verification is required with a mocked or local Syncthing API
fixture if practical:

1. Configure folder A as the Ludusavi backup folder and folder B as unrelated, both
   shared with the same remote device.
2. Start a watch for folder A, produce traffic only in folder B, and confirm no
   Syncthing transfer BrowserView state is published for A.
3. Mutate folder A without initiating a folder-A transfer while folder B is actively
   transferring; confirm B's connection bytes do not create an upload/download state
   or postpone A's normal settlement.
4. Produce folder-A download and remote-download progress and confirm the existing
   downloading/uploading states still appear, followed by completion after settlement.

On-device Steam Deck verification is deferred until an environment with two Syncthing
folders, a shared peer, Decky, and Game Mode is available. Record it explicitly as
deferred rather than claiming it passed. Automated mocked-event tests are the required
round-completion evidence; on-device verification must not broaden implementation scope
or block the orchestration review unless a reviewer specifically requests it.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-folder-activity-isolation
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-folder-activity-isolation_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-folder-activity-isolation`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-folder-activity-isolation-review-*.md
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
   scripts/orchestration/clear-finished syncthing-folder-activity-isolation
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
   git add docs/review/syncthing-folder-activity-isolation-review-*.md
   git commit -m "docs(review): record syncthing-folder-activity-isolation review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-folder-activity-isolation
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-folder-activity-isolation` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed syncthing-folder-activity-isolation
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-folder-activity-isolation
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-folder-activity-isolation_finalized
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
scripts/orchestration/finalize syncthing-folder-activity-isolation
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-folder-activity-isolation_finished
/tmp/sdh_ludusavi/syncthing-folder-activity-isolation_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
