# Plan: Fix Syncthing Event Cursor Subscription Mismatch (syncthing-event-cursor-subscription)

## Context

### Problem Definition

The plugin's Syncthing event stream has never delivered a single event in normal
operation. Every signal the watcher appears to detect actually comes from
`_tick_folder_status()` polling `/rest/db/status`.

Syncthing's `/rest/events` returns two identifiers per event: `id`, which is a counter
**private to the subscription that served the request**, and `globalID`, the process-wide
counter. The `since` query parameter is matched against the per-subscription `id`.
Syncthing keys a subscription by its `events=` filter set, so an unfiltered request and a
filtered request are served by two different subscriptions with two unrelated `id`
sequences.

`get_event_cursor()` in `py_modules/sdh_ludusavi/syncthing/activity.py` requests
`/rest/events` **without** an `events=` parameter, so it reads the default (unfiltered)
subscription's counter. `get_events()` requests the same endpoint **with**
`events=EVENT_TYPES`, so it is served by the filtered subscription. The cursor taken from
one is then used as `since` against the other.

Measured on the Legion Go S (`steamdeck-legos`, SteamOS, Syncthing v2.1.2) on
2026-08-09/10, the same event seen through both subscriptions:

```text
default (unfiltered):   id=1177   globalID=1598   FolderCompletion
filtered (plugin):      id=248    globalID=1598   FolderCompletion
```

The unfiltered counter runs far ahead because it receives every event type, including the
`RemoteIndexUpdated` traffic the plugin filters out. Asking the filtered subscription for
`id > 1146` therefore matches nothing until it has accumulated roughly nine hundred more
events, which is hours or days away. `_tick_events()` in
`py_modules/sdh_ludusavi/syncthing/watcher.py` then advances `self.cursor` from
`event["id"]`, so once the two sequences are mixed the watch never recovers.

This was reproduced by running the plugin's own installed modules against the live API:
polling exactly as `_tick_events()` does for 70 seconds, while a 400 KB file was written
into the watched folder, returned **zero events of any type**, even though Syncthing
emitted 31 events above that cursor in the same window, including 12 `FolderCompletion`
and 2 `LocalIndexUpdated`. Seeding the cursor from the filtered subscription instead
(`id=248`) and repeating the run produced the full lifecycle: all three peers tracked,
each moving from `99.78%` with `needBytes=300000` to `100.0` with all need counters zero.

Two consequences follow.

The `syncthing-peer-completion-upload-status` feature merged as `cd50ab9` has never been
exercised. On the 2026-08-09 23:37 device run it held `SYNCTHING UPLOADING` through
`awaiting_fresh_completion=3` — waiting for completion reports that could not arrive —
rather than through `incomplete_peers`, and its count-only diagnostics stayed frozen at
`incomplete_peers=0 needed_bytes=0` for 111 seconds while real outstanding need fell from
8,943,833 bytes to zero. Its verdict was accidentally correct because one peer genuinely
lagged; had all peers converged it would still have hung.

That run then died at the 120-second post-game cap with `watch_duration_timeout`,
publishing `SYNCTHING UNAVAILABLE`. The straggler was at `completion=95` with
`needDeletes=5` and still making progress when monitoring stopped, so the cap is shorter
than real convergence for this workload and the error status misreports a successful but
slow sync.

### Intended Outcome

Both event-driven call sites address one subscription, a subscription reset can no longer
silently kill a live watch, the post-game watch survives as long as peers are measurably
progressing, and a watch that stops while peers are still behind reports that truthfully
instead of as an API failure.

### Relevant Files

```text
py_modules/sdh_ludusavi/syncthing/activity.py     get_event_cursor, get_events
py_modules/sdh_ludusavi/syncthing/watcher.py      _tick_events cursor advance, terminal results
py_modules/sdh_ludusavi/syncthing/_types.py       EVENT_TYPES
src/controllers/syncthingMonitor.ts               MAX_WATCH_DURATION_MS, cap expiry handling
src/controllers/syncthingMonitorMachine.ts        mapSyncthingFailureReason
src/types/index.ts                                AutoSyncStatusKind
src/surfaces/autoSyncStatusRenderer.tsx           status label surface
docs/specs/sdh_ludusavi_sync.md                   RemoteDownloadProgress justification
docs/specs/custom_status_bar_ui.md                activity source description
README.md                                         user-facing status definitions
```

### Decisions Already Made

These were settled with the user before this plan was written. Implement them as stated;
do not re-open them.

- The post-game cap becomes **adaptive**: the watch continues while aggregate outstanding
  need is still falling, bounded by a hard absolute ceiling. The pre-game cap is unchanged.
- A post-game watch that stops while peers remain behind publishes a **distinct non-error
  terminal status**. `SYNCTHING UNAVAILABLE` is reserved for genuine API and
  initialization failures.
- The `RemoteDownloadProgress` justification is **corrected in documentation only**. Peer
  completion remains the authoritative outbound signal; `RemoteDownloadProgress` remains
  supplemental. Do not redesign the classifier.

**Slug used throughout this plan:** `syncthing-event-cursor-subscription`

---

## Orchestration Contract

**Slug:** `syncthing-event-cursor-subscription`

**Plan file:**

```text
docs/plans/2026-08-10_syncthing-event-cursor-subscription.md
```

**Implementation branch:**

```text
feat/syncthing-event-cursor-subscription
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-event-cursor-subscription_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-event-cursor-subscription_finalized
```

**Review notes:**

```text
docs/review/syncthing-event-cursor-subscription-review-*.md
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
git checkout -b feat/syncthing-event-cursor-subscription
```

Commit this plan first:

```bash
git add docs/plans/2026-08-10_syncthing-event-cursor-subscription.md
git commit -m "docs(plan): add syncthing-event-cursor-subscription implementation plan"
```

---

## Atomic task review gate

This plan uses **one implementation task per orchestration round**.

1. The initial round authorizes **Task 1 only**.
2. Complete the authorized task end to end: write its RED tests, record the expected
   failures, implement GREEN, refactor, run that task's focused command and the full
   quality gates, make only that task's atomic Conventional Commit, mark the round
   finished, and exit.
3. Do not begin the next numbered task, prepare its tests, or make opportunistic edits
   while waiting for review.
4. On continuation, read the latest committed review note. If it requests corrections, fix
   only the same task and stop for review again. Advance only when the note states both
   `TASK N: ACCEPTED` and `AUTHORIZED TASK: N+1`.
5. The orchestration engine uses `STATUS: CHANGES_REQUESTED` for every non-final
   continuation. A note that accepts Task N and authorizes Task N+1 therefore still ends in
   `STATUS: CHANGES_REQUESTED`; that trailer is a mechanical resume signal, not a rejection
   of the accepted task.
6. `STATUS: APPROVED` is reserved for human approval after Task 5 and all prior task
   reviews are complete. Never interpret approval of one task as approval of the plan.
7. If a review note is missing, ambiguous, skips a task number, or authorizes more than one
   task, stop without changing files and report the gate violation.

---

## Implementation Tasks

### Task 1 — Seed the event cursor from the filtered subscription

**Initially authorized. Stop for review after this task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/activity.py
tests/test_activity.py
```

1. Write failing tests first. Using a mock API that records every call, assert that
   `get_event_cursor()` sends an `events` parameter and that its value is **identical** to
   the one `get_events()` sends. Assert equality against the recorded parameters of both
   calls, not against a literal copy of `EVENT_TYPES` — a test that hardcodes the string
   passes even if the two call sites later diverge, which is the exact defect being fixed.
2. Add a test proving the cursor is taken from the filtered response: given a mock whose
   filtered response carries `id` values far below the `globalID` values, assert the
   returned cursor equals the maximum `id`, not the maximum `globalID`.
3. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_activity.py -q --no-cov
   ```

4. Change `get_event_cursor()` to send `events=EVENT_TYPES` alongside its existing
   `since`, `limit`, and `timeout` parameters, so both call sites address one subscription.
5. Add a comment at `get_event_cursor()` recording *why* the filter is required: Syncthing
   scopes `id` to the subscription selected by the `events=` filter and matches `since`
   against that scoped `id`, while `globalID` is the process-wide counter. Without this
   note the parameter reads as redundant and invites removal.
6. Preserve the existing non-list response guard and its test.
7. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/activity.py tests/test_activity.py
   git commit -m "fix(syncthing): seed event cursor from the filtered subscription"
   ```

Run `scripts/orchestration/mark-finished syncthing-event-cursor-subscription` and exit.
Task 2 is forbidden until a review note authorizes it.

### Task 2 — Guard against subscription resets

**Authorized only by a committed review note accepting Task 1. Stop for review after this
task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_watcher.py
```

Syncthing discards idle subscriptions. A recreated subscription restarts its `id` sequence
at 1, so a cursor held from the previous subscription sits above every new `id` and the
stream goes silent exactly as in Task 1 — but mid-watch, where re-seeding at watch start
cannot help.

1. Write failing tests first. Drive `_tick_events()` with a mocked `get_events` that
   returns a batch whose `id` values are **lower** than the watch's current cursor, and
   assert that the watch treats this as a reset: the events are processed rather than
   discarded, and the cursor afterwards equals the highest `id` in that batch rather than
   the stale higher value.
2. Add a test proving normal forward motion is unaffected: a batch with `id` values above
   the cursor still advances the cursor monotonically to the batch maximum.
3. Add a test proving the reset is logged once at INFO with no device IDs, folder paths, or
   raw payloads in the record.
4. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_watcher.py -q --no-cov
   ```

5. Implement the guard in `_tick_events()`. Detect a returned `id` below the current cursor,
   re-seed the cursor from the batch rather than skipping it, and keep the existing
   `max()` advance for the normal case. Do not add a polling loop or a second REST call.
6. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_watcher.py
   git commit -m "fix(syncthing): re-seed the cursor when a subscription resets"
   ```

Run `scripts/orchestration/mark-finished syncthing-event-cursor-subscription` and exit.
Task 3 is forbidden until a review note authorizes it.

### Task 3 — Stop a stalled post-game watch with a truthful reason

**Authorized only by a committed review note accepting Task 2. Stop for review after this
task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/_types.py
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_watcher.py
```

The frontend sample exposes exactly `status`, `folder_state`, `update_in_progress`,
`settled`, `downloading`, `uploading`, and `timestamp_unix`, and tests pin that key set.
The need counters therefore exist only in the backend, so progress-based stall detection
must live in the watcher. Publish it through the existing terminal-result shape
(`{"status": "failed", "reason": ..., "message": ...}`) used by `no_connected_peers`. Do
**not** add a field to the sample.

1. Write failing tests first, driving `_tick()` with mocked peer completions:
   - aggregate outstanding need falling across successive ticks keeps the watch alive well
     past the stall window;
   - aggregate outstanding need unchanged for longer than the stall window stops the watch
     terminally with the new reason and a message containing no device IDs, counts, folder
     paths, or raw payloads;
   - a post-game watch whose peers all reach complete and fresh settles normally and does
     **not** emit the terminal reason;
   - a pre-game watch never emits the terminal reason regardless of peer state.
2. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_watcher.py -q --no-cov
   ```

3. Add two constants to `_types.py` with comments explaining the chosen values:
   an outbound stall window, and a hard absolute ceiling for a post-game watch. Choose a
   stall window longer than the observed straggler gap — on 2026-08-09 a peer held
   `needDeletes=12` unchanged for roughly sixty seconds while still genuinely progressing —
   and state that reasoning in the comment.
4. Track aggregate outstanding need across connected relevant peers and the monotonic time
   it last decreased. Reuse the predicate extracted in whatever form the code already has;
   if `compute_activity_status()` and `_log_peer_completion_transition()` still compute the
   incomplete/awaiting conditions independently, extract that predicate to one function and
   call it from all three sites rather than adding a fourth copy.
5. Stop the watch terminally when a post-game watch is outbound-incomplete and aggregate
   need has not decreased within the stall window, or when the absolute ceiling is reached.
   Use a new reason string; keep the message generic and free of identifiers.
6. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/_types.py py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_watcher.py
   git commit -m "feat(syncthing): stop a stalled post-game watch with a truthful reason"
   ```

Run `scripts/orchestration/mark-finished syncthing-event-cursor-subscription` and exit.
Task 4 is forbidden until a review note authorizes it.

### Task 4 — Split the watch caps and surface the new terminal status

**Authorized only by a committed review note accepting Task 3. Stop for review after this
task.**

Files in scope:

```text
src/types/index.ts
src/controllers/syncthingMonitor.ts
src/controllers/syncthingMonitorMachine.ts
src/surfaces/autoSyncStatusRenderer.tsx
src/controllers/syncthingMonitor.failures.test.ts
src/controllers/syncthingMonitorMachine.test.ts
```

`MAX_WATCH_DURATION_MS` is currently one constant serving both phases via
`PRE_GAME_QUIESCENCE_TIMEOUT_MS`. Post-game measures from `handoffActivatedAt`; pre-game
from `startedAt`.

1. Write failing tests first:
   - the pre-game quiescence timeout keeps its current value and current behavior;
   - a post-game watch is still polling after the old 120-second point, up to the new
     post-game ceiling;
   - the backend's new terminal reason from Task 3 maps to the new status kind through
     `mapSyncthingFailureReason` and publishes it;
   - a post-game watch reaching the frontend ceiling publishes the new status kind, not
     `syncthing_unavailable`;
   - `syncthing_unavailable` is still published for genuine initialization and API
     failures.
2. Record the observed failures before editing production code:

   ```bash
   ./run.sh pnpm exec vitest run src/controllers/syncthingMonitor.failures.test.ts src/controllers/syncthingMonitorMachine.test.ts
   ```

3. Split the constant so pre-game keeps 120 seconds and post-game gets its own, larger
   ceiling. The backend owns stall detection after Task 3, so the frontend ceiling is a
   backstop against a hung backend rather than the primary limit; say so in a comment.
4. Add the new kind to `AutoSyncStatusKind`, map the backend reason to it in
   `mapSyncthingFailureReason`, and render it in `autoSyncStatusRenderer.tsx` with wording
   that reads as an outcome rather than an error. Decide deliberately whether it belongs in
   `ACTIONABLE_UNAVAILABLE_REASONS` and record the reasoning in the session log.
5. Do not change the RPC sample key set and do not add a frontend polling loop.
6. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add src/types/index.ts src/controllers/syncthingMonitor.ts src/controllers/syncthingMonitorMachine.ts src/surfaces/autoSyncStatusRenderer.tsx src/controllers/syncthingMonitor.failures.test.ts src/controllers/syncthingMonitorMachine.test.ts
   git commit -m "feat(autosync): split watch caps and surface incomplete upload status"
   ```

Run `scripts/orchestration/mark-finished syncthing-event-cursor-subscription` and exit.
Task 5 is forbidden until a review note authorizes it.

### Task 5 — Correct the documentation and record verification

**Authorized only by a committed review note accepting Task 4. Stop for final review after
this task.**

Files in scope:

```text
README.md
docs/specs/sdh_ludusavi_sync.md
docs/specs/custom_status_bar_ui.md
docs/agent_conversations/2026-08-10_syncthing-event-cursor-subscription.json
```

1. Correct the `RemoteDownloadProgress` justification. The specs currently argue it is not
   a durable sender-side signal because it was absent from a captured log. That reasoning
   is unsound: the plugin was receiving no events at all, so the absence proves nothing
   about that event type. Replace it with the real reason peer completion is authoritative
   — it is need-based and survives the gaps between transient block requests, and the
   2026-08-09 capture showed a peer outstanding on `needDeletes` alone with zero bytes
   pending, which a block-request signal cannot express. Keep `RemoteDownloadProgress`
   supplemental; do not redesign the classifier.
2. Document the subscription-scoped `id` versus process-wide `globalID` distinction in the
   developer spec, including that `since` matches the scoped `id` and that any new
   `/rest/events` call site must use the same filter as the others.
3. Document the stall window, the post-game ceiling, and the new terminal status in both
   specs, and add the user-facing wording for the new status to `README.md`.
4. Write the JSON session record with the date, objective, files modified, each task's RED
   proof, design decisions, the Task 1-4 commit hashes, the Task 5 commit subject, the
   review-note paths available through Task 4, exact focused and full validation results,
   and the deferred device verification named below. Do not attempt a self-referential
   Task 5 hash.
5. Run the documentation and static suites, then the full quality gates:

   ```bash
   ./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py -q --no-cov
   ```

6. Commit only this unit:

   ```bash
   git add README.md docs/specs/sdh_ludusavi_sync.md docs/specs/custom_status_bar_ui.md docs/agent_conversations/2026-08-10_syncthing-event-cursor-subscription.json
   git commit -m "docs(syncthing): correct event subscription and upload status contract"
   ```

Mark the round finished and exit. The orchestrator performs final review; do not
self-approve, finalize, deploy, or start another task.

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

Every step below must be able to fail. Before adding any step of your own, apply
`references/verification-standards.md` from the `orchestration-plan-author` skill: ask what
state of the world makes it print the failure output, and delete it if the answer is
"none".

Record actual output — pass/fail tallies, received event types, counter values — not the
conclusion that something passed.

### 1. Automated acceptance

Run the full gates and record the tallies:

```bash
scripts/orchestration/run-quality-gates
```

Record the frontend test count, the pytest count, and the coverage percentage. A drop in
either count against the previous round's recorded numbers is a failure to investigate, not
a rounding difference.

### 2. Prove the Task 1 gate by mutation

The Task 1 tests exist to catch the two call sites diverging. Prove they actually do.

With Task 1 complete and green, delete the `events` parameter from `get_event_cursor()`,
then run:

```bash
./run.sh uv run pytest tests/test_activity.py -q --no-cov
```

Expected: the filter-equality test **fails**. Record the failing test name and the
assertion output. If it passes, the test is decoration — rewrite it so it compares the
recorded parameters of the two calls, then repeat this step before continuing.

Restore the parameter and confirm the suite returns to green before moving on.

### 3. Prove the Task 2 guard by mutation

With Task 2 complete and green, remove the reset branch from `_tick_events()` so a batch of
lower `id` values is discarded again, then run:

```bash
./run.sh uv run pytest tests/test_watcher.py -q --no-cov
```

Expected: the reset test **fails**. Record the failing test name. Restore the branch and
confirm green.

### 4. Negative control — live event flow on device

This is the only step that proves the defect is actually fixed, and it must run **after**
steps 2 and 3. A green unit suite does not demonstrate that events reach the watcher; that
was true before this plan and the stream was dead.

Preconditions. If either fails, stop and report — an unreachable device is a blocked
verification, not a passed one:

```bash
ssh -q -o BatchMode=yes -o ConnectTimeout=5 steamdeck-legos true
ssh steamdeck-legos "grep -c . /home/deck/.var/app/com.github.zocker_160.SyncThingy/.local/state/syncthing/config.xml"
```

Install the branch build on the device before probing, so the probe exercises this branch's
code rather than the merged `cd50ab9` build:

```bash
./run.sh uv run python scripts/package_plugin.py
scp ./out/SDH-Ludusavi.zip steamdeck-legos:/home/deck/Downloads/
```

Installing into `/home/deck/homebrew/plugins` needs root on the device and cannot be done
non-interactively. Ask the user to install and restart the loader, then confirm the running
version before probing:

```bash
ssh steamdeck-legos "grep '\"version\"' /home/deck/homebrew/plugins/SDH-Ludusavi/plugin.json"
```

The reported version must contain this branch's short SHA. If it still shows `cd50ab9` or a
`-dev.` build, the probe would measure the old code — stop and report.

Then run the probe. Pass it over stdin with a quoted heredoc so no script file is left on
the device and nothing expands in your local shell:

```bash
ssh steamdeck-legos 'PYTHONPATH=/home/deck/homebrew/plugins/SDH-Ludusavi/py_modules python3 -' <<'PROBE'
<probe script>
PROBE
```

The probe must, in this order:

1. read the GUI block of
   `/home/deck/.var/app/com.github.zocker_160.SyncThingy/.local/state/syncthing/config.xml`
   and extract the API key and address from **within** that block — a bare
   `<address>` search matches a device address earlier in the file and yields an
   unresolvable host;
2. never print the API key;
3. build a `FolderSelection` for the backup folder with `device_ids` set to the folder's
   configured devices **excluding** `myID` from `/rest/system/status`;
4. seed the cursor with the plugin's own `get_event_cursor()`;
5. write a throwaway file of a few hundred KB into `/home/deck/ludusavi-backup/`;
6. poll `get_events()` and feed every event through `process_event()` with
   `peer_completion_tracking=True` for 60 seconds;
7. print the cumulative event-type tally and the `peer_completions` contents on every batch;
8. delete the throwaway file before exiting.

Pass condition, all three required:

```text
FolderCompletion count > 0
len(peer_completions) == number of connected relevant peers
at least one peer observed with need counters > 0, then later 100.0 with all counters 0
```

Failure output to expect if the fix regressed: an empty tally and `peer_completions=0`,
exactly as reproduced on 2026-08-09 — 70 seconds of polling returning zero events of any
type while Syncthing emitted 31 above the cursor.

Confirm the throwaway file is gone afterwards. Absence of the cleanup check is not proof of
cleanup:

```bash
ssh steamdeck-legos 'find /home/deck/ludusavi-backup -maxdepth 1 -name "*probe*" | wc -l'
```

Expected output is exactly `0`, and report the number you saw. `wc -l` always exits zero
and prints a count, so a non-zero exit here means the ssh itself failed and the check did
not run — that is a blocked verification, not a pass. Do not substitute `grep -c`: it exits
1 when there are no matches, which is precisely the passing case, so under `set -e` the
successful outcome would read as a failure.

### 5. Deferred and explicitly not verified

State these in the session log rather than leaving them implied.

- **A real post-game game-exit run is deferred.** The probe above exercises the event
  pipeline but not the full lifecycle through `handoff_confirmed`, the three-settled-sample
  quorum, and the status strip. That needs a game played and exited on the device, and it
  is deferred to after a development prerelease. The expected sequence to confirm then is
  `BACKING UP LOCAL SAVE` → `GAME SAVE UP TO DATE` → `SYNCTHING UPLOADING` sustained with
  the count-only diagnostics moving → `SYNCTHING COMPLETE`.
- **The stall window and post-game ceiling are calibrated from a single observation** —
  the 2026-08-09 capture where one peer held `needDeletes=12` unchanged for roughly sixty
  seconds while still progressing. They are judgement calls, not measurements from a
  sample. Record the values chosen and the reasoning so a later run can revise them.
- **The new terminal status has not been seen on device.** Reaching it requires a peer that
  genuinely stalls, which cannot be produced on demand without disconnecting a peer
  mid-sync. Its unit coverage is real; its on-device appearance is untested.
- **`RemoteDownloadProgress` behavior remains unmeasured.** This plan corrects the
  documented justification only. Whether that event alone would have sufficed is still
  unknown, because it has never been received either.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-event-cursor-subscription
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-event-cursor-subscription_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-event-cursor-subscription`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-event-cursor-subscription-review-*.md
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
   scripts/orchestration/clear-finished syncthing-event-cursor-subscription
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
   git add docs/review/syncthing-event-cursor-subscription-review-*.md
   git commit -m "docs(review): record syncthing-event-cursor-subscription review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-event-cursor-subscription
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-event-cursor-subscription` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed syncthing-event-cursor-subscription
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-event-cursor-subscription
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-event-cursor-subscription_finalized
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
scripts/orchestration/finalize syncthing-event-cursor-subscription
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-event-cursor-subscription_finished
/tmp/sdh_ludusavi/syncthing-event-cursor-subscription_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
