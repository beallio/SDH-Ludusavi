# Plan: Shorten Post Game Settle Gate And Fix Debug Gate (syncthing-settle-and-debug-gate)

## Context

### Problem Definition

Two independent defects, rolled into one plan because both live in the same two files.

**1. The post-game settle gate waits fifteen seconds for quiet that arrives in a tenth of
a second.**

`settled` requires the watched folder to have had no local index activity for
`DEFAULT_ACTIVE_WINDOW_SECONDS = 15.0`. Measured against a full day of Syncthing events on
`steamdeck`, every post-game backup produces one short burst and then nothing:

```text
23:25:46.551  idle -> scan-waiting -> scanning
23:25:46.629  FolderScanProgress
23:25:46.639  LocalIndexUpdated  seq=40691 items=45
23:25:46.653  scanning -> idle -> scan-waiting -> scanning
23:25:46.662  LocalIndexUpdated  seq=40722 items=31
23:25:46.662  scanning -> idle
```

Three independent runs, identical shape, spreads of 0.090s, 0.051s and 0.111s. Seven
activity bursts across the whole day, none longer than 0.111s. There is no trickle and
nothing arrives late.

On the 2026-08-11 23:25 run the peers had the save at 23:25:59.607, but `settled` could not
become true until 23:26:01.66 — fifteen seconds after the last index event — and
`SYNCTHING COMPLETE` published at 23:26:03.753. The wait was dead time, and it is currently
the sole reason completion takes 27 seconds instead of about 19.

**2. Debug extended observation is gated on a constant.**

It reads `logger.isEnabledFor(logging.DEBUG)`. `DiagnosticLogBuffer.setup_logging()`, called
from `SdhLudusaviService.__init__` (`service.py:139`), pins the plugin's loggers to `DEBUG`
permanently:

```python
for name in ("sdh_ludusavi", "pyludusavi"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
```

The Debug Logging toggle calls `_apply_log_level()`, which adjusts **only** `decky.logger`,
filtering at the sink. It never changes any `sdh_ludusavi.*` logger level. So the gate is
always true and has never been connected to the setting: a user who has never enabled debug
logging still gets extended watches.

### The second defect's unexplained half

On 2026-08-11 23:25 with Debug Logging on and an always-true gate, extended observation
still did not run — no transition lines after completion at 23:26:03.753, with two peers
holding 41 pending deletes. **That has no confirmed explanation.** This plan ships a gate
that is correct by construction plus the diagnostic needed to explain it on the next device
run. Do not guess at the cause and do not attempt to fix it here.

### Intended Outcome

Post-game completion stops waiting on a fifteen-second timer for a folder that went quiet
almost immediately, cutting `SYNCTHING UPLOADING` from roughly 17 seconds to roughly 8 on a
normal sync. Extended observation is gated on the real setting. Pre-game behaviour, the
completion rule, and the reported activity flags are unchanged.

### Modelled effect

Completion lands at `max(folder quiet, first peer confirmed) + ~2.1s` for the frontend's
three polls. This model reproduces the 23:25 run exactly: predicted 23:26:03.76, actual
23:26:03.753.

```text
capture        UPLOADING today (15s)    with a 3s settle gate
2026-08-11 23:25        17.1s                    8.7s
2026-08-11 22:34        16.6s                    7.6s
2026-08-11 11:15        16.8s                    8.3s
```

All three land near eight seconds because below roughly 6.5 seconds the settle gate stops
binding and first-peer confirmation takes over — three observations at Syncthing's ~2.1s
cadence. **Three seconds and five seconds therefore produce identical results.** Three is
chosen because it is already at that floor while still leaving roughly 30x margin over the
worst measured burst.

### Relevant Files

```text
py_modules/sdh_ludusavi/syncthing/_types.py     new constant
py_modules/sdh_ludusavi/syncthing/activity.py   compute_activity_status settled branch
py_modules/sdh_ludusavi/syncthing/watcher.py    settle window plumbing, debug gate
py_modules/sdh_ludusavi/service.py              start_watch call site, _debug_logging
tests/test_activity.py                          classifier tests
tests/test_watcher.py                           watcher and manager tests
tests/test_service.py                           service wiring
docs/specs/sdh_ludusavi_sync.md                 completion contract
docs/agent_conversations/                       session record
```

### Decisions Already Made

Implement these as stated; do not re-open them.

- **The short settle window applies to post-game watches only.** The same `settled` value
  gates the pre-game launch hold, where releasing early risks launching a game before a
  newer incoming save has landed — a data-loss risk, not a cosmetic one. Pre-game keeps the
  existing fifteen-second behaviour. Revisiting pre-game needs its own risk analysis.
- **Add a new constant; do not lower `DEFAULT_ACTIVE_WINDOW_SECONDS`.** That constant also
  prunes remote progress, prunes local activity, and drives the reported
  `local_change_recent`, `local_index_recent`, `sequence_change_recent` and
  `scan_progress_recent` fields. Lowering it would change incoming-transfer reporting, which
  currently works and is out of scope.
- **The reported `*_recent` fields keep the fifteen-second semantics.** Only the `settled`
  decision uses the short window. Every other term of `settled` — idle state, no active
  transfer, no active downloads, no remote progress, no pull errors, no watch error — is
  unchanged.
- **Gate debug observation on the persisted `debug_logging` setting**, threaded explicitly
  from the service, which already holds it at the `start_watch` call site
  (`service.py:175`). Do not read logger levels, do not import `decky` in the watcher, and
  do not add a new setting. Capture it at watch start; toggling mid-watch will not affect a
  running watch, which is acceptable and should be documented rather than engineered around.

**Slug used throughout this plan:** `syncthing-settle-and-debug-gate`

---

## Orchestration Contract

**Slug:** `syncthing-settle-and-debug-gate`

**Plan file:**

```text
docs/plans/2026-08-12_syncthing-settle-and-debug-gate.md
```

**Implementation branch:**

```text
feat/syncthing-settle-and-debug-gate
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/syncthing-settle-and-debug-gate_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/syncthing-settle-and-debug-gate_finalized
```

**Review notes:**

```text
docs/review/syncthing-settle-and-debug-gate-review-*.md
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
git checkout -b feat/syncthing-settle-and-debug-gate
```

Commit this plan first:

```bash
git add docs/plans/2026-08-12_syncthing-settle-and-debug-gate.md
git commit -m "docs(plan): add syncthing-settle-and-debug-gate implementation plan"
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

### Task 1 — Shorten the post-game settle gate

**Initially authorized. Stop for review after this task.**

Files in scope:

```text
py_modules/sdh_ludusavi/syncthing/_types.py
py_modules/sdh_ludusavi/syncthing/activity.py
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_activity.py
tests/test_watcher.py
```

`settled` is currently:

```python
settled = (
    normalized_state == "idle"
    and not update_in_progress
    and not local_activity.active_download_files
    and not remote_progress
    and runtime.pull_errors == 0
    and not runtime.watch_error
)
```

`update_in_progress` folds in the long-window recency flags, so `settled` cannot clear until
fifteen seconds after the last index event. The fix gives the settle decision its own local
recency evaluation without touching the reported flags.

1. Write the failing tests first:
   - a post-game watch whose folder went quiet 4 seconds ago, with a confirmed peer and an
     idle folder state, reports `settled=true`; today it reports false;
   - the same watch 2 seconds after the last index event still reports `settled=false`;
   - a **pre-game** watch is unaffected: it still requires the full fifteen seconds. This is
     the test that protects the launch gate and must fail if the short window is applied
     unconditionally;
   - the reported `local_change_recent`, `local_index_recent`, `sequence_change_recent` and
     `scan_progress_recent` fields keep their fifteen-second values while `settled` uses the
     short one — assert both in the same test so a future change cannot quietly couple them;
   - every other `settled` term still blocks: an active transfer, active download files,
     non-empty remote progress, a pull error, and a watch error each keep `settled=false`
     even when the folder has been quiet longer than the short window;
   - `prune_remote_progress` and `prune_local_activity` still use the fifteen-second window.
2. Record the observed failures before editing production code:

   ```bash
   ./run.sh uv run pytest tests/test_activity.py tests/test_watcher.py -q --no-cov
   ```
3. Add `POST_GAME_SETTLE_QUIET_WINDOW_SECONDS = 3.0` to `_types.py`, with a comment giving
   the evidence: measured post-backup local activity bursts spread 0.051s to 0.111s across
   seven captures, so three seconds is roughly 30x the worst observed burst, and values
   below about 6.5 seconds are equivalent because first-peer confirmation binds first.
4. Give `compute_activity_status()` a settle-specific quiet window parameter, defaulting to
   the existing `active_window_seconds` so any caller that does not pass it keeps today's
   behaviour. Compute short-window variants of the local recency terms for the `settled`
   decision only. Leave `update_in_progress` and every reported `*_recent` field on the long
   window.
5. Pass the short window from the watcher **only when `phase == "post_game"`**.
6. Change nothing else: not the completion rule, the confirmation window, the stall
   detector, either ceiling, the RPC sample key set, or any frontend file.
7. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/syncthing/_types.py py_modules/sdh_ludusavi/syncthing/activity.py py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_activity.py tests/test_watcher.py
   git commit -m "feat(syncthing): shorten the post-game settle gate"
   ```

Run `scripts/orchestration/mark-finished syncthing-settle-and-debug-gate` and exit. Task 2
is forbidden until a review note authorizes it.

### Task 2 — Gate debug observation on the debug setting

**Authorized only by a committed review note accepting Task 1. Stop for review after this
task.**

Files in scope:

```text
py_modules/sdh_ludusavi/service.py
py_modules/sdh_ludusavi/syncthing/watcher.py
tests/test_watcher.py
tests/test_service.py
```

1. Write the failing tests first:
   - a watch started with `debug_logging=False` does not select extended observation:
     `is_debug_extending_peer_completion` stays false after first-peer completion and
     `stop_watch()` stops it;
   - a watch started with `debug_logging=True` selects it, is left running by
     `stop_watch()`, and self-terminates once every peer finishes;
   - **the selection does not consult logger levels**: assert the false case still holds
     with the `sdh_ludusavi` logger explicitly set to `DEBUG`, which is its real runtime
     state. Without this, a reintroduced `isEnabledFor` check passes every other test —
     that is exactly how this defect survived review;
   - the service passes its `_debug_logging` value through to `start_watch()`;
   - one diagnostic line is emitted at latch containing the phase, the selection, and the
     connected relevant peer count, with no device IDs, folder paths, or raw payloads.
2. Record the observed failures:

   ```bash
   ./run.sh uv run pytest tests/test_watcher.py tests/test_service.py -q --no-cov
   ```
3. Add a `debug_logging: bool` parameter to `SyncthingWatchManager.start_watch()` and
   `SyncthingWatch`, defaulting to `False` so a caller that forgets it fails closed rather
   than giving every user extended watches.
4. Replace `logger.isEnabledFor(logging.DEBUG)` with the stored setting, and remove the
   `logging` import from `watcher.py` if nothing else needs it.
5. Pass `self._debug_logging` at the `service.py:175` call site.
6. Emit the diagnostic at INFO so it survives with Debug Logging off.
7. Rerun the focused command, then the full quality gates, then commit only this unit:

   ```bash
   git add py_modules/sdh_ludusavi/service.py py_modules/sdh_ludusavi/syncthing/watcher.py tests/test_watcher.py tests/test_service.py
   git commit -m "fix(syncthing): gate debug observation on the debug setting"
   ```

Run `scripts/orchestration/mark-finished syncthing-settle-and-debug-gate` and exit. Task 3
is forbidden until a review note authorizes it.

### Task 3 — Document both changes and record verification

**Authorized only by a committed review note accepting Task 2. Stop for final review after
this task.**

Files in scope:

```text
docs/specs/sdh_ludusavi_sync.md
docs/specs/custom_status_bar_ui.md
docs/agent_conversations/2026-08-12_syncthing-settle-and-debug-gate.json
```

1. Record the settle-gate split in both specs: post-game settling uses its own short quiet
   window, pruning and the reported recency flags keep the fifteen-second window, and
   pre-game settling is deliberately unchanged because it gates game launch. Include the
   measured burst spreads as the justification, and the fact that values below about 6.5
   seconds are equivalent because first-peer confirmation binds first.
2. Record the debug gate signal: the persisted `debug_logging` setting captured at watch
   start, and why logger levels are unsuitable — `setup_logging()` pins `sdh_ludusavi` to
   `DEBUG` permanently while the toggle only adjusts `decky.logger`.
3. No `README.md` change is expected. The user-facing meaning of `SYNCTHING COMPLETE` is
   unchanged and Debug Logging behaves as its description always claimed. Confirm that and
   say so in the session log rather than editing the file to no purpose.
4. Write the JSON session record with the date, objective, files modified, each task's RED
   proof, design decisions, the Task 1-2 commit hashes, the Task 3 commit subject, the
   review-note paths available through Task 2, exact validation results, and the deferred
   verification below. Record explicitly that extended observation not running on device on
   2026-08-11 despite an always-true gate remains **unexplained**, and that this plan ships
   a correct gate plus a diagnostic rather than a fix for it.
5. Run the documentation and static suites, then the full quality gates:

   ```bash
   ./run.sh uv run pytest tests/test_protocol.py tests/test_architecture.py tests/test_status_flow_diagram.py -q --no-cov
   ```
6. Commit only this unit:

   ```bash
   git add docs/specs/sdh_ludusavi_sync.md docs/specs/custom_status_bar_ui.md docs/agent_conversations/2026-08-12_syncthing-settle-and-debug-gate.json
   git commit -m "docs(syncthing): define the settle window and debug gate signals"
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

### 2. Prove the settle window is post-game only

With Task 1 complete and green, apply the short window unconditionally — pass it for
pre-game watches as well — and run:

```bash
./run.sh uv run pytest tests/test_activity.py tests/test_watcher.py -q --no-cov
```

Expected: the pre-game test **fails**. That test guards the launch gate, where an early
`settled` can release a game before a newer incoming save has landed. If nothing fails, the
pre-game path is untested and the most consequential risk in this plan is uncovered.

Restore and confirm green.

### 3. Prove the reported flags stayed on the long window

Still in Task 1, switch the reported `local_index_recent` field to the short window and
rerun the same command.

Expected: the test asserting both values in one place **fails**. Those fields are part of
the diagnostic surface and a silent coupling between them and the settle decision is exactly
what this task is structured to prevent.

### 4. Prove the debug gate reads the setting, not the logger

With Task 2 complete and green, restore `logger.isEnabledFor(logging.DEBUG)` in place of the
stored setting and run:

```bash
./run.sh uv run pytest tests/test_watcher.py tests/test_service.py -q --no-cov
```

Expected: the `debug_logging=False` case **fails**, because `setup_logging()` leaves the
`sdh_ludusavi` logger at `DEBUG` and the restored check returns true.

If it passes, the test is not reproducing the real runtime logger state — it must set the
`sdh_ludusavi` logger to `DEBUG` explicitly, because that is what the running plugin does. A
test that leaves the logger at its pytest default passes against both the correct and the
broken implementation, which is how this defect survived review.

### 5. Prove the conservative default

Still in Task 2, change the `debug_logging` default on `start_watch()` from `False` to
`True` and rerun. Expected: the `debug_logging=False` case fails. A default that fails open
would silently give every user extended watches, which is the defect being fixed.

### 6. Deferred and explicitly not verified

- **Device verification is required for both changes.** For the settle gate, the expected
  signature is `SYNCTHING COMPLETE` roughly 8 seconds after `SYNCTHING UPLOADING` rather
  than roughly 17, and handoff-to-complete near 19 seconds against the 27.4s baseline from
  2026-08-11 23:25. For the debug gate, read the new diagnostic line to establish whether
  extended observation was *selected*.
- **The second debug defect remains unexplained.** If the diagnostic shows extended
  observation was selected and transitions still stop at completion, the cause lies past the
  gate and needs its own plan.
- **The three-second window is calibrated against one game's save.** Wobbly Life's delta is
  roughly 1.4 MB across 111 files. A substantially larger save could scan for longer; no
  capture of that exists. The separate constant makes this cheap to revise if it ever
  bites.
- **The modelled timings are a model.** It reproduces the 2026-08-11 23:25 run exactly, but
  it has been validated against one capture, not many.
- **The stall window and both ceilings remain unexercised**, now across seven consecutive
  plans.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished syncthing-settle-and-debug-gate
```

This writes:

```text
/tmp/sdh_ludusavi/syncthing-settle-and-debug-gate_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer syncthing-settle-and-debug-gate`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/syncthing-settle-and-debug-gate-review-*.md
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
   scripts/orchestration/clear-finished syncthing-settle-and-debug-gate
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
   git add docs/review/syncthing-settle-and-debug-gate-review-*.md
   git commit -m "docs(review): record syncthing-settle-and-debug-gate review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished syncthing-settle-and-debug-gate
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer syncthing-settle-and-debug-gate` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed syncthing-settle-and-debug-gate
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize syncthing-settle-and-debug-gate
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/syncthing-settle-and-debug-gate_finalized
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
scripts/orchestration/finalize syncthing-settle-and-debug-gate
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/syncthing-settle-and-debug-gate_finished
/tmp/sdh_ludusavi/syncthing-settle-and-debug-gate_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
