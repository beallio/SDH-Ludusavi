# Plan: Apply Accepted Over-Engineering Simplifications (accepted-overengineering-simplifications)

## Context

### Problem Definition

The plugin is behaviorally healthy, but nine experimentally validated areas carry avoidable
maintenance or runtime cost:

1. exact per-file size budgets couple tests to incidental formatting while missing unlisted
   production modules;
2. four independent post-operation reads execute serially;
3. three frontend modules independently own the backend logging transport;
4. hidden-QAM Steam UI context capture polls private React/DOM internals indefinitely;
5. notification preferences are mirrored beside the canonical settings document;
6. three frontend-unused compatibility RPC entry points preserve unsupported surface area;
7. seven setting-specific RPC workflows duplicate sequencing, rollback, caching, and
   persistence behavior;
8. enabling debug logging changes Syncthing watch lifetime and creates a second hidden watch
   registry; and
9. updater/QAM/RPC boundaries use `any` despite existing domain types.

These are the accepted results of the read-only/experimental review recorded on
`refactor/overengineering-experiments`. The trees at `dev` (`b040e04`) and the experiment's
original `main` base (`1cc5592`) were identical when this plan was authored, so the validated
production and test changes apply cleanly to the configured `dev` integration base.

The experiment commits are read-only implementation evidence:

```text
597966e  broad production-module ceiling
fbf4888  concurrent manual-operation finalization reads
e5c5458  canonical frontend logging transport
7bfc5f5  bounded hidden-QAM context capture
abaf791  notification state derived from settings
2ad5294  frontend-unused compatibility RPC removal
979238a  typed atomic settings patch transport
f65d0bd  debug logging made observational
6dbd245  typed updater/QAM/RPC boundaries
077a1ba  holistic experiment metrics and validation evidence
```

Do not cherry-pick or copy these commits before producing the required RED evidence. They
also contain experiment-authored `docs/review/` changes, while the generated orchestration
contract reserves that directory for the orchestrator. Use `git show` only to resolve a
verified detail after reading the live `dev` source and writing the task's failing tests.
The hashes are advisory evidence, not implementation prerequisites; if they are unavailable,
continue from this plan and the live source rather than changing scope.

### Intended Outcome

- Preserve user-visible backup, restore, launch-gate, status-strip, updater, and settings
  behavior except for the explicitly measured improvements below.
- Reduce public backend RPC methods from 44 to 35 by removing three unused aliases and
  replacing seven setting setters with one typed patch method.
- Reduce `src/settings/settingsMutationRuntime.ts` from 535 lines to approximately 346 and
  replace its per-setting sequence/cache matrix with one keyed sequence map, one persisted
  settings document, one queue, and selected-game queue state.
- Make settings persistence a locked read-modify-write against the latest on-disk document,
  preserving unrelated writes from another service instance.
- Reduce a ten-iteration controlled manual-finalization critical path from 400 ms to 100 ms
  while preserving state-application order and mount guards.
- Limit hidden-QAM context capture to one immediate sample plus nine 500 ms retries, then
  perform no continuing hidden work. Opening QAM still obtains a fresh authoritative capture.
- Keep one logging RPC owner and one Syncthing watch registry/lifetime.
- Ensure INFO and DEBUG logger levels return the same Syncthing stop payload and stop the same
  thread at the same user-visible completion boundary.
- Remove every production `any` from the exact updater/QAM/RPC boundary files listed in Task 9,
  while leaving private Steam-runtime inspection outside this plan.
- Preserve or improve the experiment's holistic target: 97 production files, about 19,541
  production lines (`-273` from the baseline), 123 test files, about 30,251 test lines (`+34`),
  at least 1,030 backend tests, at least 363 frontend tests, and backend coverage above the
  repository's 83% floor. Treat counts as reconciliation evidence if `dev` moves after plan
  authoring, not as substitutes for behavioral gates.

### Architecture Overview

Keep the existing frontend/backend responsibility boundary. The backend remains authoritative
for persisted settings and Syncthing domain facts. The frontend remains authoritative for UI
publication, lifecycle promises, generation races, browser timers, cancellation, and
post-game handoff. This plan deletes duplicated owners inside those boundaries; it does not
move the lifecycle or Syncthing state machines across RPC.

Use `SettingsPatch` as a discriminated union spanning auto sync, per-game sync, selected game,
notifications, update channel, automatic update checks, and debug logging. The frontend owns
one optimistic mutation pipeline keyed by patch identity. The backend validates the patch and
mutates the latest persisted settings document while holding the existing persistence and
service locks, then adopts and returns the complete document.

Keep `src/utils/logging.ts` as the only frontend module that defines the Decky `log` callable.
Updater and installer code call that utility. Keep `LudusaviStateSnapshot.settings` as the sole
notification preference owner. Keep `SyncthingWatchManager.watches` as the sole watch registry;
logging may observe normal watch transitions but may not extend watch ownership.

### Core Data Structures

- `SettingsPatch`: seven typed variants with only the fields legal for that setting.
- `SettingsMutationRuntime`: one queue, one monotonically increasing counter, one
  `latestSequenceByKey` map, one persisted settings document, and selected-game queue state.
- `LudusaviStateSnapshot`: canonical `settings`; no notification mirror fields.
- Bounded Steam UI capture: ten-sample burst returning a cancellation callback.
- `SyncthingWatchManager`: one `watches` mapping and one unconditional `stopped` release result.

### Public Interfaces

- Add `update_settings(patch)` through `main.py`, `SDHLudusaviService`,
  `src/api/ludusaviRpc.ts`, and `SettingsPatch` in `src/types/index.ts`.
- Remove the seven setting-specific frontend RPC callables after every UI caller uses
  `updateSettingsCall`.
- Remove `handle_game_start`, `handle_game_exit`, and
  `clear_ludusavi_launcher_shortcut_id` from `main.py` and their backend wrappers only after a
  source contract proves the bundled frontend has no consumer.
- Preserve the supported two-step lifecycle operations (`check_*` followed by restore/backup)
  and use the existing shortcut setter with `-1` for the no-shortcut sentinel.
- Remove the Syncthing debug-only `observing` stop result. `stop_watch` returns `stopped`
  regardless of logger level.
- Backend and frontend ship together. Do not add compatibility shims for undocumented
  out-of-tree callers.

### Dependency Requirements

No new Python or frontend dependency is authorized. Use the existing Python 3.12/`uv`, React,
TypeScript, Vitest, pytest, Ruff, and `ty` toolchain through `./run.sh`. Do not edit vendored
packages. All caches and temporary artifacts remain under `/tmp/sdh_ludusavi`.

### Testing Strategy

Follow RED-GREEN-REFACTOR independently for every behavior-changing task. Capture each focused
RED failure in the session log before editing production code. Structural/type-only tasks may
use failing ownership/type gates instead of runtime tests. Every round runs the generated
quality gates, commits one coherent change, marks the round complete, and stops for review.

Use deterministic fake timers and deferred promises; do not benchmark wall-clock network or
Decky behavior. Never touch a real save, live Syncthing configuration, or a Steam Deck during
automated verification. Mutation controls in the Verification section must fail before the
restored positive gates are trusted.

### Scope Exclusions

- Do not implement the rejected callback-bag grouping, lifecycle typed-outcome wrapper, or
  backend-owned Syncthing lifecycle machine.
- Do not widen type cleanup into private Steam/React-fiber inspection, launcher internals,
  unrelated lifecycle command casts, or declaration shims.
- Do not change Syncthing readiness, three-sample settlement, handoff, privacy, timeout, or
  non-regressing publication semantics.
- Do not push, merge, tag, publish, dispatch a release, or install on a device from an
  implementation round. Final integration is owned by the generated orchestration lifecycle.

### Relevant Files

```text
main.py
py_modules/sdh_ludusavi/lifecycle.py
py_modules/sdh_ludusavi/service.py
py_modules/sdh_ludusavi/syncthing/watcher.py
py_modules/sdh_ludusavi/updater.py
src/api/ludusaviRpc.ts
src/components/modals/BackupBrowserModal.tsx
src/components/qam/GameSettingsSection.tsx
src/components/qam/LudusaviContent.tsx
src/components/qam/manualOperationFinalize.ts
src/components/qam/useGameRefresh.ts
src/components/qam/useInitialContent.ts
src/components/qam/useSteamContext.ts
src/controllers/gameLifecycleController.tsx
src/controllers/pluginUpdateController.tsx
src/controllers/syncthingMonitor.ts
src/index.tsx
src/settings/settingsMutationRuntime.ts
src/state/ludusaviState.tsx
src/types/index.ts
src/utils/deckyInstaller.ts
src/utils/logging.ts
src/utils/steam.ts
tests/test_architectural_constraints.py
tests/test_backup_decision.py
tests/test_compatibility.py
tests/test_history_fixes.py
tests/test_history_integration.py
tests/test_launcher_backend.py
tests/test_main.py
tests/test_module_size_budgets.py
tests/test_optimization_backend.py
tests/test_service.py
tests/test_watcher.py
src/components/qam/manualOperationFinalize.test.ts
src/components/qam/useGameRefresh.test.ts
src/controllers/gameLifecycleController.logging.test.ts
src/settings/settingsMutationRuntime.test.ts
src/state/ludusaviState.test.tsx
src/utils/steam.test.ts
docs/agent_conversations/
```

**Slug used throughout this plan:** `accepted-overengineering-simplifications`

---

## Orchestration Contract

**Slug:** `accepted-overengineering-simplifications`

**Plan file:**

```text
docs/plans/2026-08-18_accepted-overengineering-simplifications.md
```

**Implementation branch:**

```text
feat/accepted-overengineering-simplifications
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/accepted-overengineering-simplifications_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/accepted-overengineering-simplifications_finalized
```

**Review notes:**

```text
docs/review/accepted-overengineering-simplifications-review-*.md
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
git checkout -b feat/accepted-overengineering-simplifications
```

Commit this plan first:

```bash
git add docs/plans/2026-08-18_accepted-overengineering-simplifications.md
git commit -m "docs(plan): add accepted-overengineering-simplifications implementation plan"
```

---

## Implementation Tasks

Ten tasks. **Implement exactly one task per round.** For Tasks 1-9, add or update the focused
gate first, record the RED result when behavior changes, implement only that task, run its
focused checks and the full quality gate, commit, mark the round complete, and exit. Do not
combine tasks even when they touch the same file.

### Task 1 — Replace brittle file budgets with one broad safety ceiling

In `tests/test_module_size_budgets.py`, remove the hand-maintained mapping of 26 files to
near-current line limits. Discover `main.py`, Python modules under
`py_modules/sdh_ludusavi/`, and non-test `.ts`/`.tsx` modules under `src/` dynamically.
Apply one named 1,000-line last-resort ceiling.

Retain all semantic architecture/security tests elsewhere. Add executable helper tests proving
that a synthetic 1,000-line module passes and a 1,001-line module raises an assertion containing
`exceeding broad ceiling`. Prove the production discovery list is non-empty. This is a test-policy
change, not runtime behavior; no production file changes belong in this round.

Focused gate:

```bash
./run.sh uv run pytest -o addopts='' tests/test_module_size_budgets.py tests/test_architecture.py tests/test_architectural_constraints.py
```

Commit as `test(architecture): relax brittle size budgets`.

### Task 2 — Start independent manual-finalization reads concurrently

Before changing `src/components/qam/manualOperationFinalize.ts`, add deferred-promise tests in
`manualOperationFinalize.test.ts` requiring all four read calls—refresh result, operation status,
recent logs, and game history—to start before any one settles. Add a deterministic fake-timer
benchmark for ten finalizations with four 10 ms reads: the sequential implementation must report
a 400 ms virtual critical path and the target must report 100 ms.

Replace the four sequential awaits with one typed `Promise.all`. Preserve the existing apply
order, selected-game preference, mounted guard, history RPC-status handling, and aggregate
failure behavior. Do not add retries or alter backend worker count.

Focused gate:

```bash
./run.sh pnpm exec vitest run src/components/qam/manualOperationFinalize.test.ts
./run.sh pnpm run typecheck
```

Commit as `perf(qam): finalize independent reads concurrently`.

### Task 3 — Give frontend logging transport one owner

Add an ownership assertion to `tests/test_architectural_constraints.py` that scans production
frontend source and requires the sole direct Decky `log` callable definition to be
`src/utils/logging.ts`. Capture the RED result showing the updater controller and Decky installer
also define it.

Remove those duplicate callables from `pluginUpdateController.tsx` and `deckyInstaller.ts`.
Route their messages through the canonical `log()` utility, preserving backend level/message/
operation fields. Keep browser-console logging and contain asynchronous backend logging failures;
logging must not change update or install control flow.

Focused gates:

```bash
./run.sh uv run pytest -o addopts='' tests/test_architectural_constraints.py
./run.sh pnpm exec vitest run src/controllers/pluginUpdateController.test.tsx src/controllers/gameLifecycleController.logging.test.ts
./run.sh pnpm run typecheck
```

Commit as `refactor(logging): centralize frontend transport`.

### Task 4 — Bound hidden-QAM Steam UI context capture

Write fake-timer tests in `src/utils/steam.test.ts` before changing production behavior. Require a
hidden QAM transition to capture immediately, retry nine times at 500 ms intervals, stop after
4.5 seconds, and perform no additional work during the rest of a simulated minute. Require the
returned cleanup callback to cancel the burst early.

Add a named bounded-capture helper in `src/utils/steam.ts` and use it from the visibility effect
in `LudusaviContent.tsx`. Preserve the fresh open-time path:
`getPreferredSteamGameSession()` must still capture synchronously before consulting recent cache
or running-app fallback. Do not change selection precedence, Steam runtime inspection, or the
10-second recent-context TTL.

Focused gates:

```bash
./run.sh pnpm exec vitest run src/utils/steam.test.ts src/components/qam/useSteamContext.test.ts src/components/qam/qamOpenSelection.test.ts
./run.sh pnpm run typecheck
```

Commit as `perf(qam): bound hidden context capture`.

### Task 5 — Derive notification policy from canonical settings

Add an ownership assertion in `src/state/ludusaviState.test.tsx` that fails while
`autoSyncNotificationsEnabled` and `notificationSettings` exist beside
`LudusaviStateSnapshot.settings`. Preserve behavioral tests for cold defaults, master disable,
per-category enablement, optimistic auto-sync changes, lifecycle status suppression, and logging.

Remove the two mirror fields. Make `applySettings()` commit only the normalized settings document,
and derive notification/pre-RPC publication selectors from it with the existing cold-state
defaults. Update `gameLifecycleController.tsx` and its logging test only as needed to consume the
derived selectors. Do not change persisted settings shape.

Focused gates:

```bash
./run.sh pnpm exec vitest run src/state/ludusaviState.test.tsx src/controllers/gameLifecycleController.logging.test.ts
./run.sh pnpm run typecheck
```

Commit as `refactor(state): derive notification policy from settings`.

### Task 6 — Remove frontend-unused compatibility RPC entry points

Add a repository contract that first proves the bundled frontend does not contain
`handle_game_start`, `handle_game_exit`, or `clear_ludusavi_launcher_shortcut_id`, then fails while
`main.py` exposes them. Remove only those public async methods and their service/lifecycle wrapper
methods.

Migrate tests that called the aliases to the supported check-then-restore and check-then-backup
interfaces. Use `set_ludusavi_launcher_shortcut_id(-1)` for shortcut clearing and preserve `-1` as
the no-shortcut sentinel. Do not remove lower-level lifecycle behavior used by supported methods
and do not add an alternate compatibility layer.

Focused gates:

```bash
./run.sh uv run pytest -o addopts='' tests/test_compatibility.py tests/test_main.py tests/test_service.py tests/test_backup_decision.py tests/test_history_fixes.py tests/test_history_integration.py tests/test_launcher_backend.py tests/test_optimization_backend.py
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh pnpm run typecheck
```

Record the public `main.py` async method count before and after; the target is 44 to 41 at this
round. Commit as `refactor(rpc): remove unused compatibility aliases`.

### Task 7 — Unify setting mutations behind one typed atomic patch

Write backend tests before production changes for all seven patch variants, malformed kinds and
fields, persistence reload, and two service instances updating different fields without losing
either write. Preserve or extend frontend tests for optimistic updates, same-field supersession,
cross-field ordering, timeout rollback, late success, late failure, per-game isolation, same-game
failure recovery, selected-game serialization, and no busy-label flicker.

Add the discriminated `SettingsPatch` union to `src/types/index.ts` and one
`updateSettingsCall` to `src/api/ludusaviRpc.ts`. Route every settings UI action through a single
keyed queue in `settingsMutationRuntime.ts`. Maintain one sequence map keyed by setting or game,
one persisted settings document, one queue/counter, and selected-game queue state. A late result
may apply only its owned field and must not clobber newer unrelated state.

Add `update_settings` to `main.py` and `SDHLudusaviService`. Validate each patch before mutation.
While holding the service state lock, call the persistence layer's locked settings mutation so
the patch merges against the latest on-disk document; then adopt and return the complete persisted
settings. Keep persistence error behavior fail-closed. Route updater setting changes through the
same patch path. Remove the seven setting-specific frontend RPC callables only after every caller
is migrated; service helpers may remain only where backend-internal tests/behavior still require
them.

Focused gates:

```bash
./run.sh uv run pytest -o addopts='' tests/test_service.py tests/test_main.py tests/test_compatibility.py
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh pnpm exec vitest run src/settings/settingsMutationRuntime.test.ts src/state/ludusaviState.test.tsx
./run.sh pnpm run typecheck
```

Record setting RPC definitions, mutable workflow owners, and runtime line count before/after. The
validated targets are seven RPCs to one, total public RPCs 41 to 35, 20 mutable workflow values to
six, and 535 runtime lines to approximately 346. Commit as
`refactor(settings): unify typed mutation transport`.

### Task 8 — Make debug logging observational for Syncthing

Before changing the watcher, add a parameterized test that runs the same completed post-game
watch release at INFO and DEBUG logger levels. Capture the RED difference: DEBUG returns
`observing`, retains a running thread, and moves the watch into a second registry while INFO
returns `stopped`.

Remove the debug-lifetime constructor flag, released-observation callback/state, alternate
completion branch, `is_debug_extending_peer_completion`, and `_observing_watches`. Stop and join a
released watch unconditionally and return `{"status": "stopped", "watch_id": ...}`. Ensure
`stop_all()` snapshots the current watch values before clearing the dictionary so every thread is
still stopped outside the manager lock.

Keep sanitized, transition-only peer diagnostics during the normal watch lifetime. Preserve tests
that device IDs, folder IDs, paths, file names, and raw Syncthing responses never enter logs or
RPC payloads. Explicitly record the accepted tradeoff: delete-pruning is no longer observed after
the frontend releases a completed watch.

Focused gates:

```bash
./run.sh uv run pytest -o addopts='' tests/test_watcher.py tests/test_service.py tests/test_activity.py
./run.sh uv run ty check py_modules/sdh_ludusavi/
```

Commit as `refactor(syncthing): keep debug logging observational`.

### Task 9 — Strengthen the evaluated TypeScript boundaries

Inventory production `any` occurrences before editing. Remove all occurrences from exactly these
evaluated boundary files:

```text
src/api/ludusaviRpc.ts
src/components/modals/BackupBrowserModal.tsx
src/components/qam/GameSettingsSection.tsx
src/components/qam/LudusaviContent.tsx
src/components/qam/useGameRefresh.ts
src/components/qam/useInitialContent.ts
src/components/qam/useSteamContext.ts
src/controllers/pluginUpdateController.tsx
src/controllers/syncthingMonitor.ts
src/index.tsx
src/utils/deckyInstaller.ts
```

Use the existing `PluginUpdateCandidate`, `RpcResult`, `RpcStatus`, `GameOperationHistory`,
`Versions`, `LudusaviLaunchCommand`, `ReactNode`, `QamOpenSelectionInput`, and
`QamOpenSelectionAction` types. Make RPC-status callbacks real type predicates so unions narrow
without casts. Use `unknown` for caught values and the unused Decky installer response. Use the
browser timer return type instead of `any`. Update test doubles only enough to satisfy the stronger
predicate contracts.

Do not widen this round into `src/utils/steam.ts`, `steamRuntime.ts`, launcher casts, lifecycle
command casts, browser-view shims, or global declaration files. Runtime behavior must remain
unchanged.

Focused gates:

```bash
./run.sh pnpm exec vitest run src/components/qam/useInitialContent.test.ts src/components/qam/useGameRefresh.test.ts src/components/qam/useSteamContext.test.ts src/components/qam/qamOpenSelection.test.ts src/controllers/pluginUpdateController.test.tsx
./run.sh pnpm run typecheck
```

Record scoped and repository-wide counts. The validated scoped target is 31 to zero; the
repository-wide production target is 86 to 54 after all accepted changes. Commit as
`refactor(types): strengthen frontend boundaries`.

### Task 10 — Reconcile the accepted set and record the implementation session

Do not change production behavior in this round. Confirm none of the three rejected prototypes is
present: no nested callback grouping that retains the same QAM leaf dependencies, no lifecycle
typed-outcome/effect wrapper, and no backend port of the frontend Syncthing machine.

Measure production/test files and lines, public RPC count, settings-runtime lines, logging-RPC
owners, scoped/repository `any`, hidden-QAM captures, and controlled finalization latency against
the round's actual `dev` base. Explain any drift from the authored targets with file-level
evidence. Inspect `README.md` and `DEVELOPMENT.md`; update them only if the completed work changed
a documented public behavior or developer workflow. No routine README change is expected because
the accepted set preserves public workflows.

Create `docs/agent_conversations/2026-08-18_accepted_overengineering_simplifications.json` with
date, objective, files modified, tests added, design decisions, task-by-task results, RED evidence,
negative controls, final metrics, and deferred verification. Do not create or modify
`docs/review/`; review notes remain orchestrator-owned.

Run the focused suites and required negative controls, restore every temporary mutation, run the
positive gates, and record actual pass/fail tallies. Commit the completed record as
`docs(session): record accepted simplification implementation`. After that commit, run the Final
full gate exactly as written below and require empty `git status --short` output. If a gate fails,
fix the cause, update and recommit the record when its evidence changed, then rerun the entire
Final full gate. Do not edit tracked files after the clean final gate; put the clean-tree result in
the orchestration round handoff before marking the round finished.

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

Follow the repository wrapper/cache policy and the orchestration skill's
`references/verification-standards.md`. A command is evidence only when its failure propagates and
its actual output/tally is recorded. Focused commands may be narrowed while iterating, but every
round still runs `scripts/orchestration/run-quality-gates` before completion.

### Focused suites

```bash
./run.sh uv run pytest -o addopts='' tests/test_module_size_budgets.py tests/test_architectural_constraints.py tests/test_architecture.py
./run.sh uv run pytest -o addopts='' tests/test_compatibility.py tests/test_main.py tests/test_service.py tests/test_backup_decision.py tests/test_history_fixes.py tests/test_history_integration.py tests/test_launcher_backend.py tests/test_optimization_backend.py
./run.sh uv run pytest -o addopts='' tests/test_activity.py tests/test_watcher.py
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh pnpm exec vitest run src/components/qam/manualOperationFinalize.test.ts src/utils/steam.test.ts src/components/qam/useSteamContext.test.ts src/components/qam/qamOpenSelection.test.ts
./run.sh pnpm exec vitest run src/state/ludusaviState.test.tsx src/settings/settingsMutationRuntime.test.ts src/controllers/gameLifecycleController.logging.test.ts src/controllers/pluginUpdateController.test.tsx src/components/qam/useInitialContent.test.ts src/components/qam/useGameRefresh.test.ts
./run.sh pnpm run typecheck
./run.sh pnpm run build
```

### Required negative controls

Run these after the failure cases from Tasks 1-9 and before the final positive gate. Make each
temporary mutation in production code, run the named focused test, record the expected non-zero
exit and failing test name/message, then restore the production line with a targeted edit—never by
rewriting the test expectation.

1. Replace Task 2's concurrent read start with sequential awaits. Run
   `manualOperationFinalize.test.ts`; `starts all independent reads before the first one settles`
   and/or the 100 ms critical-path test must fail.
2. Increase the bounded Steam capture sample count from 10 to 11. Run `steam.test.ts`; `stops
   scraping after ten samples during a minute hidden` must fail.
3. Change backend `update_settings` to base a patch on the service instance's in-memory settings
   instead of `Persistence.mutate_settings`. Run
   `test_typed_settings_patches_merge_across_service_instances`; it must fail by losing the peer
   instance's unrelated field.
4. Reintroduce the DEBUG-only observation release branch or make the parameterized test's DEBUG
   path return `observing`. Run `test_debug_logging_does_not_change_watch_stop_semantics`; its
   DEBUG case must fail.

After restoring every mutation, rerun all focused suites above. The positive controls must pass
after—not before—the negative-control failures.

### Final full gate

Run this gate after Task 10's session-record commit:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

Record the backend test count and coverage, frontend test/file count, TypeScript result,
supply-chain audit result, build result, and package result in the session record before its
commit. Record the post-commit clean-worktree output in the orchestration round handoff.
Verification is incomplete if a no-op implementation could pass, a negative mutation did not fail
for the named reason, a test expectation was weakened, any review note was deleted, or the final
worktree is dirty.

### Deferred verification

- On-device observation of QAM visibility transitions, update installation, notification policy,
  and Syncthing post-game status remains deferred until an explicitly authorized development
  install. Unit/fake-timer tests do not claim private Steam UI stability across a Steam client
  update.
- Do not run backup, restore, launch-gate, or Syncthing experiments against real saves or live
  device configuration during this plan.
- Out-of-tree callers of the removed undocumented RPC aliases are not tested or supported; the
  bundled backend/frontend compatibility matrix is the release boundary.
- No release, tag, workflow dispatch, GitHub publication, device install, push, or merge is an
  implementation-round action. Orchestration finalization owns integration; publishing requires
  separate explicit user authorization.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished accepted-overengineering-simplifications
```

This writes:

```text
/tmp/sdh_ludusavi/accepted-overengineering-simplifications_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer accepted-overengineering-simplifications`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/accepted-overengineering-simplifications-review-*.md
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
   scripts/orchestration/clear-finished accepted-overengineering-simplifications
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
   git add docs/review/accepted-overengineering-simplifications-review-*.md
   git commit -m "docs(review): record accepted-overengineering-simplifications review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished accepted-overengineering-simplifications
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer accepted-overengineering-simplifications` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed accepted-overengineering-simplifications
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize accepted-overengineering-simplifications
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/accepted-overengineering-simplifications_finalized
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
scripts/orchestration/finalize accepted-overengineering-simplifications
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/accepted-overengineering-simplifications_finished
/tmp/sdh_ludusavi/accepted-overengineering-simplifications_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
