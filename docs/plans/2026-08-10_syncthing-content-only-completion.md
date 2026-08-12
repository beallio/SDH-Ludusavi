# Plan: Gate Syncthing Completion on Content Only (syncthing-content-only-completion)

## Context

### Problem Definition

Post-game `SYNCTHING COMPLETE` currently waits for peers to finish deleting old Ludusavi
snapshots. That is housekeeping, not save propagation, and it delays or prevents the
status the user actually wants.

A peer reports three independent need counters. `needBytes` and `needItems` mean the peer
is **missing content** — the new save is not there yet. `needDeletes` means the peer still
holds files the Deck has since removed; it already has every byte of the new backup and is
pruning stale snapshots. Gating completion on `needDeletes` gates on cleanup.

The 2026-08-10 21:29 Wobbly Life run on the Steam Deck (`steamdeck`, plugin
`0.4.4-dev.gccb9ef7`, three connected peers) separates the two cleanly:

```text
21:29:08.417  handoff activated
21:29:16.632  SYNCTHING UPLOADING            (on FolderCompletion evidence)
21:29:17.886  incomplete_peers=3  needed_bytes=1406739 needed_items=111 needed_deletes=117
21:29:32.538  incomplete_peers=2  needed_bytes=0       needed_items=0   needed_deletes=46
...
21:34:06.017  incomplete_peers=2  needed_bytes=0       needed_items=0   needed_deletes=4
21:34:08.561  LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE
```

Content reached every peer 24.1 seconds after handoff. The following four and a half
minutes were snapshot pruning, and the watch ended at the 300-second frontend ceiling four
deletes short of finishing. The user was shown an incomplete-upload outcome for a backup
that had been safely propagated for over four minutes.

There is a second, non-obvious reason a narrower predicate is required. Syncthing's
`completion` percentage is itself dragged down by pending deletes: the 2026-08-09 Legion Go
capture recorded a peer at `completion=95` with `needBytes=0`, `needItems=0`,
`needDeletes=12`. Dropping only the `need_deletes > 0` clause from
`peer_completion_is_incomplete()` would therefore change nothing for that peer, because the
`completion < 100` clause would still hold it incomplete for the same underlying reason.
Both clauses have to go.

### Intended Outcome

A connected relevant peer counts as behind only when it is missing content. Pending deletes
and the completion percentage remain fully visible in the transition diagnostics but stop
gating status. On the captured run this would have published `SYNCTHING COMPLETE` at
roughly 21:29:32 — about 24 seconds after handoff, on evidence.

### Relevant Files

```text
py_modules/sdh_ludusavi/syncthing/_types.py     peer_completion_is_incomplete, summarize_peer_completions,
                                                PeerCompletionDiagnostics
py_modules/sdh_ludusavi/syncthing/watcher.py    _log_peer_completion_transition log line
tests/test_activity.py                          classification table, reducer tests
tests/test_watcher.py                           diagnostics and stall tests
docs/specs/sdh_ludusavi_sync.md                 completion contract
docs/specs/custom_status_bar_ui.md              activity source description
README.md                                       user-facing status definitions
```

### Decisions Already Made

Implement these as stated; do not re-open them.

- The gating predicate becomes `need_bytes > 0 or need_items > 0`. The
  `completion < 100` and `need_deletes > 0` clauses are both removed, for the reason given
  above.
- Deletes and completion percentage stay in the diagnostics. Losing them would remove the
  only visibility into a slow-pruning peer.
- **The stall window and both ceilings keep their current values**
  (`OUTBOUND_STALL_WINDOW_SECONDS = 90.0`, `POST_GAME_WATCH_HARD_CEILING_SECONDS = 900.0`,
  `POST_GAME_WATCH_HARD_CEILING_MS = 300_000`). Once the deletes tail no longer gates, the
  captured run settles in about 24 seconds and approaches none of them. Changing them now
  would be tuning against a workload that no longer exists. Record this decision and the
  evidence for it; do not edit the constants.

**Slug used throughout this plan:** `syncthing-content-only-completion`

---

## Orchestration Contract

**Slug:** `syncthing-content-only-completion`

**Plan file:**

```text
docs/plans/2026-08-10_syncthing-content-only-completion.md
```

**Implementation branch:**

```text
feat/syncthing-content-only-completion
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-content-only-completion_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-content-only-completion_finalized
```

**Review notes:**

```text
docs/review/syncthing-content-only-completion-review-*.md
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
git checkout -b feat/syncthing-content-only-completion
```

Commit this plan first:

```bash
git add docs/plans/2026-08-10_syncthing-content-only-completion.md
git commit -m "docs(plan): add syncthing-content-only-completion implementation plan"
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
6. `STATUS: APPROVED` is reserved for human approval after Task 3 and all prior task
   reviews are complete.
7. If a review note is missing, ambiguous, skips a task number, or authorizes more than one
   task, stop without changing files and report the gate violation.

---

## Implementation Tasks

### Task 1 — Gate peer completeness on missing content only

**Initially authorized. Stop for review after this task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/_types.py
tests/test_activity.py
```

1. Write the failing tests first. The existing classification table in
   `tests/test_activity.py` is parametrized over
   `(completion, need_bytes, need_items, need_deletes, expected_uploading)`. Two of its rows
   assert the behaviour this plan removes and **must** have their expectations changed:

   ```text
   (93.56119493792454, 0, 0, 0, True)   ->  False
   (100.0,             0, 0, 19, True)  ->  False
   ```

   This is an authorized expected-value change, required by this plan, for the reason in
   the Context section: a percentage below 100 and a positive delete count both mean
   "pruning outstanding", not "content missing". The scope-discipline rule against editing
   expected values does not apply to these two rows. Record the change and its rationale in
   the session log during Task 3. Do **not** change any other row — in particular
   `(100.0, 8_942_011, 0, 0, True)` and `(100.0, 0, 32, 0, True)` must stay `True`, and
   `(100.0, 0, 0, 0, False)` must stay `False`.

2. Add a row proving the exact device-captured state is now complete:
   `(95.0, 0, 0, 12, False)` — the 2026-08-09 peer that was held incomplete solely by
   pruning. Add a row proving content still gates when the percentage looks healthy:
   `(100.0, 1, 0, 99, True)`.

3. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_activity.py -q --no-cov
   ```

4. Change `peer_completion_is_incomplete()` to:

   ```python
   return completion is not None and (completion.need_bytes > 0 or completion.need_items > 0)
   ```

   Add a comment stating why the percentage clause is gone: Syncthing's `completion` is
   reduced by pending deletes, so retaining it would re-introduce delete gating through the
   back door.

5. Change nothing else. `summarize_peer_completions()` is Task 2's subject; leave it alone
   this round even though it calls this predicate.

6. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/_types.py tests/test_activity.py
   git commit -m "fix(syncthing): gate peer completeness on missing content only"
   ```

Run `scripts/orchestration/mark-finished syncthing-content-only-completion` and exit.
Task 2 is forbidden until a review note authorizes it.

### Task 2 — Keep deletes and completion visible in diagnostics

**Authorized only by a committed review note accepting Task 1. Stop for review after this
task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/_types.py
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_watcher.py
```

`summarize_peer_completions()` accumulates `needed_bytes`, `needed_items`, and
`needed_deletes` **only for peers the predicate calls incomplete**. After Task 1 a
deletes-only peer is no longer incomplete, so its pending deletes silently vanish from the
diagnostics — the opposite of the intent, and it would remove the only visibility into a
slow-pruning peer.

1. Write the failing tests first:
   - a peer with `need_deletes > 0` and zero content need is **not** counted in
     `incomplete_peers`, but its deletes **are** reported in `needed_deletes`;
   - a new `peers_pending_deletes` count reports how many connected relevant peers have
     deletes outstanding, independent of the gate;
   - `needed_bytes` and `needed_items` continue to sum over content-incomplete peers only;
   - the transition log line contains the new field and still contains no device IDs,
     folder paths, or raw payloads;
   - a peer with neither content need nor deletes contributes to none of the counts.
2. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_watcher.py -q --no-cov
   ```
3. Accumulate `needed_deletes` across **all** connected relevant peers rather than only
   incomplete ones, add `peers_pending_deletes` to `PeerCompletionDiagnostics`, and extend
   the `_log_peer_completion_transition()` format string to include it.
4. Leave the stall detector's `aggregate_outstanding_need` definition alone. It is only
   consulted while `incomplete_peers > 0`, which after Task 1 means content is outstanding,
   so deletes can no longer hold a watch open through it.
5. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/_types.py py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_watcher.py
   git commit -m "feat(syncthing): report pending deletes without gating completion"
   ```

Run `scripts/orchestration/mark-finished syncthing-content-only-completion` and exit.
Task 3 is forbidden until a review note authorizes it.

### Task 3 — Document the contract and record verification

**Authorized only by a committed review note accepting Task 2. Stop for final review after
this task.**

Files in scope:

```text
README.md
docs/specs/sdh_ludusavi_sync.md
docs/specs/custom_status_bar_ui.md
docs/agent_conversations/2026-08-10_syncthing-content-only-completion.json
```

1. Update the user-facing definition of **Syncthing Complete** in `README.md`. It currently
   says every connected device has reported no outstanding *need*; it must say every
   connected device that shares the folder has **received the backup**, and state plainly
   that the plugin does not wait for those devices to finish deleting older snapshots.
   Preserve the existing caveat that disconnected or offline devices are not covered.
2. Update both specs: the gating predicate is content-only; `needDeletes` and the
   completion percentage are reported for observability but never gate; and record the
   Syncthing behaviour that forced this — the percentage is itself reduced by pending
   deletes, evidenced by the `completion=95 need=0/0/12` capture.
3. Record the decision to leave the stall window and both ceilings unchanged, with the
   reasoning from the Context section: with the deletes tail no longer gating, the captured
   run settles in roughly 24 seconds and approaches none of them.
4. Write the JSON session record with the date, objective, files modified, each task's RED
   proof, design decisions, the Task 1-2 commit hashes, the Task 3 commit subject, the
   review-note paths available through Task 2, exact focused and full validation results,
   the authorized classification-table row changes from Task 1 with their rationale, and
   the deferred verification named below. Do not attempt a self-referential Task 3 hash.
5. Run the documentation and static suites, then the full quality gates:

   ```bash
   ./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py -q --no-cov
   ```
6. Commit only this unit:

   ```bash
   git add README.md docs/specs/sdh_ludusavi_sync.md docs/specs/custom_status_bar_ui.md docs/agent_conversations/2026-08-10_syncthing-content-only-completion.json
   git commit -m "docs(syncthing): define completion as content received"
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
"none". Report actual output — tallies, counter values, timestamps — not conclusions.

### 1. Automated acceptance

```bash
scripts/orchestration/run-quality-gates
```

Record the frontend test count, the pytest count, and the coverage percentage. A drop in
either count against the previous round is a failure to investigate.

### 2. Prove the Task 1 gate by mutation

With Task 1 complete and green, restore the removed `completion.need_deletes > 0` clause to
`peer_completion_is_incomplete()`, then run:

```bash
./run.sh uv run pytest tests/test_activity.py -q --no-cov
```

Expected: the `(100.0, 0, 0, 19, …)` and `(95.0, 0, 0, 12, …)` rows **fail**. Record the
failing parametrised ids. Restore the content-only predicate and confirm green.

Repeat with the `completion.completion < 100` clause restored instead. Expected: the
`(93.56119493792454, 0, 0, 0, …)` and `(95.0, 0, 0, 12, …)` rows fail. If restoring the
percentage clause alone changes nothing, the tests are not pinning the second half of the
fix — add a row that does before continuing.

### 3. Prove the Task 2 diagnostics by mutation

With Task 2 complete and green, revert `needed_deletes` accumulation to the incomplete-only
branch, then run:

```bash
./run.sh uv run pytest tests/test_watcher.py -q --no-cov
```

Expected: the deletes-visibility test **fails** because a deletes-only peer reports
`needed_deletes=0`. Restore and confirm green.

### 4. Negative control — replay the captured device sequence

This must run **after** steps 2 and 3. Add a test (or extend an existing watcher test) that
feeds the real 2026-08-10 21:29 counter sequence through the watcher and asserts the
transition to settled happens at the content boundary, not the pruning boundary:

```text
incomplete_peers=3  needed_bytes=1406739 needed_items=111 needed_deletes=117   -> uploading
needed_bytes=0      needed_items=0       needed_deletes=46                     -> settled
needed_bytes=0      needed_items=0       needed_deletes=4                      -> still settled
```

The middle row is the whole point of this plan: under the old predicate it was `uploading`,
and a test that passes with either predicate is not a control. Confirm it fails against the
pre-Task-1 predicate before trusting it.

### 5. Deferred and explicitly not verified

- **A real post-game device run is deferred.** The expected sequence to confirm on a
  prerelease is `SYNCTHING UPLOADING` while `needed_bytes`/`needed_items` fall, then
  `SYNCTHING COMPLETE` once they reach zero, with `needed_deletes` still non-zero in the
  final transition line and no `LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE`. On the
  captured run that boundary was 24.1 seconds after handoff.
- **The stall window and ceilings are unchanged and unexercised by this plan.** They were
  calibrated against a workload where deletes gated completion. Whether they suit the
  content-only workload is unknown and untested; revisit only with a run that actually
  approaches them.
- **No frontend change is made.** `syncthing_upload_incomplete` still exists and can still
  fire; this plan only makes it far less likely by removing the delete gate.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-content-only-completion
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-content-only-completion_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-content-only-completion`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-content-only-completion-review-*.md
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
   scripts/orchestration/clear-finished syncthing-content-only-completion
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
   git add docs/review/syncthing-content-only-completion-review-*.md
   git commit -m "docs(review): record syncthing-content-only-completion review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-content-only-completion
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-content-only-completion` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed syncthing-content-only-completion
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-content-only-completion
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-content-only-completion_finalized
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
scripts/orchestration/finalize syncthing-content-only-completion
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-content-only-completion_finished
/tmp/sdh_ludusavi/syncthing-content-only-completion_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
