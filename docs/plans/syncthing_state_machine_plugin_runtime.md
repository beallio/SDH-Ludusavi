# Syncthing Monitor State Machine + PluginRuntime Consolidation

Date: 2026-06-11
Planner Model: claude-fable-5
Plan name (used for markers/review files): `syncthing_state_machine_plugin_runtime`

## Execution Skill

Execute this plan with the `implementer` skill (environment discovery → branch → strict TDD → atomic conventional commits → session log).

## Problem Definition

`src/controllers/syncthingMonitor.ts` (677 lines; size budget 700 in `tests/test_module_size_budgets.py`, only 23 lines of headroom) encodes a state machine implicitly via boolean flags in a per-generation `WatchContext` (lines 61–83): `initialized`, `cancelled`, `publicationEnabled`, `activityObserved`, `completionObserved`, `settledCount`, `handoffActivated`, etc., guarded by generation counters. Every flag pair is a potential illegal combination the code must defend against. Extracting an explicit, pure state machine makes transitions compiler-checked (exhaustive switch with `never`), table-testable in vitest without timers/mocks, and relieves the size budget.

Separately, four modules hold module-level mutable state with paired reset functions invoked on plugin dismount — a stale-state-across-QAM-remount bug class waiting for one forgotten reset:
1. `src/settings/settingsMutationController.tsx` — queue, processing flag, listeners, 5 seq counters, 5 lastPersisted caches, active store/notifier; `resetSettingsMutationController()` (lines 159–177)
2. `src/surfaces/autoSyncStatusBrowserView.ts` — view/owner refs, state, timeout/generation; `destroyAutoSyncStatusBrowserView()`
3. `src/surfaces/autoSyncStatusSurface.tsx` — state, timedOut flag, 2 timeout IDs; `resetAutoSyncStatusSurface()`
4. `src/components/qam/LudusaviContent.tsx` — `activeInitPromise`, `activeMetadataPromise`; `resetLudusaviContentLoadState()`

A single `PluginRuntime` constructed in `definePlugin` and disposed once on dismount replaces N reset calls with one, and lets tests build fresh runtimes instead of `vi.resetModules`.

**Important facts verified against the source (use these, not assumptions):**
- The monitor's context map is **class-instance** state (instantiated in `gameLifecycleController.tsx:165`, disposed at `:534`) — it is correctly lifecycle-managed already and only needs the state-machine extraction, not singleton conversion.
- A naive linear phase list (`idle | starting | watching | ... | done`) does **not** fit the real behavior: handoff and completion are orthogonal to cancellation (cancel can fire after completion; post-game contexts survive in the map until handoff or supersession). Use the design below.

## Execution Protocol

- **Branch**: `git checkout dev && git checkout -b refactor/syncthing-state-machine-runtime` — all work on this branch. Never commit to `dev` or `main` directly during development.
- **Baseline**: before any change, run the full gates (below) on the fresh branch and confirm green.
- **Quality gates (run before EVERY commit)**:
  1. `pnpm run test:unit` (vitest)
  2. `pnpm run typecheck` (tsc --noEmit)
  3. `./run.sh uv run ruff check . --fix`
  4. `./run.sh uv run ruff format .`
  5. `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  6. `./run.sh uv run pytest`
- All caches/temp under `/tmp/sdh_ludusavi/` (run.sh exports this). Always use `./run.sh` for Python tooling.

## Behavioral Contract — tests that MUST NOT be modified

- `src/controllers/syncthingMonitor.initialization.test.ts`, `.activity.test.ts`, `.failures.test.ts` (963 lines total — the red/green signal for Half 1)
- `src/controllers/gameLifecycleController.test.ts`, `.logging.test.ts`, `steamLifecycleSource.test.ts`
- `src/surfaces/autoSyncStatusSurface.test.ts` (pure renderer exports)
- All Python tests except `tests/test_module_size_budgets.py` — especially `tests/test_issue_8_ui_error.py`, which string-asserts on `LudusaviContent.tsx` source (`const applyRefreshResult = (`, `if (result.dependency_error) {`). Do not rename/reformat `applyRefreshResult` or refresh-notify strings.

Tests that WILL change: `src/surfaces/autoSyncStatusSurface.suppression.test.ts` (migrates off `vi.resetModules`), `tests/test_module_size_budgets.py` (BUDGETS table).

---

## Architecture Overview

### Half 1 — Pure state machine for SyncthingMonitor

Extract a pure, side-effect-free transition module `src/controllers/syncthingMonitorMachine.ts`. The existing `SyncthingMonitor` class becomes a thin I/O shell (timers, RPC, promises, logging) that dispatches typed events into the machine and applies the returned effects.

**Verified behavior facts (transcribe exactly; do NOT "fix" any of these):**
- Primary lifecycle axis: `allocating` (before `startWatch` resolves, lines 156–184) → `watching` (line 359) → terminal `complete` (settledCount ≥ 3 after activity, lines 603–605) or `cancelled` (cancel / alloc failure / poll failure / pending timeout).
- **Cancel can fire after completion** (cleanup gate lines 266–274; `activatePostGameHandoff` on a cancelled context returns `unavailable`, lines 206–210) → `completionObserved` must stay a separate sticky boolean even when cancelled.
- `handoffActivated` is orthogonal (cleanup gate only, line 269). `publicationEnabled`: set on allocation for pre_game (line 370), on handoff confirmation for post_game (line 249); cleared on cancel/failure.
- Pre-game sample publication does **not** check `publicationEnabled` (lines 622–635).
- `handlePollFailure`: publishes only when `wasEnabled && phase === "post_game"` (line 548); resolves readiness `unavailable` only when `!initialized` (line 529); no-op when already cancelled (line 520).
- `failures.test.ts:292` reads `(monitor as any).contexts.get(generation).cancelled` — the shell context must keep a `cancelled` property (getter over machine state).
- Stays in the impure shell: generation counters/staleness checks, `Date.now()` 120s max-duration check (lines 465–474, `startedAt` for pre_game / `handoffActivatedAt` for post_game), the readiness Promise object, `window.setTimeout` poll/pending/confirmation timers, `Promise.race` in `activatePostGameHandoff`, RPC calls, logging, late-allocation stop (lines 338–345).

### Half 2 — PluginRuntime consolidation

Composition of factories with closure state and one `dispose()`, composed by `createPluginRuntime()` in `src/runtime/pluginRuntime.ts`, constructed once in `definePlugin` and disposed once in `onDismount`.

## Core Data Structures

### State machine (`src/controllers/syncthingMonitorMachine.ts`, ~280 lines)

```ts
export type WatchPhase = "pre_game" | "post_game";
export type WatchStep = "allocating" | "watching" | "complete" | "cancelled";
export type WatchLatestStatus = "idle" | "uploading" | "downloading" | "complete";

export type WatchMachineState = Readonly<{
  phase: WatchPhase; step: WatchStep;
  initialized: boolean; publicationEnabled: boolean;
  activityObserved: boolean; completionObserved: boolean;  // sticky: survives later cancel
  settledCount: number; lastProcessedTimestamp: number | null;
  latestStatus: WatchLatestStatus; handoffActivated: boolean;
  detectionGraceMs: number;       // default 30_000, clamped on watch_allocated
  unavailableReason: string;      // default "initialization_failed"
}>;

export type WatchMachineEvent =
  | { type: "watch_allocated"; detectionGraceMs: number | undefined }
  | { type: "watch_allocation_failed"; reason?: string }
  | { type: "sample"; sample: SyncthingActivitySample | null }
  | { type: "poll_failed"; reason?: string }
  | { type: "cancel" }
  | { type: "handoff_confirmed" }   // readiness race won by "ready"
  | { type: "handoff_finished" }    // marks handoffActivated for non-confirmed outcomes
  | { type: "pending_activity_timeout" };

export type WatchMachineEffects = Readonly<{
  publish: { status: AutoSyncStatusKind; source: "context" | "timeout" | "rpc_result" } | null;
  resolveReadiness: "ready" | "unavailable" | null;
  stopWatch: boolean;
  clearPendingTimer: boolean;     // post-game publish of uploading/complete (lines 650–652)
  schedulePendingTimer: boolean;  // handoff_confirmed with "pending" outcome (line 257)
  nextPoll: "active" | "retry" | "none";  // 500ms / 250ms / stop
}>;
```

## Public Interfaces

### Machine module

```ts
export function createInitialWatchState(phase: WatchPhase): WatchMachineState;
export function transition(state, event): { state: WatchMachineState; effects: WatchMachineEffects };
export function isTerminal(state): boolean;  // step complete|cancelled
export function canCleanup(state, superseded: boolean): boolean;
  // isTerminal && (phase !== "post_game" || handoffActivated || superseded) — lines 266–274
export function handoffOutcome(state): "complete" | "uploading" | "pending";
  // latestStatus==="complete" → complete; activityObserved → uploading; else pending — lines 252–259
export function mapSyncthingFailureReason(reason): AutoSyncStatusKind | null;  // moved verbatim
```

`transition` is an exhaustive `switch (event.type)` with `default: { const _exhaustive: never = event; ... }`.

**Transition table (transcribe from source, do not redesign):**

| Event | Precondition | New state | Effects |
|---|---|---|---|
| `watch_allocated` | step `allocating`, else no-op | step→`watching`; `detectionGraceMs` = finite && >0 ? value : 30000; `publicationEnabled=true` iff pre_game | none (first poll invoked directly by shell) |
| `watch_allocation_failed` | step `allocating` | step→`cancelled`; `unavailableReason` = reason if in actionable set (`not_configured, api_unavailable, folder_not_found, folder_not_shared, no_connected_peers`) else `"initialization_failed"` | `resolveReadiness:"unavailable"` |
| `sample` (null) | watching | unchanged | `nextPoll:"retry"` |
| `sample`, !initialized, invalid (non-finite `timestamp_unix` or `folder_state==="unknown"`) | watching | unchanged | `nextPoll:"retry"` |
| `sample`, !initialized, valid | watching | `initialized=true`, then process same sample (lines 494–506) | `resolveReadiness:"ready"` + sample effects |
| `sample`, initialized, non-finite or duplicate ts (lines 561, 566) | watching | unchanged | `nextPoll:"active"` |
| `sample` processing | watching | lines 570–646 verbatim: set `lastProcessedTimestamp`; activity predicate (post_game: `uploading`; pre_game: downloading/uploading/update_in_progress/status ∈ {ACTIVE_TRANSFER, SCANNING, UPDATE_NEEDED, PREPARING, INDEXING_OR_SEQUENCE_UPDATE}); newStatus + settledCount reset rules; post_game rank-monotonic `latestStatus` (`getStatusRank`); `completionObserved`/step→`complete` at settledCount ≥ 3 | post_game: publish (`source:"context"`) only if rank increased ∧ `publicationEnabled` ∧ newStatus≠idle; uploading/complete also `clearPendingTimer:true`. pre_game: publish downloading/uploading/complete unconditionally; complete → `stopWatch:true, nextPoll:"none"`. completionObserved → `stopWatch:true, nextPoll:"none"`; otherwise `nextPoll:"active"` |
| `poll_failed` | no-op if cancelled | step→`cancelled`, `publicationEnabled=false`; `unavailableReason`=reason if actionable | `resolveReadiness:"unavailable"` iff !initialized; `stopWatch:true`; publish `{status: mapSyncthingFailureReason(reason) ?? "syncthing_unavailable", source:"rpc_result"}` iff prior `publicationEnabled` ∧ post_game; `nextPoll:"none"` |
| `cancel` | no-op if already cancelled | step→`cancelled` (completionObserved preserved), `publicationEnabled=false` | `resolveReadiness:"unavailable"`, `stopWatch:true` |
| `handoff_confirmed` | — | `handoffActivated=true`, `publicationEnabled=true` | `schedulePendingTimer:true` iff `handoffOutcome(state)==="pending"` |
| `handoff_finished` | — | `handoffActivated=true` | none |
| `pending_activity_timeout` | guard: `publicationEnabled && initialized && !activityObserved && step !== "cancelled"` (lines 424–430), else no-op | step→`cancelled`, `publicationEnabled=false` | publish `{status:"has_backup", source:"timeout"}`, `stopWatch:true` |

### Shell rewrite of `SyncthingMonitor`

`WatchContext` shrinks to: `watchID`, `generation`, `gameName`, `appID`, `source`, `startedAt`, `handoffActivatedAt`, `resolveReadiness`, `readinessPromise`, `state: WatchMachineState`, plus getters `phase` (→ `state.phase`) and `cancelled` (→ `state.step === "cancelled"`, required by `failures.test.ts:292`).

Add `private dispatch(context, event, opts: { releaseWatchID: boolean }): WatchMachineEffects` — calls `transition`, assigns `context.state`, applies effects:
- `resolveReadiness` → `context.resolveReadiness(value)`
- `publish` → `this.onStatus(status, { source: source === "context" ? context.source : source, gameName, appID })`
- `stopWatch` with `releaseWatchID:true` (cancel paths): null `context.watchID` first, **await** `stopWatchSafe` in `cancelContext` (init test line 202 asserts call count immediately after `await handle.cancel()`); with `releaseWatchID:false` (sample-completion path, mirrors `clearPollStateAndStop`): do NOT null `watchID`, fire-and-forget `void this.stopWatchSafe(...)`
- `clearPendingTimer` → `this.clearPendingTimeout()`; `schedulePendingTimer` → `this.schedulePendingActivityTimeout(context, context.state.detectionGraceMs)`
- `nextPoll`: `"retry"` → schedulePoll(250), `"active"` → schedulePoll(500), `"none"` → nothing
- Generation-gated monitor-global timer clears in `cancelContext`/`handlePollFailure` (lines 391–394, 537–540) stay verbatim in the shell.

Method mapping: `allocateWatchBackground` → dispatch `watch_allocated`/`watch_allocation_failed` (late-allocation block 338–345 unchanged); `pollOnce` → keep duration-timeout/staleness checks, dispatch `sample`/`poll_failed`; `cancelContext` → dispatch `cancel` (log line 386 only when not already cancelled); `activatePostGameHandoff` → keep Promise.race scaffolding; confirmed → dispatch `handoff_confirmed`, return per `handoffOutcome`; other `finish()` paths → `handoff_finished`; confirmation timeout still awaits `cancelContext` first (line 237). `maybeCleanupContext` → `if (canCleanup(context.state, context.generation !== this.currentGeneration)) this.contexts.delete(...)`. `getSnapshotForTest` reads `context.state.*` (same shape). Re-export: `export { mapSyncthingFailureReason } from "./syncthingMonitorMachine";` so `gameLifecycleController.tsx:21` is untouched. Delete from shell: in-file `mapSyncthingFailureReason`, `getStatusRank`, `ACTIONABLE_UNAVAILABLE_REASONS`, `DEFAULT_DETECTION_GRACE_MS`; keep `EMPTY_SAMPLE_RETRY_MS`, `ACTIVE_POLL_INTERVAL_MS`, `MAX_WATCH_DURATION_MS`.

### PluginRuntime factories

```ts
// src/runtime/contentLoadCoordinator.ts
export function createContentLoadCoordinator(): {
  getInitPromise(): Promise<OperationStatus> | null;
  setInitPromise(p): void;
  getMetadataPromise(): Promise<void> | null;
  setMetadataPromise(p): void;
  dispose(): void;  // nulls both (old resetLudusaviContentLoadState)
};

// src/settings/settingsMutationController.tsx — exports replaced
export function createSettingsMutationRuntime(): SettingsMutationRuntime;
// All module-level state (lines 32–48) → closure vars inside the factory.
// API: getQueueBusy (was getSettingsQueueBusy), subscribeQueue, applySettings (was
// applySettingsGlobal), syncLastQueuedSelectedGame, clearLastQueuedSelectedGame,
// setActiveStore (was setActiveSettingsStore), createController (was
// createSettingsMutationController), dispose() (body of old reset, lines 159–177).

// src/surfaces/autoSyncStatusBrowserView.ts
export function createAutoSyncStatusBrowserViewController(deps: {
  getCurrentState: () => AutoSyncStatusState;  // PULL model replaces setBrowserViewSyncStateContext push
}): { sync(state): void; destroy(): void };
// Module state (lines 9–19) → closure. Pure helpers stay module-level.
// Delete exports setBrowserViewSyncStateContext, clearAutoSyncStatusShowTimeout (internal now).

// src/surfaces/autoSyncStatusSurface.tsx
export function createAutoSyncStatusSurfaceRuntime(deps?: {
  browserView?: AutoSyncStatusBrowserViewController;  // injectable for tests
}): { publish(...); hide(...); complete(...); dispose(); };
// Closure holds current state + timedOut + 2 timeout IDs; default browserView built with
// getCurrentState: () => current. KEEP module-level: RUNNING_STATUS_HIDE_CEILING_MS,
// RESULT_HIDE_DELAY_MS, the pure re-exports at line 13 (autoSyncStatusSurface.test.ts needs them).

// src/runtime/pluginRuntime.ts
export function createPluginRuntime(overrides?): Readonly<{
  settings; statusSurface; contentLoad;
  dispose(): void;  // order mirrors old onDismount: statusSurface → settings → contentLoad
}>;
```

`index.tsx` (lines 207–302): create `runtime = createPluginRuntime()` after the store; `runtime.settings.setActiveStore(...)`; hydration uses `runtime.settings.applySettings(...)`; lifecycle controller's `statusSurface` arg wires to `runtime.statusSurface.{publish,hide,complete}`; pass `runtime` as a **prop** to `<LudusaviContent runtime={runtime} .../>` (no new React context; `LudusaviStateProvider` unchanged); `onDismount` keeps `lifecycleController.dispose()` + style-element removal, then a single `runtime.dispose()` replaces the 3 reset calls.

`LudusaviContent.tsx`: delete lines 67–73 (module promises + reset); add `runtime: PluginRuntime` prop; `loadInitial` (284–321) and `fetchMetadata` (334–374) use `runtime.contentLoad` getters/setters; lines 134/154/144/207/217/388 switch to `runtime.settings.*`. Do NOT touch `applyRefreshResult` or refresh-notify code.

`gameLifecycleController` already receives `statusSurface` via DI — no changes in Half 2.

## Dependency Requirements

No new dependencies. Existing: vitest + tsc (`pnpm run test:unit`, `pnpm run typecheck`), Python toolchain via `./run.sh` (ruff, ty, pytest, uv).

## Testing Strategy & Implementation Steps (commit-by-commit; TDD red→green within each; suite green at every commit)

1. **`docs(plans): add syncthing state machine and plugin runtime refactor plan`** — commit this file.
2. **`refactor(syncthing): add pure watch state machine module`** — RED: `src/controllers/syncthingMonitorMachine.test.ts`, table-driven `it.each` covering every transition-table row plus: detectionGrace clamping (undefined/NaN/0/-1 → 30000); actionable-reason matrix for both failure events; cancel idempotency; cancel-after-complete preserves `completionObserved` + `canCleanup` gating; post_game rank monotonicity (uploading→downloading ignored; concurrent upload+download → uploading, mirroring activity test line 327); settledCount reset on interleaved activity; `handoffOutcome` 3 cases; `canCleanup` 2×2×2 matrix; `mapSyncthingFailureReason` 4 cases. No timers, no mocks. Confirm failure (module not found). GREEN: implement the machine. `syncthingMonitor.ts` untouched.
3. **`refactor(syncthing): delegate watch flag logic to the pure machine`** — rewrite shell per above; the 3 monitor test files + `gameLifecycleController.tsx` unmodified are the signal; iterate until green. Update `tests/test_module_size_budgets.py`: `"src/controllers/syncthingMonitor.ts": 500`, add `"src/controllers/syncthingMonitorMachine.ts": 350`.
4. **`refactor(runtime): introduce PluginRuntime with content load coordinator`** — RED: `src/runtime/pluginRuntime.test.ts` (contentLoad round-trips; dispose nulls; two runtimes independent; override injection + dispose delegation; mock `@decky/api` like sibling tests). GREEN: `contentLoadCoordinator.ts` + `pluginRuntime.ts` (contentLoad only for now). Wire `LudusaviContent.tsx` (contentLoad + prop) and `index.tsx` (create runtime, replace `resetLudusaviContentLoadState()`; other two resets remain).
5. **`refactor(settings): move settings mutation state into a runtime factory`** — RED: `src/settings/settingsMutationRuntime.test.ts` (mock `@decky/api` + `../api/ludusaviRpc`; real `createLudusaviStateStore()`; busy-flag lifecycle with fake timers; rollback to lastPersisted on RPC failure; two runtimes isolated; dispose clears + notifies false). GREEN: convert per design. Extend `pluginRuntime.test.ts` FIRST (settings member, dispose ordering), then add `settings` to the runtime; update `LudusaviContent.tsx` + `index.tsx` (delete `resetSettingsMutationController`).
6. **`refactor(surfaces): convert status surface and browser view to injected factories`** — RED: rewrite `autoSyncStatusSurface.suppression.test.ts` (drop `vi.resetModules`/`freshSurface`/browserView vi.mock; `makeSurface = () => createAutoSyncStatusSurfaceRuntime({ browserView: { sync: vi.fn(), destroy: vi.fn() } })`; rename calls publish/complete; keep every assertion verbatim) + dispose test (calls injected destroy, clears pending hide timers). GREEN: convert both surface modules. Extend `pluginRuntime.test.ts` first, add `statusSurface`, update `index.tsx` per design (delete `resetAutoSyncStatusSurface`). Check `wc -l` vs budgets (`autoSyncStatusSurface.tsx` ≤ 350, `autoSyncStatusBrowserView.ts` ≤ 300; currently 264/273 — bump budget in same commit if factory indentation overflows, with justifying commit-body line).
7. **`docs: record session log for state machine and runtime refactor`** — `docs/agent_conversations/2026-06-11_syncthing_machine_plugin_runtime.json` (date, objective, files modified, tests added, design decisions, results).

## Risks / Guardrails

- Single-enum designs lose cancel-after-complete; keep `completionObserved` sticky (machine test pins it).
- `stopWatch` watchID-nulling divergence is intentional (`releaseWatchID` option) — do not deduplicate.
- Pre-game publishes without `publicationEnabled` — transcribe, don't fix.
- Suppression-test migration and surface factory conversion must land in the same commit (never a state where neither module globals nor factory exist).
- `runtime` prop is created once in `definePlugin` → stable identity; do not add it to existing `[]` dep arrays.
- Do not modify upstream packages, `dev`, or `main` directly. Preserve unrelated user work (`git status --short` before edits).

## Verification (after every commit; full pass at the end)

1. `pnpm run test:unit` — all green; `git diff --stat dev -- src/controllers/*.test.ts` shows zero diffs to the 3 monitor test files and gameLifecycleController tests.
2. `pnpm run typecheck`
3. `./run.sh uv run ruff check . --fix && ./run.sh uv run ruff format .`
4. `./run.sh uv run ty check py_modules/sdh_ludusavi/`
5. `./run.sh uv run pytest` (covers size budgets, test_issue_8_ui_error, test_protocol)
6. `pnpm run build` once at the end (catches import regressions tsc misses)
7. `wc -l` on the 4 budgeted files matches BUDGETS
8. `grep -rn "resetSettingsMutationController\|resetAutoSyncStatusSurface\|resetLudusaviContentLoadState\|setBrowserViewSyncStateContext" src/` → no hits
9. `git log --oneline dev..HEAD` → the 7 conventional commits

---

## Completion & Review Loop Protocol

After all 7 commits are done and verification passes:

1. **Finished marker**: write an empty file `/tmp/sdh_ludusavi/syncthing_state_machine_plugin_runtime_finished` (e.g. `touch`).
2. **Review polling loop** — repeat until a passing review note is received:
   a. Poll `/tmp/sdh_ludusavi/` for new review note files matching `syncthing_state_machine_plugin_runtime_review*` (any extension). Poll by checking periodically (~60s between checks); track already-processed notes by moving each processed note to `/tmp/sdh_ludusavi/processed_reviews/` after handling.
   b. For each new note, read it:
      - **If it contains findings**: address each finding on the working branch with the same TDD discipline (failing test → fix → gates → atomic conventional commit). Copy the note plus a resolution summary into `docs/review/2026-MM-DD_syncthing_machine_runtime_review.md` and commit it (`docs(review): ...`). Then re-touch the `_finished` marker to signal the fixes are ready, and continue polling.
      - **If it states the review passed** (e.g. contains "PASS", "passing", "no findings", "approved"): exit the loop and proceed to the endgame.
3. **Endgame** (only after a passing review note):
   a. Commit the passing review note if not already committed: copy it to `docs/review/2026-MM-DD_syncthing_machine_runtime_passing_review.md`, commit as `docs(review): record passing review for syncthing state machine and plugin runtime`.
   b. Merge the working branch into dev: `git checkout dev && git merge --no-ff refactor/syncthing-state-machine-runtime`. Run the full gate suite once on dev post-merge.
   c. Clean up the working branch: `git branch -d refactor/syncthing-state-machine-runtime` (and `git push origin --delete refactor/syncthing-state-machine-runtime` only if it was pushed).
   d. Push dev: `git push origin dev`.
   e. Cut a dev release: `./scripts/request_dev_release.sh 0.3.0` (base version 0.3.0 matches all current `v0.3.0-dev.*` tags; defaults to HEAD of dev; requires authenticated `gh`). This is the explicitly authorized release-dispatch action per CLAUDE.md §14.
