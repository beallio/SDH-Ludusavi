# Plan: Complete On First Peer With Settling (syncthing-first-peer-completion)

## Context

### Problem Definition

Post-game `SYNCTHING COMPLETE` waits for **every** connected peer to receive the backup.
The status strip stays on screen for that whole time, so the slowest peer sets how long the
user waits after quitting a game.

The 2026-08-11 11:15 Wobbly Life run on `steamdeck` (`v0.4.4-dev.g856f4cc`, three connected
peers) shows the shape of the wait. Per-peer content-complete times, derived from raw
`FolderCompletion` events by taking each peer's last non-zero report:

```text
handoff                11:15:38.051
Y4IAP3B  content done  11:15:53.342   +15.3s
WQ6UZOR  content done  11:15:57.525   +19.5s
5CE2WLE  content done  11:16:14.315   +36.3s
SYNCTHING COMPLETE     11:16:17.451   +39.4s
```

Two peers finished within four seconds of each other; the third took another seventeen. The
tail is one straggler, not a gradual spread.

The strip is visible for all of it. In-progress statuses inherit the 930-second auto-hide
window scheduled at `backing_up` and never reschedule; only the terminal status schedules a
2-second hide:

```text
11:15:35.330  backing_up                Auto-hide scheduled in 930000ms
11:15:38.951  syncthing_pending_upload  visible=true   (no reschedule)
11:15:51.324  syncthing_uploading       visible=true   (no reschedule)
11:16:17.451  syncthing_complete        Auto-hide scheduled in 2000ms
11:16:19.453  visible=false
```

That is 44 seconds of on-screen strip, about 21 of which are spent waiting on the third
peer after the save is already safe on two others.

### The risk this plan must not introduce

A peer can report content-complete while more data is still being written. In the same run,
`Y4IAP3B` reported `needBytes=0 needItems=0` at 11:15:45.214 and then went back to non-zero,
with its last non-zero report at 11:15:51.243 — a false-complete window of roughly six
seconds.

That blip was excluded by the existing freshness rule, because the plugin armed the mutation
at 11:15:50.960, after the final write, so the 11:15:45 report was stale. Freshness is not a
general guarantee: it protects against reports predating the *observed* mutation, not
against a peer confirming between two writes that the plugin observes as one. Declaring
completion on a single unconfirmed report leans on that far harder than the current
all-peers rule does, because one early report ends the watch instead of needing agreement
from three.

### Intended Outcome

`SYNCTHING COMPLETE` is published once at least one connected relevant peer has the content
and has held that state across consecutive observations. On the captured run that boundary
is roughly +15.3s plus the settling window instead of +39.4s, cutting the visible strip
from about 44 seconds to roughly 25.

### Relevant Files

```text
py_modules/sdh_ludusavi/syncthing/_types.py     PeerCompletionDiagnostics, constants
py_modules/sdh_ludusavi/syncthing/activity.py   compute_activity_status outbound branch
py_modules/sdh_ludusavi/syncthing/watcher.py    confirmation streak, extended observation
tests/test_activity.py                          classification tests
tests/test_watcher.py                           watcher and diagnostics tests
docs/specs/sdh_ludusavi_sync.md                 completion contract
docs/specs/custom_status_bar_ui.md              activity source description
README.md                                       user-facing status definitions
```

### Decisions Already Made

Implement these as stated; do not re-open them.

- Completion requires **at least one** connected relevant peer that is content-complete and
  fresh, sustained across **three consecutive backend observations**. At Syncthing's
  roughly two-second summary cadence that is a four-to-six second confirmation window.
- The watch **stops** on completion as it does today, **except** when debug logging is
  enabled, in which case it keeps observing until every peer finishes or an existing
  boundary is reached. The published status is identical either way; only the log tail
  differs.
- The debug gate is `logger.isEnabledFor(logging.DEBUG)`. `set_debug_logging()` in
  `service.py` raises the decky logger to `DEBUG`, so no new setting, RPC field, or service
  coupling is required. **If inspection shows the `sdh_ludusavi.*` loggers do not inherit
  that level, stop and report it as a blocking finding — do not invent a new setting.**
- `SYNCTHING COMPLETE` now means at least one connected device has the save, not all of
  them. This is a weaker guarantee than the current documentation states and the README must
  say so plainly.

**Slug used throughout this plan:** `syncthing-first-peer-completion`

---

## Orchestration Contract

**Slug:** `syncthing-first-peer-completion`

**Plan file:**

```text
docs/plans/2026-08-11_syncthing-first-peer-completion.md
```

**Implementation branch:**

```text
feat/syncthing-first-peer-completion
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-first-peer-completion_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-first-peer-completion_finalized
```

**Review notes:**

```text
docs/review/syncthing-first-peer-completion-review-*.md
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
git checkout -b feat/syncthing-first-peer-completion
```

Commit this plan first:

```bash
git add docs/plans/2026-08-11_syncthing-first-peer-completion.md
git commit -m "docs(plan): add syncthing-first-peer-completion implementation plan"
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
5. The engine uses `STATUS: CHANGES_REQUESTED` for every non-final continuation; that
   trailer is a mechanical resume signal, not a rejection of an accepted task.
6. `STATUS: APPROVED` is reserved for human approval after Task 3.
7. If a review note is missing, ambiguous, skips a task number, or authorizes more than one
   task, stop without changing files and report the gate violation.

---

## Implementation Tasks

### Task 1 — Complete on the first confirmed peer

**Initially authorized. Stop for review after this task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/_types.py
py_modules/sdh_ludusavi/syncthing/activity.py
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_activity.py
tests/test_watcher.py
```

The outbound branch of `compute_activity_status()` currently reads:

```python
uploading = (
    bool(remote_progress)
    or incomplete_peer
    or awaiting_fresh_peer_completion
    or outbound_observation_hold_active
)
```

Replace the two peer-derived terms with a single confirmation term.

1. Write the failing tests first:
   - with a mutation armed and no peer yet content-complete and fresh, `uploading` is true;
   - one peer content-complete and fresh for fewer than three consecutive observations
     leaves `uploading` true, even while the other peers are still behind;
   - the same peer on its third consecutive confirming observation flips `uploading` false
     and `settled` true **while the other peers remain content-incomplete**; this is the
     behavioural heart of the plan and must assert the other peers' state explicitly;
   - a peer that confirms, then regresses to content-incomplete before reaching three
     observations, resets the streak and does not complete — model this on the real
     `Y4IAP3B` blip, which reported zero at 11:15:45.214 and was non-zero again at
     11:15:51.243;
   - with no mutation armed (`outbound_index_observed_monotonic == 0`) there is nothing to
     confirm and `uploading` is not held true by this branch;
   - `RemoteDownloadProgress` and the 2.5-second observation hold still force `uploading`
     independently;
   - a pre-game watch is unaffected.
2. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_activity.py tests/test_watcher.py -q --no-cov
   ```
3. Add `OUTBOUND_CONFIRMATION_OBSERVATIONS = 3` to `_types.py` with a comment stating the
   reasoning: at Syncthing's roughly two-second cadence this is a four-to-six second
   window, and its purpose is the multi-write case rather than the stale-report case, which
   freshness already covers.
4. Track the streak in `SyncthingWatch`, alongside the existing `_last_outbound_need`
   fields, not inside `compute_activity_status()`. Increment when at least one connected
   relevant peer is both content-complete and fresh; reset to zero otherwise. Pass the
   resulting boolean into `compute_activity_status()` as a new keyword argument defaulting
   to the compatibility-preserving value, so the classifier stays pure and directly
   testable.
5. Keep `incomplete_peers`, `awaiting_fresh_completion`, `needed_bytes`, `needed_items`,
   `needed_deletes`, and `peers_pending_deletes` computed and logged exactly as now. They
   are the only record of what the other peers were doing at completion and must not be
   narrowed.
6. Do not change the stall detector, either ceiling, the RPC sample key set, or any
   frontend file.
7. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/_types.py py_modules/sdh_ludusavi/syncthing/activity.py py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_activity.py tests/test_watcher.py
   git commit -m "feat(syncthing): complete on the first confirmed peer"
   ```

Run `scripts/orchestration/mark-finished syncthing-first-peer-completion` and exit. Task 2
is forbidden until a review note authorizes it.

### Task 2 — Keep observing under debug logging

**Authorized only by a committed review note accepting Task 1. Stop for review after this
task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_watcher.py
```

1. Before writing code, confirm by inspection that a `sdh_ludusavi.*` logger reports
   `isEnabledFor(logging.DEBUG)` as true when `service._apply_log_level()` has raised the
   decky logger to `DEBUG`. If the plugin loggers do not inherit that level, **stop and
   report it**; do not add a setting, an RPC field, or a service reference to work around
   it.
2. Write the failing tests first:
   - with debug logging off, a watch that reaches first-peer confirmation publishes the
     completed sample and sets `stop_event` exactly as it does today;
   - with debug logging on, the same watch publishes the identical completed sample but
     does **not** set `stop_event`, and continues to emit transition diagnostics as the
     remaining peers finish;
   - in that extended mode the watch still terminates on the existing stall window and hard
     ceiling — extended observation must not create an unbounded watch;
   - the published sample is byte-for-byte identical in both modes, so the user-visible
     status never depends on the debug toggle.
3. Record the observed failures:

   ```bash
   ./run.sh uv run pytest tests/test_watcher.py -q --no-cov
   ```
4. Implement the gate with `logger.isEnabledFor(logging.DEBUG)`. Evaluate it at the moment
   completion is reached rather than caching it at watch construction, so toggling debug
   logging mid-session behaves predictably.
5. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_watcher.py
   git commit -m "feat(syncthing): keep observing peers under debug logging"
   ```

Run `scripts/orchestration/mark-finished syncthing-first-peer-completion` and exit. Task 3
is forbidden until a review note authorizes it.

### Task 3 — Document the weaker guarantee and record verification

**Authorized only by a committed review note accepting Task 2. Stop for final review after
this task.**

Files in scope:

```text
README.md
docs/specs/sdh_ludusavi_sync.md
docs/specs/custom_status_bar_ui.md
docs/agent_conversations/2026-08-11_syncthing-first-peer-completion.json
```

1. Rewrite the **Syncthing Complete** entry in `README.md`. It currently says every
   connected device that shares the folder has received the backup. It must now say **at
   least one** connected device has received it, and state plainly that other connected
   devices may still be catching up when the status appears. Keep the existing caveat about
   disconnected and offline devices. Do not soften this into implying full propagation —
   the guarantee genuinely got weaker and the documentation is the only place a user will
   learn that.
2. Update both specs: the completion rule is first-confirmed-peer with a three-observation
   settling window; the per-peer counts remain in diagnostics and record what the other
   peers were doing at completion; and debug logging extends observation without changing
   the published status.
3. Record the measured effect using the 2026-08-11 capture: first peer at +15.3s, second at
   +19.5s, third at +36.3s, published completion at +39.4s, and the visible-strip
   arithmetic from the Context section.
4. Write the JSON session record with the date, objective, files modified, each task's RED
   proof, design decisions, the Task 1-2 commit hashes, the Task 3 commit subject, the
   review-note paths available through Task 2, exact validation results, and the deferred
   verification below. Do not attempt a self-referential Task 3 hash.
5. Run the documentation and static suites, then the full quality gates:

   ```bash
   ./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py -q --no-cov
   ```
6. Commit only this unit:

   ```bash
   git add README.md docs/specs/sdh_ludusavi_sync.md docs/specs/custom_status_bar_ui.md docs/agent_conversations/2026-08-11_syncthing-first-peer-completion.json
   git commit -m "docs(syncthing): define completion as first confirmed peer"
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
`orchestration-plan-author` skill before adding any step of your own: ask what state of the
world makes it print the failure output, and delete it if the answer is "none". Report
actual output, not conclusions.

### 1. Automated acceptance

```bash
scripts/orchestration/run-quality-gates
```

Record the frontend count, the pytest count, and the coverage percentage. A drop against
the previous round is a failure to investigate.

### 2. Prove the Task 1 gate by mutation

With Task 1 complete and green, set `OUTBOUND_CONFIRMATION_OBSERVATIONS = 1`, then run:

```bash
./run.sh uv run pytest tests/test_activity.py tests/test_watcher.py -q --no-cov
```

Expected: the regression test modelled on the `Y4IAP3B` blip **fails**, because a single
confirming observation completes the watch before the peer regresses. Record the failing
test name. If it passes, the settling window is not actually being exercised — the test is
confirming across too few observations to distinguish 1 from 3. Fix it before continuing.

Restore the constant and confirm green.

### 3. Prove the completion boundary moved

Still in Task 1, revert the outbound branch to the previous all-peers form
(`incomplete_peer or awaiting_fresh_peer_completion`) and run the same command.

Expected: the test asserting completion **while other peers remain content-incomplete**
fails. That test is the entire point of the plan; if it passes against the all-peers form,
it is not asserting the new behaviour. Record the failing test name, restore, confirm green.

### 4. Prove the Task 2 gate by mutation

With Task 2 complete and green, force the debug gate to a constant `False`, then run:

```bash
./run.sh uv run pytest tests/test_watcher.py -q --no-cov
```

Expected: the extended-observation test fails while the stop-on-completion test still
passes. Then force it to `True` and confirm the stop-on-completion test fails instead. Both
directions must be pinned; a gate tested in only one direction passes when it is stuck.

### 5. Negative control — replay the captured sequence

Runs **after** steps 2 to 4. Add a test that feeds the real 2026-08-11 per-peer sequence
through the watcher and asserts the completion boundary lands after the first peer's
confirmation rather than the third's:

```text
Y4IAP3B content-complete   +15.3s   -> not yet complete (streak building)
Y4IAP3B still complete     +19.5s   -> complete, while 5CE2WLE is still content-incomplete
5CE2WLE content-complete   +36.3s   -> watch already finished
```

Under the pre-Task-1 predicate the middle assertion fails. Confirm that before trusting it.

### 6. Deferred and explicitly not verified

- **A post-game device run is deferred to a prerelease.** The expected signature is
  `SYNCTHING COMPLETE` published while a transition line still reports
  `incomplete_peers` greater than zero — the direct analogue of the `needed_deletes=40`
  signature that confirmed the previous change. Measure handoff-to-complete and compare
  against the +39.4s baseline from 2026-08-11.
- **Extended debug observation has never run on device.** Its unit coverage is real; its
  behaviour against a live slow peer is untested.
- **The stall window and both ceilings remain unchanged and unexercised.** They have now
  been carried unverified across three consecutive plans; completing on the first peer
  makes them even less likely to be reached, which lowers the urgency without removing the
  gap.
- **The weaker guarantee is not itself verifiable by test.** Whether "at least one connected
  device has the save" is acceptable for the way these devices are actually used is a
  judgement the user has made; no test can confirm it was the right call.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-first-peer-completion
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-first-peer-completion_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-first-peer-completion`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-first-peer-completion-review-*.md
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
   scripts/orchestration/clear-finished syncthing-first-peer-completion
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
   git add docs/review/syncthing-first-peer-completion-review-*.md
   git commit -m "docs(review): record syncthing-first-peer-completion review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-first-peer-completion
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-first-peer-completion` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed syncthing-first-peer-completion
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-first-peer-completion
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-first-peer-completion_finalized
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
scripts/orchestration/finalize syncthing-first-peer-completion
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-first-peer-completion_finished
/tmp/sdh_ludusavi/syncthing-first-peer-completion_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
