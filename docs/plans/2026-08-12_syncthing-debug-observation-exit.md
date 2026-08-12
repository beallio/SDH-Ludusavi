# Plan: Fix Debug Observation Exit Condition (syncthing-debug-observation-exit)

## Context

### Problem Definition

Debug extended peer observation terminates instantly every time it starts. It has never
observed anything, on any device run, and it cannot.

The exit condition in `_latch_post_game_peer_completion()` is:

```python
if diagnostics.incomplete_peers == 0 and diagnostics.awaiting_fresh_completion == 0:
    self.stop_event.set()
```

`incomplete_peers` counts peers missing **content**. Since the content-only completion
change, a peer holding only pending deletes is not incomplete. That is the same predicate
that causes completion in the first place — so at the moment the frontend publishes
`SYNCTHING COMPLETE` and releases the watch, `incomplete_peers` is **already zero by
definition**. The first tick after release evaluates a condition that is guaranteed true and
stops immediately.

Confirmed on the 2026-08-12 11:25 Deadpool run (`v0.4.4-dev.ged733d5`, Debug Logging on):

```text
11:26:06.640  acknowledged  incomplete_peers=0 needed_deletes=34 peers_pending_deletes=2
11:26:07.666  latch: debug_observation_selected=True
11:26:08.759  acknowledged  incomplete_peers=0 needed_deletes=27 peers_pending_deletes=2
11:26:10.062  SYNCTHING COMPLETE          (frontend releases the watch)
              ... nothing further, with 27 deletes still outstanding
```

This also explains the previously unexplained 2026-08-11 23:25 result, where extended
observation was selected under an always-true gate and still produced no post-completion
transitions. The gate was genuinely broken and worth fixing, but it was never the reason
observation did not run.

### The second half — the missing bound

Fixing only the exit condition converts a dead feature into a very long-lived one.
`_stop_if_post_game_upload_incomplete()` evaluates the stall window and the hard ceiling
**after** an early return:

```python
if diagnostics.incomplete_peers == 0:
    self._last_outbound_need = None
    self._last_outbound_need_decrease_monotonic = None
    return False          # <-- ceiling and stall checks are below this line
```

A released debug watch has `incomplete_peers == 0` by construction, so neither the
90-second stall window nor the 900-second hard ceiling can ever fire for it. Its only bound
is the thread TTL at ceiling + 60 seconds, which terminates through the
"exceeded TTL without stop_watch" warning path and publishes a `watch_ttl_expired` sample —
a warning-shaped exit for a diagnostic that behaved normally.

Both changes are required together. Shipping the exit-condition fix alone would replace an
instant no-op with a 16-minute watch that ends in a warning.

### Intended Outcome

Extended observation continues while pending deletes remain, terminates cleanly when they
drain, and is bounded by the existing hard ceiling rather than by the TTL warning path.
Published status is unchanged in every case.

### Relevant Files

```text
py_modules/sdh_ludusavi/syncthing/watcher.py    _latch_post_game_peer_completion exit condition
tests/test_watcher.py                           watcher and manager tests
docs/specs/sdh_ludusavi_sync.md                 extended observation contract
docs/agent_conversations/                       session record
```

### Decisions Already Made

Implement these as stated; do not re-open them.

- **The exit condition gains a pending-deletes term.** Stop when
  `incomplete_peers == 0 and awaiting_fresh_completion == 0 and peers_pending_deletes == 0`.
  `peers_pending_deletes` already exists on `PeerCompletionDiagnostics`; do not add a new
  field or recompute deletes separately.
- **The extended path gets its own ceiling check** so a never-draining delete backlog
  terminates cleanly at `POST_GAME_WATCH_HARD_CEILING_SECONDS` instead of falling through to
  the TTL warning. Do not move or restructure `_stop_if_post_game_upload_incomplete()`; add
  the bound where the extended branch already lives.
- **Do not change the stall window, the ceiling values, the completion rule, the settle
  window, the debug gate, the RPC sample key set, or any frontend file.** This plan is
  scoped to making an opt-in diagnostic work and terminate.
- **Published status must remain identical** whether or not extended observation runs. That
  is the invariant that makes this safe to ship without device verification.

**Slug used throughout this plan:** `syncthing-debug-observation-exit`

---

## Orchestration Contract

**Slug:** `syncthing-debug-observation-exit`

**Plan file:**

```text
docs/plans/2026-08-12_syncthing-debug-observation-exit.md
```

**Implementation branch:**

```text
feat/syncthing-debug-observation-exit
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-debug-observation-exit_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-debug-observation-exit_finalized
```

**Review notes:**

```text
docs/review/syncthing-debug-observation-exit-review-*.md
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
git checkout -b feat/syncthing-debug-observation-exit
```

Commit this plan first:

```bash
git add docs/plans/2026-08-12_syncthing-debug-observation-exit.md
git commit -m "docs(plan): add syncthing-debug-observation-exit implementation plan"
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
6. `STATUS: APPROVED` is reserved for human approval after Task 2.
7. If a review note is missing, ambiguous, or skips a task number, stop without changing
   files and report the gate violation.

**There is no halt-and-report instruction anywhere in this plan.** If something seems
impossible, implement the closest correct thing and record the concern in the session log.
Marking a round finished without producing code is never the right response.

---

## Implementation Tasks

### Task 1 — Observe until deletes drain, and bound it

**Initially authorized. Stop for review after this task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_watcher.py
```

1. Write the failing tests first. The decisive one must model the real release sequence,
   because a watch-only test cannot see this:
   - a released debug watch with `incomplete_peers == 0`, `awaiting_fresh_completion == 0`
     and `peers_pending_deletes > 0` **keeps running** and continues publishing samples.
     Against the current code this fails immediately, which is the whole defect;
   - the same watch stops once `peers_pending_deletes` reaches zero;
   - a released debug watch whose deletes never drain stops at
     `POST_GAME_WATCH_HARD_CEILING_SECONDS` and does **not** reach the thread TTL. Assert
     the terminal it produces, not merely that it stopped;
   - an **unreleased** debug watch still does not self-terminate on peer completion — the
     guard added by the predecessor branch must survive this change;
   - a non-debug watch is unaffected: `stop_watch()` stops it at completion as today;
   - the published sample is identical in both modes at the moment completion is reached.
2. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_watcher.py -q --no-cov
   ```
3. Add the pending-deletes term to the exit condition:

   ```python
   if (
       diagnostics.incomplete_peers == 0
       and diagnostics.awaiting_fresh_completion == 0
       and diagnostics.peers_pending_deletes == 0
   ):
   ```

   Add a comment recording *why* the deletes term is load-bearing: `incomplete_peers` is
   zero by construction once the watch has been released, because content completion is
   what caused the release, so without this term the branch stops on its first evaluation.
4. Add a hard-ceiling bound to the extended branch so a never-draining backlog terminates
   there rather than at the thread TTL. Reuse
   `POST_GAME_WATCH_HARD_CEILING_SECONDS` and `self.watch_started_monotonic`; do not
   introduce a new constant and do not restructure
   `_stop_if_post_game_upload_incomplete()`.
5. Both stop paths must call `_deregister_finished_debug_observation()` so the manager's
   `_observing_watches` registry does not retain a stopped watch.
6. Change nothing else.
7. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_watcher.py
   git commit -m "fix(syncthing): observe until pending deletes drain"
   ```

Run `scripts/orchestration/mark-finished syncthing-debug-observation-exit` and exit. Task 2
is forbidden until a review note authorizes it.

### Task 2 — Document the exit contract and record verification

**Authorized only by a committed review note accepting Task 1. Stop for final review after
this task.**

Files in scope:

```text
docs/specs/sdh_ludusavi_sync.md
docs/agent_conversations/2026-08-12_syncthing-debug-observation-exit.json
```

1. Correct the spec. It currently says extended observation continues "until all peers
   finish or an existing terminal boundary is reached", which is ambiguous enough to have
   permitted this defect. State precisely: observation continues while any connected
   relevant peer has pending deletes, ends when those drain, and is bounded by the hard
   ceiling. Record that `incomplete_peers` cannot serve as the exit condition because it is
   zero by construction after release.
2. No `README.md` change is expected — extended observation is an opt-in diagnostic that
   never alters published status. Confirm that and say so in the session log rather than
   editing the file.
3. Write the JSON session record with the date, objective, files modified, the RED proof,
   design decisions, the Task 1 commit hash, the Task 2 commit subject, the review-note
   path from Task 1, exact validation results, and the deferred verification below. Record
   that this defect also explains the 2026-08-11 23:25 result that was previously logged as
   unexplained, and that the debug-gate fix shipped for it was a real but separate defect.
4. Run the documentation and static suites, then the full quality gates:

   ```bash
   ./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py -q --no-cov
   ```
5. Commit only this unit:

   ```bash
   git add docs/specs/sdh_ludusavi_sync.md docs/agent_conversations/2026-08-12_syncthing-debug-observation-exit.json
   git commit -m "docs(syncthing): define the debug observation exit contract"
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

### 2. Prove the deletes term is load-bearing

With Task 1 complete and green, remove `and diagnostics.peers_pending_deletes == 0` from the
exit condition and run:

```bash
./run.sh uv run pytest tests/test_watcher.py -q --no-cov
```

Expected: the keeps-running test **fails**, because the branch stops on its first evaluation
exactly as it does today. Record the failing test name.

If it passes, the test is not modelling a released watch — it must go through
`stop_watch()` so `_released_for_observation` is set, because an unreleased watch never
reaches this branch at all and would pass against both implementations.

Restore and confirm green.

### 3. Prove the ceiling bound

Still in Task 1, remove the hard-ceiling check from the extended branch and rerun.

Expected: the never-draining test **fails** — the watch survives past the ceiling. Without
this the feature is bounded only by the thread TTL, which exits through a warning path
sixty seconds later.

### 4. Prove the release guard survived

Still in Task 1, remove `self._released_for_observation` from the branch guard and rerun.

Expected: the unreleased-watch test **fails**. That guard came from the predecessor branch
and protects the frontend's completion quorum; a change to the exit condition must not
weaken it.

### 5. Deferred and explicitly not verified

- **Device verification is deferred and is genuinely optional here.** Extended observation
  is opt-in and never alters published status, so a wrong result costs a diagnostic tail
  rather than a user-visible outcome. The expected signature on a Debug Logging run is
  transition lines continuing **after** `SYNCTHING COMPLETE`, tailing off as
  `needed_deletes` reaches zero. On 2026-08-12 11:26 they stopped dead at completion with 27
  deletes outstanding.
- **The ceiling path has never been reached on device**, and after this change it becomes
  reachable for the first time. Its unit coverage is real; its on-device behaviour is not.
- **A released watch can now live up to the hard ceiling.** That is intended for an opt-in
  diagnostic, but it is a longer-lived background thread than anything shipped so far, and
  it only occurs with Debug Logging enabled.
- **The stall window remains unexercised**, now across eight consecutive plans, and this
  change does not make it reachable for released watches.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-debug-observation-exit
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-debug-observation-exit_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-debug-observation-exit`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-debug-observation-exit-review-*.md
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
   scripts/orchestration/clear-finished syncthing-debug-observation-exit
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
   git add docs/review/syncthing-debug-observation-exit-review-*.md
   git commit -m "docs(review): record syncthing-debug-observation-exit review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-debug-observation-exit
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-debug-observation-exit` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed syncthing-debug-observation-exit
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-debug-observation-exit
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-debug-observation-exit_finalized
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
scripts/orchestration/finalize syncthing-debug-observation-exit
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-debug-observation-exit_finished
/tmp/sdh_ludusavi/syncthing-debug-observation-exit_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
