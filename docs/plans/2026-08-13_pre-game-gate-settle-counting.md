# Plan: Separate Pre-Game Settle Counting From Display Status (pre-game-gate-settle-counting)

## Context

### The problem

The `pre-game-content-only-launch-gate` work (merged as `2ae9052`) made the backend
correctly report `settled=true` during a delete-only tail. It does not work end to end,
because the frontend discards that signal.

`src/controllers/syncthingMonitorMachine.ts` decides two unrelated things in one if/else
chain: which status the strip displays, and whether a sample counts toward settling. The
chain reads:

```ts
if (sample.downloading && phase !== "post_game") { newStatus = "downloading"; settledCount = 0; }
else if (sample.uploading)                       { newStatus = "uploading";   settledCount = 0; }
else if (sample.update_in_progress && phase !== "post_game")
                                                 { newStatus = "downloading"; settledCount = 0; }
else if (mutationObserved && sample.settled && ...) { settledCount++; ... }
```

Because the branches are exclusive, `update_in_progress` resets `settledCount` **before**
the settling branch is ever reached. During a delete tail the folder state is
`sync-preparing`, so `preparing` is true, so `update_in_progress` is true, so the counter
is reset on every sample and never reaches three. The launch gate never releases.

`update_in_progress` was deliberately left unchanged by the previous plan. That decision
was wrong, and it is why the measured 52.3s SIGSTOP hold is still 52.3s despite the
backend now being correct.

### Verified behaviour, measured through the real reducer

Ten scenarios were replayed through `transition()` on current `dev` and against the fix.
Signature format is `settledCount[*=completionObserved]:latestStatus` per sample.

```text
                          dev                                fix
PRE delete-tail x6        0:downloading (x6)                 1:idle 2:idle 3*:complete ...
PRE content-download x6   0:downloading (x6)                 unchanged
PRE content-need x6       0:downloading (x6)                 unchanged
PRE quiet x4              1:idle 2:idle 3*:complete          unchanged
PRE dl x2 then tail x4    0:downloading (x6)                 0:dl 0:dl 1:idle 2:idle 3*:complete
PRE tail2 dl2 tail3       0:downloading (x7)                 1:idle 2:idle 0:dl 0:dl 1:idle 2:idle 3*:complete
POST (4 scenarios)        —                                  all four identical to dev
```

Exactly three rows change, all pre-game delete-tail. The `PRE tail2 dl2 tail3` row is the
important safety one: when content appears partway through a tail, the counter drops back
to zero and has to re-earn all three samples, so an interrupted tail cannot be walked past.

Post-game is unchanged by construction, not by luck — the reset branch is already guarded
by `phase !== "post_game"`.

### Two decisions already made, do not revisit them

1. **A delete-only tail must not claim `DOWNLOADING`.** Nothing is being downloaded. With
   content present the strip should stay quiet and then publish `COMPLETE`. Note that
   `newStatus = "idle"` does not publish anything in the pre-game branch, so the strip
   simply holds its previous value until `COMPLETE`.
2. **Keep the three-sample confirmation.** It is the anti-flap guard that stops one
   misread sample from releasing the launch gate. Roughly 4–6s at the current sample
   cadence, against 52.3s measured today.

### The coverage gap that let this ship

The full frontend suite — 335 tests — passes identically against the broken code and the
fix. **No existing test discriminates.** This is why the defect shipped, and it is why
Task 1 exists and must come first.

The backend test `tests/test_watcher.py::test_pre_game_launch_gate_releases_during_delete_only_tail`
reads like an end-to-end control but drives `manager.poll_watch()` and asserts on backend
booleans only. It passed for the right reason and still missed this entirely. Do not treat
a backend replay as proof that the gate releases.

### Relevant files

```text
src/controllers/syncthingMonitorMachine.ts        the if/else chain, around line 200
src/controllers/syncthingMonitorMachine.test.ts   reducer tests
tests/test_watcher.py                             backend replay that overstated its reach
docs/specs/sdh_ludusavi_sync.md                   sync behaviour spec
```

### Practical note

If a commit fails because a dependency is newer than the machine's uv cutoff, retry with
`UV_FROZEN=1` in the environment.

**Slug used throughout this plan:** `pre-game-gate-settle-counting`

---

## Orchestration Contract

**Slug:** `pre-game-gate-settle-counting`

**Plan file:**

```text
docs/plans/2026-08-13_pre-game-gate-settle-counting.md
```

**Implementation branch:**

```text
feat/pre-game-gate-settle-counting
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/pre-game-gate-settle-counting_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/pre-game-gate-settle-counting_finalized
```

**Review notes:**

```text
docs/review/pre-game-gate-settle-counting-review-*.md
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
git checkout -b feat/pre-game-gate-settle-counting
```

Commit this plan first:

```bash
git add docs/plans/2026-08-13_pre-game-gate-settle-counting.md
git commit -m "docs(plan): add pre-game-gate-settle-counting implementation plan"
```

---

## Implementation Tasks

Three tasks. **Implement exactly one task per round.** Finish a task, run the quality gates,
commit, run `mark-finished`, and exit. Each is reviewed before the next begins.

There is no halt-and-report instruction anywhere in this plan.

---

### Task 1 — Reducer tests first, red against current code

Write these **before** touching production code, and confirm they fail. This is the whole
reason the defect shipped: the existing 335 frontend tests do not distinguish working from
broken here.

Add to `src/controllers/syncthingMonitorMachine.test.ts`, driving `transition()` directly
the way the existing tests in that file do. Seed state with `step: "watching"` and
`mutationObserved: true`, since a real watch has observed a mutation before it settles.

The delete-tail sample to replay is what the backend now emits for `sync-preparing` with
content present:

```ts
{ timestamp_unix: n, folder_state: "sync-preparing", downloading: false, uploading: false,
  update_in_progress: true, status: "PREPARING", settled: true }
```

Required cases:

1. **Releases** — pre-game, six delete-tail samples: `settledCount` reaches 3,
   `completionObserved` becomes true, `latestStatus` ends `"complete"`. **Fails today**
   (counter stays 0 forever).
2. **No false download claim** — in that same sequence, `latestStatus` is never
   `"downloading"`. **Fails today.**
3. **Content still blocks** — pre-game, six samples with `downloading: true`,
   `settled: false`, `folder_state: "syncing"`: never settles, stays `"downloading"`.
   Passes today; it is the safety guard.
4. **Content mid-tail resets the count** — pre-game sequence tail, tail, download,
   download, tail, tail, tail. Assert the count reaches 2, drops to 0 when content
   appears, then re-earns 1, 2, 3. **Fails today.** This is the most important test in the
   plan: it proves an interrupted tail cannot be walked past.
5. **Post-game unchanged** — replay the delete tail and a content download in `post_game`
   with `handoffActivated: true`, and assert the same signatures the code produces today.
   These must pass both before and after; they are the regression guard for the phase
   boundary.

Use distinct timestamps per sample. Identical timestamps are skipped by the reducer's
duplicate-suppression, which would make a sequence silently shorter than it looks.

Run the suite, record the failures verbatim in the session log, and confirm cases 3 and 5
pass while 1, 2 and 4 fail. Commit the tests on their own.

---

### Task 2 — Split display from counting

In `src/controllers/syncthingMonitorMachine.ts`, replace the fused chain with a display
decision followed by an independent counting decision:

```ts
let newStatus: WatchLatestStatus = "idle";
if (sample.downloading && state.phase !== "post_game") {
  newStatus = "downloading";
} else if (sample.uploading) {
  newStatus = "uploading";
} else if (sample.update_in_progress && !sample.settled && state.phase !== "post_game") {
  newStatus = "downloading";
}

if (
  nextState.mutationObserved &&
  sample.settled &&
  (state.phase !== "post_game" || state.handoffActivated)
) {
  nextState.settledCount++;
  if (nextState.settledCount >= 3) {
    newStatus = "complete";
    nextState.completionObserved = true;
    nextState.step = "complete";
    effects = { ...effects, resolveQuiescence: "settled" };
  }
} else {
  nextState.settledCount = 0;
}
```

Two things are doing work here and both are required:

- Removing `settledCount = 0` from the first three branches is what lets a delete tail
  settle. It is safe because `settled` and `downloading`/`uploading` are mutually
  exclusive in the backend — `settled` requires `not active_transfer` — so whenever the old
  code reset via those branches, `sample.settled` is false and the trailing `else` resets
  anyway.
- Adding `!sample.settled` to the third branch is what stops the strip claiming
  `DOWNLOADING` during a delete-only tail.

Add a comment recording why the two decisions are separate, so the chain does not get
re-fused later.

Do not change `update_in_progress` in the backend, do not change the three-sample
threshold, and do not touch the post-game branch.

All five Task 1 cases must now pass. Record the before/after suite output.

---

### Task 3 — Close the false-confidence gap in the backend replay

`tests/test_watcher.py::test_pre_game_launch_gate_releases_during_delete_only_tail` asserts
that the backend publishes three distinct settled samples. That is true and was never in
question; the problem is that its name claims the launch gate releases, which it does not
demonstrate.

Do both of these:

1. Rename it to say what it actually proves — that the backend *publishes* settled samples
   during a delete-only tail — and add a comment pointing at the reducer test from Task 1
   as the test that covers the gate actually releasing. Do not weaken its assertions.
2. Record the contract in `docs/specs/sdh_ludusavi_sync.md`: the strip's displayed status
   and the settle count are independent decisions; a delete-only tail displays nothing and
   then publishes `COMPLETE`; settling requires three consecutive content-complete samples;
   and post-game is unaffected because the reset is phase-guarded. Keep it to prose a
   maintainer can act on — this is a spec, not release notes.

No production behaviour changes in this task.

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

Every step below must be able to fail. Record the command's actual output — pass/fail
tallies, assertion text, exit codes — not a conclusion that it passed.

### The gate must be proven before it is trusted

Task 1 is itself the proof, and it only counts if you run it against unmodified production
code and watch it fail. If cases 1, 2 and 4 pass before Task 2 lands, the tests are not
testing anything — fix them before continuing. Record the failure output verbatim.

### Mutation checks

Do each in the round that implements the task.

**Task 2, mutation A — re-fuse the counting.** Put `nextState.settledCount = 0;` back into
the `update_in_progress` branch and run the suite. Cases 1 and 4 must go red. Restore and
show green.

**Task 2, mutation B — remove the display guard.** Drop `!sample.settled` from the third
branch, leaving the split in place. Case 2 must go red while cases 1 and 4 stay green. This
separates the two halves of the change; if case 2 stays green, it is not testing the
display claim.

Both mutations matter. A single mutation that reverts the whole hunk would hide which half
each test covers.

### Full gates

```bash
scripts/orchestration/run-quality-gates
git status --short
```

Record the vitest and pytest tallies, and the ruff, `ty`, typecheck and build results.

Note for context, not as a pass condition: the frontend suite reports 335 passed against
both the broken and fixed code today. A green suite alone therefore proves nothing about
this defect. Report the new test count explicitly so the delta is visible.

### Deferred — on-device verification

**Not performed as part of this plan.** It needs a Steam Deck or Legion Go S with the built
plugin installed, Syncthing running with peers connected, and a backup folder carrying a
pending delete backlog.

When it runs, the pass signature is:

- confirm the installed build first with
  `grep '"version"' /home/deck/homebrew/plugins/SDH-Ludusavi/plugin.json`;
- launch a tracked game while `needDeletes` is non-zero on the backup folder;
- the game starts within a few seconds rather than tens of seconds;
- the strip does **not** show `SYNCTHING DOWNLOADING` during the delete tail;
- the pre-game quiescence diagnostic lines show `need_content_items=0` alongside a
  non-zero `need_deletes`;
- the restored save is correct — confirm the game loads the expected save, not an older one.

A restore of stale or partial content is a correctness regression and outranks the latency
win. If it happens, report it rather than tuning the threshold.

### Explicitly not verified by this plan

- Real device behaviour. Every step here is reducer-level or backend unit coverage.
- Whether three samples is the right threshold. It is retained deliberately as the existing
  anti-flap guard, not measured.
- The pre-existing gaps an independent review raised against the prior merge and which this
  plan does not address: the folder-status read that precedes event-cursor seeding during
  initialization, poll failures retaining stale runtime rather than failing closed, and
  receive-only folder divergence being invisible to `receive_needed`. All three predate this
  change and remain open.
- Per-game path scoping of the pre-game query, which would make delete activity structurally
  irrelevant rather than filtered. That is a separate architectural change and is not
  started here.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished pre-game-gate-settle-counting
```

This writes:

```text
/tmp/sdh_ludusavi/pre-game-gate-settle-counting_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer pre-game-gate-settle-counting`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/pre-game-gate-settle-counting-review-*.md
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
   scripts/orchestration/clear-finished pre-game-gate-settle-counting
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
   git add docs/review/pre-game-gate-settle-counting-review-*.md
   git commit -m "docs(review): record pre-game-gate-settle-counting review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished pre-game-gate-settle-counting
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer pre-game-gate-settle-counting` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed pre-game-gate-settle-counting
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize pre-game-gate-settle-counting
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/pre-game-gate-settle-counting_finalized
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
scripts/orchestration/finalize pre-game-gate-settle-counting
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/pre-game-gate-settle-counting_finished
/tmp/sdh_ludusavi/pre-game-gate-settle-counting_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
