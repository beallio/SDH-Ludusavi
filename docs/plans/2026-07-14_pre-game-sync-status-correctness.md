# Plan: Fix Pre-Game Sync Gating and BrowserView Status Messages (pre-game-sync-status-correctness)

## Context

### Problem Definition

The current development build can report contradictory pre-game state and can resume a
game while the watched Ludusavi backup folder is still receiving Syncthing changes. The
captured `steamdeck-legos` log demonstrates the sequence:

1. the pre-game watcher publishes `syncthing_downloading`;
2. `check_game_start` finishes with `skipped/local_current` and the status surface
   replaces the active transfer with `has_backup` (`GAME SAVE UP TO DATE`);
3. the launch-gate lease is released and the process resumes;
4. the watcher immediately publishes `syncthing_downloading` again and continues doing
   so while the game is running.

That is both a BrowserView ordering defect and a save-safety race. The save preview was
computed while the backup folder was changing, so `local_current` cannot be trusted as
the final launch decision until the incoming activity settles and the preview is rerun.
The 900 ms `has_backup` dwell also applies indiscriminately to pre-game results even
though it was introduced to make the post-game backup-to-Syncthing handoff readable.

The same logs expose two additional status-contract defects:

- `SAVE CONFLICT` auto-hides after two seconds even though the conflict modal remains
  open. Dismissing the modal then maps the deliberate `conflict_unresolved` skip to the
  generic amber `UNKNOWN` message.
- the pre-game state machine republishes `syncthing_downloading` for each distinct poll
  timestamp even when the semantic status has not changed. The BrowserView already
  avoids a same-status `LoadURL`, but the redundant surface publications still produce
  log noise and needless context/bounds/timer work.

The intended behavior is:

- an initialized idle pre-game watch adds no launch delay;
- once relevant pre-game Syncthing activity has been observed, the renewable pause lease
  remains held until the watched folder reaches the existing three-sample settled
  threshold or a bounded safety failure occurs;
- after observed activity settles, publish `VERIFYING GAME SAVE` and rerun
  `check_game_start` before deciding whether to restore, prompt for conflict, report the
  save current, or resume the game;
- an active pre-game Syncthing status cannot be replaced by a stale
  `GAME SAVE UP TO DATE`, while the existing 900 ms post-game backup-result dwell remains
  intact;
- `SAVE CONFLICT` stays visible for the lifetime of the modal, and dismissal shows
  `SYNC SKIPPED — CONFLICT UNRESOLVED` in amber for the normal result duration;
- pre-game transfer statuses publish only on semantic transitions, not on every poll;
- the approved merge is pushed to `origin/dev` and the exact merged commit is published
  through the existing development-release workflow as a new immutable `0.3.6` dev
  prerelease.

### Architecture Overview

Keep the existing ownership boundaries:

- `src/controllers/syncthingMonitorMachine.ts` remains the pure transition model. Extend
  it to model pre-game active-to-settled progress and expose effects that resolve a
  pre-game quiescence waiter. This is also the correct place to deduplicate semantic
  pre-game status transitions.
- `src/controllers/syncthingMonitor.ts` remains responsible for watch allocation,
  polling, cancellation, timeouts, and promise lifetimes. Extend the opaque
  `SyncthingWatchSession` with a pre-game-only bounded wait method; do not expose watch
  IDs or mutable machine state to the lifecycle controller.
- `src/controllers/gameLifecycleController.tsx` remains the coordinator for the launch
  pause lease and lifecycle RPCs. It waits only when the game is actually launch-gated,
  reruns the start check only when the watcher reports that observed activity settled,
  and routes failures through the existing status/toast cleanup paths.
- `src/controllers/gameLifecycleDecision.ts` remains the pure decision boundary for
  converting the quiescence outcome and conflict dismissal into commands. Do not embed
  user-visible failure policy in timer callbacks.
- `src/surfaces/autoSyncStatusSurface.tsx` remains the publication precedence and timer
  owner. Give completion calls explicit lifecycle provenance so the 900 ms dwell can be
  restricted to the post-game `backed_up` handoff and a pre-game `local_current` result
  can be suppressed while a Syncthing transfer is visibly active.
- `src/surfaces/autoSyncStatusRenderer.tsx` and `src/types/index.ts` own the new explicit
  unresolved-conflict kind, copy, color, icon, and auto-hide contract. The existing
  BrowserView creation, same-status navigation deduplication, bounds, and reveal logic
  remain unchanged.

No backend RPC or Syncthing wire-format change is needed. The frontend already receives
folder-scoped `uploading`, `downloading`, `update_in_progress`, `settled`, status, and
timestamp fields from the existing watcher API.

### Core Data Structures

- Add a discriminated pre-game wait result such as `PreGameQuiescenceResult` with enough
  information to distinguish:
  - initialized and idle with no observed activity;
  - observed activity that reached the settled threshold;
  - watch unavailability before activity;
  - timeout/failure after activity began;
  - cancellation or supersession/staleness.
  Do not reduce these cases to a boolean; the lifecycle safety policy differs between
  benign absence and an interrupted active transfer.
- Extend `SyncthingWatchSession` with one pre-game wait operation. Calling it on a
  post-game session must return a typed stale/unavailable result or reject immediately;
  it must never activate post-game handoff behavior.
- Reuse `WatchMachineState.activityObserved`, `settledCount`, `latestStatus`, and
  `completionObserved`. Set the mutation/activity state needed for pre-game settlement
  instead of inventing a second polling state machine.
- Add a separate quiescence-resolution effect/promise rather than reusing the current
  first-valid-sample readiness promise. Initialization and safe settlement are different
  milestones.
- Add `conflict_unresolved` to `AutoSyncStatusKind`. Preserve `conflict` as the modal's
  active warning state; the two kinds intentionally have different auto-hide behavior.
- Add lifecycle provenance to status completion options (`lifecycle_start` versus
  `lifecycle_exit`) so dwell/precedence decisions are explicit and testable. Do not infer
  phase from game names, timing, or unrelated result text.

### Public Interfaces and Behavioral Contracts

- Preserve all backend RPC names and result shapes, the Syncthing activity sample wire
  format, persisted settings, BrowserView owner API, and Decky lifecycle registration.
- Preserve the current pause-lease renewal/watchdog design. Any quiescence wait and the
  second `check_game_start` call must execute under `PauseLeaseHandle.runProtected()` so
  lease loss cancels the protected sequence rather than silently allowing a restore
  after resume.
- Use the existing 120-second frontend watch duration as the upper bound for an observed
  pre-game transfer. Do not create an unbounded modal or promise. A timeout or polling
  failure after activity began must cancel the watch, publish `UNABLE TO SYNC`, emit one
  failure toast explaining that launch verification could not safely complete, skip
  automatic restore/conflict action, and release the game through the existing `finally`
  cleanup so it cannot remain permanently paused.
- Watch allocation failure/unavailability before any relevant activity remains benign and
  preserves the current Ludusavi-only launch decision. In particular,
  `no_connected_peers` before activity must not create a new launch warning.
- If a valid initialized sample is already idle and no activity has been observed, the
  quiescence wait returns immediately and the original `check_game_start` result is used;
  do not run every launch check twice.
- If activity was observed and then settled, ignore the earlier check result, republish
  `checking` with `lifecycle_start` provenance, rerun `check_game_start`, and evaluate only
  the fresh result. Recheck staleness after every awaited boundary.
- Preserve the existing conflict resolution action animation: `keep_local` publishes
  `backing_up`, and `restore_backup` publishes `restoring` before its RPC.
- Preserve the 900 ms dwell only for a successful post-game `backed_up` result before
  pending/uploading Syncthing handoff. Pre-game `local_current`, `restored`, or other
  results must not delay active Syncthing status.
- Do not change BrowserView status dimensions, CSS animation, navigation/reveal behavior,
  or the backend folder-isolation rules delivered by the preceding feature.

### Dependency Requirements

No Python, TypeScript, npm, pnpm, Decky, Syncthing, or system dependency changes are
required. Use the existing fake timers, mocked RPCs, transition tests, and launch-lease
harness. Keep all generated caches and temporary state under `/tmp/sdh_ludusavi` and run
project tooling through `./run.sh`.

### Scope Boundaries

- Do not address updater/WSRouter reload tasks, duplicate update checks, unrelated Decky
  logs, or backend activity classification in this branch.
- Do not add a second overlay, toast routine progress, or replace the BrowserView.
- Do not change stable-release metadata or create a stable tag. This request authorizes
  one development prerelease only, using the existing `0.3.6` base-version guard and
  GitHub Actions publisher after approval and merge.
- On-device verification is deferred until the new development prerelease is published;
  it must not block code review, merge, or release publication.

**Slug used throughout this plan:** `pre-game-sync-status-correctness`

---

## Orchestration Contract

**Slug:** `pre-game-sync-status-correctness`

**Plan file:**

```text
docs/plans/2026-07-14_pre-game-sync-status-correctness.md
```

**Implementation branch:**

```text
feat/pre-game-sync-status-correctness
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/pre-game-sync-status-correctness_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/pre-game-sync-status-correctness_finalized
```

**Review notes:**

```text
docs/review/pre-game-sync-status-correctness-review-*.md
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
git checkout -b feat/pre-game-sync-status-correctness
```

Commit this plan first:

```bash
git add docs/plans/2026-07-14_pre-game-sync-status-correctness.md
git commit -m "docs(plan): add pre-game-sync-status-correctness implementation plan"
```

---

## Implementation Tasks

### 1. Establish all regression fences first (RED)

Write the failing tests before changing production behavior. Keep the RED failures
focused and record the expected failure names/output in the session log.

1. In `src/controllers/syncthingMonitorMachine.test.ts`, add tests proving:
   - a pre-game download/upload/update sample records activity and does not resolve the
     quiescence milestone;
   - three distinct settled samples after observed pre-game activity resolve completion;
   - repeated downloading samples with new timestamps publish once, while a transition
     from downloading to uploading publishes the new status;
   - an idle sample resets the semantic latest status so a later new transfer can publish;
   - cancellation or failure after activity resolves the waiter as unavailable rather
     than leaving it pending.
2. In the focused `src/controllers/syncthingMonitor.*.test.ts` suites, add session-level
   tests proving:
   - an initialized idle pre-game watch returns immediately;
   - an active pre-game wait remains pending through activity and fewer than three settled
     samples, then resolves as settled on the third;
   - the bounded timeout cancels the backend watch and reports that activity had begun;
   - pre-activity unavailability remains distinguishable and benign;
   - cancellation, supersession, and late allocation cannot strand either readiness or
     quiescence promises;
   - post-game handoff behavior and cleanup are unchanged.
3. In `src/controllers/gameLifecycleController.test.ts`, add orchestration tests proving:
   - when the watcher is active, the game stays paused, the first
     `checkGameStart` result is not acted upon, settlement is awaited under the renewable
     lease, `checking` is republished, and a second check completes before restore/conflict
     or resume;
   - an idle watcher does not cause a second check or observable launch delay;
   - timeout/failure after activity publishes an error, emits exactly one failure toast,
     performs no automatic restore/conflict RPC, cancels the watch, and still releases the
     pause in cleanup;
   - unavailable-before-activity preserves the existing check/restore behavior;
   - epoch supersession and lease loss prevent stale reruns/statuses/actions.
4. In `src/surfaces/autoSyncStatusSurface.test.ts` and/or the suppression suite, add tests
   proving:
   - pre-game `local_current` cannot replace a currently visible
     `syncthing_downloading`/`syncthing_uploading` state;
   - the 900 ms dwell still applies to post-game `backed_up` followed by pending/uploading;
   - the dwell does not apply to pre-game `local_current` or restored results;
   - a conflict remains visible beyond `RESULT_HIDE_DELAY_MS`;
   - `conflict_unresolved` renders and auto-hides after the normal result delay.
5. In `src/controllers/gameLifecycleDecision.test.ts`, renderer tests, and
   `tests/test_status_flow_diagram.py`, fence the explicit conflict-dismissal result, its
   exact copy, warning styling/icon, and the preserved keep-local/restore animations.
6. Run the focused RED suites before implementation:

   ```bash
   ./run.sh pnpm run test:unit -- src/controllers/syncthingMonitorMachine.test.ts src/controllers/syncthingMonitor.initialization.test.ts src/controllers/syncthingMonitor.activity.test.ts src/controllers/syncthingMonitor.failures.test.ts src/controllers/gameLifecycleDecision.test.ts src/controllers/gameLifecycleController.test.ts src/surfaces/autoSyncStatusSurface.test.ts src/surfaces/autoSyncStatusSurface.suppression.test.ts
   ./run.sh uv run pytest tests/test_status_flow_diagram.py
   ```

Do not weaken existing assertions or change fixtures merely to manufacture RED.

### 2. Make pre-game watch settlement an explicit machine milestone (GREEN)

Update `src/controllers/syncthingMonitorMachine.ts` and its tests:

1. Treat download, upload, `update_in_progress`, and the existing active/preparing/indexing
   sample statuses as relevant pre-game activity. Once activity is observed, count only
   distinct, valid, settled idle samples toward the existing three-sample threshold.
   Interleaved activity resets the count.
2. Resolve a dedicated quiescence effect only when the threshold is reached. Resolve it
   unavailable on cancellation, terminal polling failure, or watch allocation failure so
   no caller can wait forever.
3. For pre-game publication, update `latestStatus` for every processed semantic state and
   publish only when that state differs from the previous one. Repeated timestamps remain
   ignored as today; different timestamps carrying the same semantic status are also
   deduplicated.
4. Preserve meaningful transitions: downloading to uploading, idle to a later transfer,
   and final completion may each publish once. Do not apply post-game rank monotonicity to
   pre-game transfer direction.
5. Preserve post-game pending/upload/complete ranking, handoff, detection grace, timeout,
   and cleanup behavior exactly.

Commit the coherent machine/test change after its focused tests pass, for example:

```text
fix(syncthing): track and deduplicate pre-game settlement
```

### 3. Expose a bounded pre-game quiescence session API (GREEN)

Update `src/controllers/syncthingMonitor.ts` and its focused tests:

1. Add a dedicated quiescence promise/resolver to each watch context and expose a typed
   method on `SyncthingWatchSession` for pre-game callers.
2. At invocation time:
   - wait for first-sample readiness only if initialization is still pending;
   - return `idle` immediately when initialized with no observed activity;
   - return `settled` immediately when completion already occurred;
   - otherwise wait for the machine's quiescence outcome or the caller-supplied timeout.
3. Return activity provenance with failure/timeout results so lifecycle policy can tell a
   harmless unavailable watcher from an interrupted active sync.
4. On timeout, cancel the specific generation and stop its backend watch. Clear timeout
   handles in all resolve/reject paths. A stale generation must not cancel the current
   generation.
5. Make all cancellation paths idempotently settle both promises, including dispose,
   supersession, late allocation, poll failure, and the existing 120-second watch timeout.
6. Keep post-game `activatePostGameHandoff()` and all public backend RPC shapes unchanged.

Commit this session-level API with its tests, for example:

```text
fix(syncthing): expose bounded pre-game quiescence wait
```

### 4. Gate launch decisions on settled files and rerun stale checks (GREEN)

Update `src/controllers/gameLifecycleController.tsx`,
`src/controllers/gameLifecycleDecision.ts`, and their tests:

1. Preserve the existing order that acquires the pause lease and starts the pre-game watch
   before `check_game_start`.
2. After the first check returns but before evaluating or acting on it, use the pre-game
   session's bounded quiescence API when a pause lease exists. Run the wait through
   `pauseHandle.runProtected()` and recheck lifecycle epoch/staleness immediately after it.
3. For `idle` or pre-activity-unavailable outcomes, evaluate the original check exactly as
   today.
4. For `settled` after observed activity, discard the first result, publish `checking`, run
   a fresh `check_game_start` through the protected lease, log it as a post-settlement
   recheck, recheck epoch/staleness, and evaluate only that result.
5. For timeout/failure after observed activity, use a pure decision result to publish
   `error`, emit one actionable failure toast, skip restore/conflict resolution, cancel the
   watch, and let existing `finally` cleanup release the process. Include bounded,
   path-free diagnostics; do not expose Syncthing credentials or raw payloads.
6. Preserve the current no-pause safety behavior, conflict-modal pause renewal, conflict
   resolution action animations, global history sync, and stale-epoch guards.

Commit the launch-safety change with its tests, for example:

```text
fix(autosync): recheck saves after pre-game sync settles
```

### 5. Correct status precedence and restrict the dwell to its intended phase

Update `src/surfaces/autoSyncStatusSurface.tsx`, the controller's status-surface adapter
types/calls, and focused surface/controller tests:

1. Pass explicit lifecycle provenance into `complete()` from both start and exit command
   executors, including epoch-guard forwarding.
2. If a pre-game `local_current` completion arrives while the current visible status is an
   active Syncthing download/upload, suppress the stale `has_backup` publication. Log one
   concise diagnostic explaining the precedence decision.
3. Apply `HAS_BACKUP_MIN_DWELL_MS` only when the visible `has_backup` came from a successful
   post-game `backed_up` result and the next state belongs to the post-game Syncthing
   handoff. Preserve coalescing, error preemption, hide/dispose cleanup, and the existing
   two-second result auto-hide.
4. Do not change `autoSyncStatusBrowserView.ts` production behavior. Its same-status
   navigation deduplication remains a lower-level defense and should continue passing all
   existing tests.

Commit this BrowserView ordering correction with its tests, for example:

```text
fix(status): preserve active pre-game sync precedence
```

### 6. Make conflict status persistent and dismissal explicit

Update `src/types/index.ts`, `src/surfaces/autoSyncStatusRenderer.tsx`,
`src/surfaces/autoSyncStatusSurface.tsx`, `src/controllers/gameLifecycleDecision.ts`, and
their focused tests:

1. Add `conflict_unresolved` as an explicit result kind with the exact copy
   `SYNC SKIPPED — CONFLICT UNRESOLVED`.
2. Render it with the existing amber warning treatment and a conflict/warning icon; keep
   `error` red and routine Syncthing/success statuses Steam Blue.
3. Make active `conflict` non-auto-hiding so it remains visible while
   `resolveConflict()` is pending. Selecting an action still transitions immediately to
   `backing_up` or `restoring`.
4. Map a dismissed modal (`skipped/conflict_unresolved`) directly to the new result kind,
   which auto-hides after `RESULT_HIDE_DELAY_MS`, instead of falling through to `unknown`.
5. Preserve the existing game-resume cleanup and do not emit a failure toast for a user
   who intentionally dismisses the modal.

Commit this result-contract change with its tests, for example:

```text
fix(status): report unresolved conflicts explicitly
```

### 7. Update durable documentation and session evidence

1. Update `docs/specs/custom_status_bar_ui.md` to document:
   - the new status kind/copy/color/timing;
   - persistent conflict display while the modal is open;
   - pre-game Syncthing precedence and the post-game-only dwell;
   - the launch-safety sequence of observe, settle, recheck, decide, and resume.
2. Update the README's status explanation if it lists user-visible lifecycle messages or
   launch behavior. Do not add implementation detail to user-facing copy.
3. Add the required dated JSON session record under `docs/agent_conversations/` with the
   objective, files modified, RED tests, design decisions, gate results, and explicit note
   that hardware verification is deferred to the published dev build.
4. Keep unrelated files and user work untouched. Use targeted formatting if the working
   tree is not otherwise clean.

### 8. Preserve atomic history and prepare approved finalization

1. Keep the plan commit first and use the coherent Conventional Commit boundaries above;
   minor documentation/session evidence may accompany the behavior commit it documents or
   use one final `docs(...)` commit.
2. Before marking a round complete, confirm all changes and review notes are committed,
   the working tree is clean, and the complete orchestration quality gate passes.
3. Do not dispatch a release during implementation or review rounds. Release publication
   belongs only to approved finalization through
   `scripts/orchestration/finalize pre-game-sync-status-correctness` and the existing
   `scripts/orchestration-hooks/finalize-release` hook.
4. The finalization execution must have remote push enabled so the merge commit exists on
   `origin/dev` before the hook dispatches GitHub Actions. Use the current unreleased base
   version from matching `package.json`/`plugin.json` (`0.3.6` at plan authoring time); do
   not bump it merely to create another SHA-qualified dev prerelease.
5. A finalized marker is not sufficient release evidence by itself. Completion requires
   the exact merged commit on `origin/dev`, a successful `dev-release.yml` run, and the
   corresponding immutable prerelease/assets described below.

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

### Focused automated verification

Run focused tests throughout RED/GREEN/REFACTOR work:

```bash
./run.sh pnpm run test:unit -- src/controllers/syncthingMonitorMachine.test.ts src/controllers/syncthingMonitor.initialization.test.ts src/controllers/syncthingMonitor.activity.test.ts src/controllers/syncthingMonitor.failures.test.ts src/controllers/gameLifecycleDecision.test.ts src/controllers/gameLifecycleController.test.ts src/surfaces/autoSyncStatusSurface.test.ts src/surfaces/autoSyncStatusSurface.suppression.test.ts src/surfaces/autoSyncStatusBrowserView.test.ts
./run.sh uv run pytest tests/test_status_flow_diagram.py
./run.sh pnpm run typecheck
./run.sh pnpm run build
```

The focused tests must prove these observable sequences:

- idle watch: `VERIFYING GAME SAVE` -> original check result -> resume, with one start
  check and no artificial wait;
- incoming sync: Syncthing download/upload remains authoritative -> three settled samples
  -> `VERIFYING GAME SAVE` -> fresh check result -> optional restore/conflict -> resume;
- interrupted incoming sync: active transfer -> bounded `UNABLE TO SYNC` plus one toast ->
  no restore/conflict action -> watch cancellation and eventual resume;
- conflict modal: `SAVE CONFLICT` remains visible past two seconds -> selected action
  animation, or dismissal -> `SYNC SKIPPED — CONFLICT UNRESOLVED` for two seconds;
- repeated same-direction samples produce one status publication and no extra BrowserView
  navigation, while real status transitions remain visible;
- post-game behavior remains `BACKING UP LOCAL SAVE` -> `GAME SAVE UP TO DATE` for at
  least 900 ms -> pending/uploading/complete as observed.

### Full repository gates

Before every round-complete marker, run the generated orchestration gate:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

That gate must pass the repository's complete validation ladder through `./run.sh`,
including Ruff check/format check, `ty`, frozen frontend install/supply-chain verification,
pytest, Vitest, TypeScript, and build/package validation. The final `git status --short`
must be empty.

### Release verification after approval

Approved finalization must use the existing orchestration finalizer and project release
hook, with remote push enabled by the execution workflow. Verify all of the following
before reporting the user-requested outcome complete:

1. `dev` and `origin/dev` resolve to the same merge commit containing the approved
   feature and committed review record.
2. `scripts/request_dev_release.sh` dispatches `dev-release.yml` for base `0.3.6` and
   that exact full merge SHA; if the base version changed before execution, use the
   matching current `package.json`/`plugin.json` value only after its version guard passes.
3. The GitHub Actions run completes successfully rather than merely entering the queue.
4. The created prerelease tag is `v0.3.6-dev.g<short-merge-sha>` (or the guarded current
   base equivalent), targets the same merge commit, is marked prerelease/not-latest, and
   no stable tag is created.
5. The release contains only the immutable versioned ZIP, SHA-256 file, and manifest;
   validate that the manifest/version and checksum correspond to the published ZIP. Do
   not create or overwrite a mutable public ZIP alias.

If dispatch or publication fails after the merge/push stage, preserve the orchestration
finalize journal and use its documented recovery path; do not blindly redispatch and risk
a duplicate dev tag.

### Deferred on-device verification

Steam Deck verification is intentionally deferred until the new prerelease is available.
After installing it on `steamdeck-legos`, manually reproduce both paths and collect fresh
logs under `/tmp/sdh_ludusavi/steamdeck-legos/logs`:

- launch while the resolved Ludusavi Syncthing folder is actively downloading; confirm
  the game remains paused, no `has_backup` appears during transfer, the save check runs
  again after settlement, and resume occurs only after the fresh decision;
- open a conflict modal for more than two seconds and then dismiss it; confirm the active
  conflict remains visible and dismissal shows the explicit unresolved-conflict result;
- confirm repeated same-direction poll samples no longer create repeated status-update
  log entries;
- run a normal exit backup and confirm the established 900 ms result dwell and
  pending/upload/complete handoff remain healthy.

These hardware checks are post-release acceptance evidence, not blockers for automated
review, approved merge, remote push, or development prerelease publication.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished pre-game-sync-status-correctness
```

This writes:

```text
/tmp/sdh_ludusavi/pre-game-sync-status-correctness_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer pre-game-sync-status-correctness`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/pre-game-sync-status-correctness-review-*.md
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
   scripts/orchestration/clear-finished pre-game-sync-status-correctness
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
   git add docs/review/pre-game-sync-status-correctness-review-*.md
   git commit -m "docs(review): record pre-game-sync-status-correctness review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished pre-game-sync-status-correctness
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer pre-game-sync-status-correctness` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed pre-game-sync-status-correctness
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize pre-game-sync-status-correctness
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/pre-game-sync-status-correctness_finalized
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
scripts/orchestration/finalize pre-game-sync-status-correctness
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/pre-game-sync-status-correctness_finished
/tmp/sdh_ludusavi/pre-game-sync-status-correctness_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
