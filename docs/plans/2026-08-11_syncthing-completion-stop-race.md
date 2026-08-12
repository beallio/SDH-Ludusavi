# Plan: Fix Post-Game Completion Stop Race (syncthing-completion-stop-race)

## Context

### Problem Definition

Post-game `SYNCTHING COMPLETE` never publishes. The status strip shows
`SYNCTHING UPLOADING` for five minutes and then reports a false
`LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE`, for a sync that actually finished in
seventeen seconds.

This is a live regression in `dev` at `7a0d570` and in the published prerelease
`v0.4.4-dev.g7a0d570`. It affects both debug and normal logging modes. Saves propagate
correctly; only the reported status is wrong.

Measured on `steamdeck` (`v0.4.4-dev.g7a0d570`, debug logging on, three connected peers),
log `2026-08-11 22.29.25.log`:

```text
22:34:01.073  handoff activated
22:34:06.579  SYNCTHING UPLOADING published
22:34:07.928  incomplete_peers=2 awaiting_fresh=0   all three reported, one already complete
22:34:10.014  incomplete_peers=1                    two complete
22:34:18.405  incomplete_peers=0 needed_deletes=41  all content delivered
22:34:20.507  incomplete_peers=0 needed_deletes=40  last log line; watcher stopped
22:39:01.528  SYNCTHING UPLOAD INCOMPLETE           frontend 300s ceiling, exactly on time
```

### Root Cause

`_stop_after_post_game_peer_completion()` in `watcher.py` sets `stop_event` once first-peer
completion is confirmed. Before that method was added, the backend **never** stopped itself
on completion: it kept publishing settled samples and the frontend stopped the watch after
publishing `SYNCTHING COMPLETE`. The current code inverts that ordering and races the
frontend.

The frontend requires three settled samples with **distinct** timestamps
(`syncthingMonitorMachine.ts`):

```ts
if (!Number.isFinite(timestamp) || timestamp === state.lastProcessedTimestamp) {
  effects = { ...effects, nextPoll: "active" };
  break;
}
```

When the watcher thread stops, `latest_sample` freezes. Nothing removes the watch from
`self.watches`, so `poll_watch()` keeps returning that frozen sample rather than a stopped
result. The frontend therefore polls forever, sees the same `timestamp_unix` every time,
skips each poll as a duplicate, never increments `settledCount`, and never reaches three.
It stays in `uploading` until the 300-second post-game ceiling fires and publishes the
incomplete terminal.

Normal mode is worse than the captured debug run: the stop fires on the *first* qualifying
tick, so the frontend can receive at most one settled sample.

### Intended Outcome

The backend never stops itself on first-peer completion. It keeps publishing settled samples
with advancing timestamps so the frontend can accumulate its quorum, publish
`SYNCTHING COMPLETE`, and stop the watch as it did before this regression. Debug extended
observation continues to work, but only *after* the frontend has released the watch.

### Relevant Files

```text
py_modules/sdh_ludusavi/syncthing/watcher.py    _stop_after_post_game_peer_completion,
                                                SyncthingWatchManager.stop_watch
tests/test_watcher.py                           watcher and manager tests
docs/specs/sdh_ludusavi_sync.md                 completion contract
docs/specs/custom_status_bar_ui.md              activity source description
docs/agent_conversations/                       session record
```

### Decisions Already Made

Implement these as stated; do not re-open them.

- **Delete the stop-on-completion behaviour rather than tune it.** Ownership of "stop after
  completion" belongs to the frontend, which already calls `stopWatch` once it publishes
  `SYNCTHING COMPLETE`. The backend must not pre-empt that.
- The debug-extending flag is still latched at first confirmation, because
  `stop_watch()` reads it to decide whether to keep the watch alive. Latching must be
  separated from stopping.
- Extended observation self-terminates **only after the manager has released the watch**
  into `_observing_watches`. A watch the frontend still owns must never self-terminate on
  peer completion, in either mode.
- Do not change the frontend, the RPC sample key set, the stall window, or either ceiling.
  The 300-second ceiling behaved exactly as designed here; it fired because the status was
  wrong, not because its value is wrong.

**Slug used throughout this plan:** `syncthing-completion-stop-race`

---

## Orchestration Contract

**Slug:** `syncthing-completion-stop-race`

**Plan file:**

```text
docs/plans/2026-08-11_syncthing-completion-stop-race.md
```

**Implementation branch:**

```text
feat/syncthing-completion-stop-race
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-completion-stop-race_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-completion-stop-race_finalized
```

**Review notes:**

```text
docs/review/syncthing-completion-stop-race-review-*.md
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
git checkout -b feat/syncthing-completion-stop-race
```

Commit this plan first:

```bash
git add docs/plans/2026-08-11_syncthing-completion-stop-race.md
git commit -m "docs(plan): add syncthing-completion-stop-race implementation plan"
```

---

## Atomic task review gate

This plan uses **one implementation task per orchestration round**.

1. The initial round authorizes **Task 1 only**.
2. Complete the authorized task end to end: RED tests, recorded failures, GREEN, refactor,
   focused command, full quality gates, one atomic Conventional Commit, mark the round
   finished, exit.
3. Do not begin the next task or make opportunistic edits while waiting for review.
4. On continuation, read the latest committed review note. Advance only when it states both
   `TASK N: ACCEPTED` and `AUTHORIZED TASK: N+1`.
5. The engine uses `STATUS: CHANGES_REQUESTED` for every non-final continuation; that
   trailer is a resume signal, not a rejection.
6. `STATUS: APPROVED` is reserved for human approval after Task 3.
7. If a review note is missing, ambiguous, or skips a task number, stop without changing
   files and report the gate violation.

**There is no halt-and-report instruction anywhere in this plan.** If something seems
impossible, implement the closest correct thing and record the concern in the session log.
Marking a round finished without producing code is never the right response.

---

## Implementation Tasks

### Task 1 — Let the frontend own the completion stop

**Initially authorized. Stop for review after this task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_watcher.py
```

1. Write the failing tests first. The decisive one must model the real polling sequence
   rather than a single tick:
   - a post-game watch that reaches first-peer confirmation continues to publish samples
     with **advancing** `timestamp_unix` across several subsequent ticks, in **both** debug
     and normal mode, and `stop_event` is **not** set by the watch itself;
   - a watch released by `stop_watch()` in normal mode stops, as today;
   - a watch released by `stop_watch()` in debug mode keeps observing and self-terminates
     once every peer finishes;
   - a debug watch that has **not** been released does **not** self-terminate when every
     peer finishes — it keeps publishing advancing samples until released;
   - `stop_all()` still stops both owned and released watches.
2. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_watcher.py -q --no-cov
   ```
3. Split latching from stopping in `_stop_after_post_game_peer_completion()`. At first
   confirmation it must set `_outbound_first_peer_completion_reached` and evaluate the debug
   gate into `_debug_outbound_completion_observation`, and then **return without touching
   `stop_event`**. Rename the method to reflect that it no longer stops anything.
4. Add an explicit released state rather than inferring it. Give `SyncthingWatch` a flag set
   by a manager-called method — for example `begin_released_observation(callback)` — that
   records both the callback and the fact that the frontend has let go. Self-termination on
   "all peers finished" must be guarded by that flag. Do not infer release from the presence
   of the callback alone; an implicit signal here is what makes this class of bug hard to
   see.
5. Update `SyncthingWatchManager.stop_watch()` to call that method when it moves a watch
   into `_observing_watches`, and leave its normal-mode branch unchanged.
6. Leave the stall detector, both ceilings, the TTL path, and `stop_all()` behaviour alone.
   Confirm the TTL `_on_expired` callback still pops from both dicts.
7. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_watcher.py
   git commit -m "fix(syncthing): let the frontend own the completion stop"
   ```

Run `scripts/orchestration/mark-finished syncthing-completion-stop-race` and exit. Task 2
is forbidden until a review note authorizes it.

### Task 2 — Add a poll-sequence regression harness

**Authorized only by a committed review note accepting Task 1. Stop for review after this
task.**

Files in scope:

```text
tests/test_watcher.py
```

Four defects on the previous branch shared one shape: a test exercised a sequence the
running system never performs. Watch-level tests cannot see the frontend's quorum, because
they never poll through the manager. This task adds the missing level of coverage; it
changes no production code.

1. Write a small helper in `tests/test_watcher.py` that drives a watch **through
   `SyncthingWatchManager.poll_watch()`** for a given number of polls and returns the
   observed sequence of `timestamp_unix` values and `settled` flags. It must go through the
   manager, not read `watch.latest_sample` directly — reading the attribute is exactly the
   shortcut that hid this regression.
2. Add a test that reproduces the 2026-08-11 22:34 failure and would have caught it: after
   first-peer confirmation, poll repeatedly and assert that at least three settled samples
   with **distinct** timestamps are observable before anything stops the watch. Under the
   pre-Task-1 code this fails because the timestamps freeze; confirm that before trusting
   it.
3. Add a test asserting `poll_watch()` on a watch whose thread has stopped but which is
   still registered does not return an endless run of identical timestamps — capture the
   current behaviour explicitly so a future change to it is visible rather than silent.
4. Do not modify production code in this task. If the harness reveals a further defect,
   record it in the session log and report it through the round rather than fixing it here.
5. Rerun the focused command and the full quality gates, then commit only this unit:

   ```bash
   git add tests/test_watcher.py
   git commit -m "test(syncthing): cover the manager poll sequence after completion"
   ```

Run `scripts/orchestration/mark-finished syncthing-completion-stop-race` and exit. Task 3
is forbidden until a review note authorizes it.

### Task 3 — Document the ownership rule and record verification

**Authorized only by a committed review note accepting Task 2. Stop for final review after
this task.**

Files in scope:

```text
docs/specs/sdh_ludusavi_sync.md
docs/specs/custom_status_bar_ui.md
docs/agent_conversations/2026-08-11_syncthing-completion-stop-race.json
```

1. Record the ownership rule in both specs as a durable contract: the backend publishes
   settled samples and never stops a post-game watch on peer completion; the frontend
   publishes `SYNCTHING COMPLETE` after three settled samples with distinct timestamps and
   then calls `stopWatch`; the backend continues observing past that call only under debug
   logging, and only once released. State that a stopped watcher freezes `latest_sample`,
   so any backend-side stop that pre-empts the frontend silently prevents completion.
2. No `README.md` change is expected: the user-facing definition of `SYNCTHING COMPLETE` is
   unchanged by this fix. Confirm that is still true and say so in the session log rather
   than editing the file to no purpose.
3. Write the JSON session record with the date, objective, files modified, each task's RED
   proof, design decisions, the Task 1-2 commit hashes, the Task 3 commit subject, the
   review-note paths available through Task 2, exact validation results, and the deferred
   verification below. Do not attempt a self-referential Task 3 hash. Include the
   observation that four consecutive defects on the predecessor branch shared the
   wrong-test-shape pattern, and that Task 2's harness exists to close it.
4. Run the documentation and static suites, then the full quality gates:

   ```bash
   ./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py -q --no-cov
   ```
5. Commit only this unit:

   ```bash
   git add docs/specs/sdh_ludusavi_sync.md docs/specs/custom_status_bar_ui.md docs/agent_conversations/2026-08-11_syncthing-completion-stop-race.json
   git commit -m "docs(syncthing): define completion stop ownership"
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

Every step must be able to fail. Apply `references/verification-standards.md` from the
`orchestration-plan-author` skill before adding any step: ask what state of the world makes
it print the failure output, and delete it if the answer is "none". Report actual output.

### 1. Automated acceptance

```bash
scripts/orchestration/run-quality-gates
```

Record the frontend count, the pytest count, and coverage.

### 2. Prove the fix by mutation

With Task 1 complete and green, restore the stop on completion — add `self.stop_event.set()`
at the point first-peer confirmation is latched — and run:

```bash
./run.sh uv run pytest tests/test_watcher.py -q --no-cov
```

Expected: the advancing-timestamp test **fails**, in both the debug and normal parametrised
cases. Record the failing test names. If only one mode fails, the other mode is not covered
— fix that before continuing, because normal mode is the one most users run.

Restore and confirm green.

### 3. Prove the release guard by mutation

Still in Task 1, remove the released-state guard so a debug watch self-terminates on peer
completion whether or not the manager released it, and rerun the same command.

Expected: the not-yet-released test **fails**. That guard is the whole difference between
extended observation and a second instance of this bug; if nothing fails, it is untested.

### 4. Prove the Task 2 harness catches the original regression

Runs **after** steps 2 and 3. With Task 2 complete, apply the step 2 mutation again — the
stop on completion — and run the harness test alone:

```bash
./run.sh uv run pytest tests/test_watcher.py -q --no-cov -k poll_sequence
```

Expected: it fails, reporting fewer than three distinct settled timestamps. This is the
control for the entire plan: the harness exists specifically to catch the defect that
930 passing tests missed, so it must demonstrably fail against that defect. If it passes,
the harness is not polling through the manager or is not asserting distinctness.

### 5. Deferred and explicitly not verified

- **Device verification is required before this is considered fixed**, and is deferred to a
  prerelease. The expected signature is `SYNCTHING COMPLETE` published within roughly twenty
  seconds of handoff while a transition line still reports non-zero `needed_deletes`, and
  **no** `SYNCTHING UPLOAD INCOMPLETE` at the 300-second mark. Compare against the
  2026-08-11 22:34 capture, where completion never published and the false terminal fired at
  22:39:01.528.
- **Debug extended observation still has no device evidence.** It has now failed once on
  hardware in a way unit tests did not predict; treat the next device run as its first real
  test, not a re-confirmation.
- **The stall window and both ceilings remain unchanged and unexercised** across five
  consecutive plans. The 300-second ceiling did fire correctly in the captured failure,
  which is the first evidence any of them work as intended, but it fired on a wrong status
  rather than a genuine stall.
- **The accepted `stop_watch()` race** carried from the predecessor branch remains open and
  is unaffected by this plan.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-completion-stop-race
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-completion-stop-race_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-completion-stop-race`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-completion-stop-race-review-*.md
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
   scripts/orchestration/clear-finished syncthing-completion-stop-race
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
   git add docs/review/syncthing-completion-stop-race-review-*.md
   git commit -m "docs(review): record syncthing-completion-stop-race review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-completion-stop-race
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-completion-stop-race` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed syncthing-completion-stop-race
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-completion-stop-race
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-completion-stop-race_finalized
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
scripts/orchestration/finalize syncthing-completion-stop-race
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-completion-stop-race_finished
/tmp/sdh_ludusavi/syncthing-completion-stop-race_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
