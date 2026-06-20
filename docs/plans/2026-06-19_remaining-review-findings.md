# Remaining Review-Finding Decompositions

```text
TITLE=Remaining Review-Finding Decompositions
SLUG=remaining-review-findings
PLAN_PATH=docs/plans/2026-06-19_remaining-review-findings.md
```

## Context

The June-18 reviews in `docs/review/2026-06-18_*.md` were mostly remediated by the
`june-review-remediation` work (merged to `dev`). What remains are the findings that were
deliberately deferred as "Future PR": four large architecture decompositions plus one
small concurrency nit. This plan lands them. Each is a **no-behavior-change refactor**
(except the watcher race, which is a correctness fix) — the public RPC surface, return
shapes, and existing test expectations must stay intact; the goal is structure, testability,
and removing duplication, not new features.

Two items are explicitly **out of scope** (the user declined them): event-driven QAM
capture (still leave the 500ms hidden-QAM polling as-is) and full-commit-SHA pinning of
GitHub Actions (leave the major-tag pins as-is). Do not touch those.

You are the implementer. Develop on a branch off `dev`. Do not write reviews. Do not
create, delete, or edit anything under `docs/review/` except committing review notes the
orchestrator writes there.

---

## Scope (what to do / not do)

**In scope (work units below):**

| Finding | Source | Work unit |
|---|---|---|
| Syncthing watcher: concurrent same-signature start can leave a started-but-unregistered (orphan) watch thread | review nit | WU-1 |
| `PluginUpdater` combines parsing/validation/cooldown/ledger; 403/429 cooldown block duplicated in `check_for_update()` & `revalidate()` | holistic #7 | WU-2 |
| `handleAppStart`/`handleAppExit` are long inline transaction coordinators with mutable cleanup flags | holistic #5 | WU-3 |
| Update workflow is an implicit state machine across ~16 useState/useRef + 5 effects | holistic #2 (refactor half) | WU-4 |
| `LudusaviContent` is an 854-line god component; `runForceOperation`/`runSnapshotRestore` duplicate the finalize sequence | holistic #6 | WU-5 |

**Out of scope — do NOT implement:** event-driven QAM capture (leave `window.setInterval(captureSteamUiGameContext, 500)` in `LudusaviContent.tsx`); full-SHA action pinning (leave `@v6`/`@v8.1.0` tags). Also do not re-address anything already remediated by `june-review-remediation` (lock fail-closed, PID identity, fuzzy match, backup-browser bounds, watcher lock scoping, install-abort, settings single-source, lifecycle bookkeeping executor, quality gates).

**Resolved by verification — no action:** the previously-suspected dead `if record_order == "after_log": pass` branch in `lifecycle.py` is **not dead** (it records history after logging for `after_log` callers). Leave it.

---

## Orchestration Contract

Plan path:
```text
docs/plans/2026-06-19_remaining-review-findings.md
```
Implementation branch:
```text
feat/remaining-review-findings
```
Round-complete marker:
```text
/tmp/sdh_ludusavi/remaining-review-findings_finished
```
Finalized marker:
```text
/tmp/sdh_ludusavi/remaining-review-findings_finalized
```
Review notes (audit records — committed, never deleted/edited by you):
```text
docs/review/remaining-review-findings-review-*.md
```

Each review note ends with exactly one of `STATUS: CHANGES_REQUESTED` or `STATUS: APPROVED`.

**Setup:** Use the `implementer` skill. Create `feat/remaining-review-findings` off `dev`. Write this plan to `docs/plans/2026-06-19_remaining-review-findings.md` and commit it first.

**On completing a round (initial implementation or a review round):**
1. Run the quality gates (see "Quality Gates").
2. Ensure the working tree is clean.
3. Commit all relevant changes (Conventional Commits, atomic per work unit / sub-commit).
4. Write the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished remaining-review-findings
   ```
5. Then either keep polling `docs/review/remaining-review-findings-review-*.md` or exit cleanly (the orchestrator resumes you via `agy -c -p`). On every resume, scan existing review notes **first** (read the latest note's committed content via `git show HEAD:docs/review/remaining-review-findings-review-*.md`) before waiting for new file events.

**When a `STATUS: CHANGES_REQUESTED` note appears:**
1. `scripts/orchestration/clear-finished remaining-review-findings`
2. Read the note; implement every requested change.
3. Run quality gates; commit the fixes.
4. Commit the review note if not already committed.
5. `scripts/orchestration/mark-finished remaining-review-findings`
6. Keep polling or exit cleanly.

**When a `STATUS: APPROVED` note appears:**
1. Confirm all review notes are committed and the tree is clean.
2. `scripts/orchestration/finalize remaining-review-findings`
3. Confirm `/tmp/sdh_ludusavi/remaining-review-findings_finalized` exists.
4. Stop polling and exit. (Finalize merges `feat/remaining-review-findings` into `dev`, cleans up the branch, pushes `dev`, and requests a dev release. Steam Deck / on-device testing is deferred until after the dev push.)

---

## Global refactor rules (apply to every work unit)

- **No behavior change** (except WU-1, which fixes a race). Preserve public RPC method names, signatures, and return dict/object shapes. Preserve all existing test expectations — existing tests must pass **without weakening assertions**; only add tests.
- **Strict TDD applies to WU-1** (behavior change → write the failing concurrency test first). The decompositions (WU-2…WU-5) are structural; lead each with characterization tests for the unit you extract, and keep the full suite green throughout.
- **Architecture guard tests are load-bearing.** `tests/test_architecture.py`, `tests/test_module_size_budgets.py`, `tests/test_architectural_constraints.py`, `tests/test_status_flow_diagram.py` enforce layering and per-file LOC budgets. When you create new modules or shrink files, **update `tests/test_module_size_budgets.py`** to add budgets for new modules and tighten the shrunk ones, and keep `tests/test_architecture.py` layering rules satisfied (no new cross-layer imports). Do not delete or loosen these guards to make room.
- **One coherent commit per logical step** (Conventional Commits). Large work units use several atomic sub-commits (noted per WU) — land the low-risk extraction first, then build on it.
- No new third-party dependencies. Keep caches under `/tmp/sdh_ludusavi/` via `./run.sh`.

---

## Work Units

Order: WU-1 → WU-2 (backend, independent) → WU-3 → WU-4 (frontend controllers) → WU-5 (QAM god-component, composes the controllers — last). Each is independent enough to land and be reviewed on its own.

---

### WU-1 — Fix the Syncthing watcher orphan-thread race (correctness)
**Files:** `py_modules/sdh_ludusavi/syncthing/watcher.py`, `tests/test_watcher.py`
**Verified state:** `start_watch` is already 3-phase (prepare outside lock → register under lock → stop-old/`watch.start()` outside lock). Phase 2 (under lock) does `self.watches[watch_id] = watch`; phase 3 (no lock) does `for old in watches_to_stop: old.stop()` then `watch.start()`. There is **no re-check** before `watch.start()`. Two concurrent identical-signature starts can interleave so thread B removes thread A's just-registered watch (into B's `watches_to_stop`) before A reaches `watch.start()` — A then starts a watch that is no longer registered (orphan thread until TTL), and/or B calls `stop()` on A's never-started watch.

**Change:**
- In phase 3, before starting, re-check under the lock whether this watch is still the registered one:
  ```python
  with self.lock:
      still_registered = self.watches.get(watch_id) is watch
  for old_watch in watches_to_stop:
      old_watch.stop()
  if still_registered:
      watch.start()
  # else: superseded before we started — discard without starting (do not orphan)
  ```
- Make `SyncthingWatch.stop()` **safe to call on a never-started watch** (guard the `thread.join()` — e.g. only join if the thread exists and was started; `threading.Thread.join()` raises `RuntimeError` if the thread was never started). A superseding start must be able to `stop()` a replaced watch that may not have started yet.
- Keep all public return shapes unchanged. Same-signature replacement must still leave **exactly one** registered, started watch.

**Tests (write first):**
- Concurrency: drive two identical-signature `start_watch` calls that interleave at the phase boundary (use a `threading.Event`/barrier injected into the prepare phase). Assert exactly one watch remains registered AND no started-but-unregistered watch thread survives (track started watches via a stub `SyncthingWatch` whose `start`/`stop` record calls; assert every started watch is either registered or stopped).
- `stop()` on a never-started watch does not raise.
- Existing `test_watcher.py` concurrency/replacement tests still pass.

**Risk:** use barriers/events, not sleeps. Don't reintroduce holding the lock across `start()`/`join()` (that was the original bug WU-E fixed). Keep the prepare/probe work outside the lock.

---

### WU-2 — Split `PluginUpdater` into focused collaborators
**Files:** `py_modules/sdh_ludusavi/updater.py` (928 lines), `py_modules/sdh_ludusavi/updater_models.py`, new sibling modules under `py_modules/sdh_ludusavi/`, `tests/test_updater.py`, `tests/test_updater_service.py`, `tests/test_updater_lazy.py`, `tests/test_updater_models.py`, `tests/test_updater_client.py`, and `tests/test_module_size_budgets.py`.
**Verified state:** `PluginUpdater` (updater.py ~309-929) combines version parsing/selection, remote release validation, 403/429 cooldown policy, and the pending-install ledger. The rate-limit cooldown block (parse `retry-after`/`x-ratelimit-reset`, default 1 minute, set `self._rate_limited_until`, shape the `failed` payload) is **duplicated** in `check_for_update()` (~511-558) and `revalidate()` (~718-765).

**Sub-commits (land in this order):**
1. **Extract the rate-limit parser (low-risk dedup first).** Add a pure helper (e.g. `parse_rate_limit_retry_after(headers, now) -> str` and/or a small `RateLimitPolicy`) used by **both** `check_for_update()` and `revalidate()`. No behavior change — same retry-after string and `_rate_limited_until` result. Add focused unit tests for the parser (retry-after seconds, x-ratelimit-reset epoch, missing-header default) without constructing the full updater.
2. **Separate the collaborators.** Move pure release parsing/selection (the `prevalidate_release_candidate` / `validate_prevalidated_candidate` / `select_candidate` family, ~110-284) and the pending-install ledger (cache payload load/promote/reconcile) into focused modules/classes. Keep `PluginUpdater` as a small façade that coordinates: release discovery/validation, the cooldown policy, the pending-install ledger, and persistence (`_save_callback`).
3. Keep `updater_models.py` as the dataclass/model home; add new models there rather than scattering them.

**Constraints:** public service/RPC behavior unchanged — `check_for_update`, `revalidate`, `record_update_install_requested`, `confirm_update_install_handoff`, `clear_pending_update_install`, `reconcile_pending_install`, `adopt_persisted_cache` must keep identical signatures and return payloads. The inter-process/persistence locking and the `_state_lock` ordering must be preserved.

**Tests:** rate-limit and pending-install state transitions must be **independently unit-testable without constructing the full updater** (new tests). All existing `test_updater*.py` must pass unchanged. Update `tests/test_module_size_budgets.py` with budgets for the new modules and a tightened budget for the shrunk `updater.py`.

**Risk:** highest-value backend refactor but `updater.py` is dense with locking + persistence; move logic in small steps, run `test_updater*.py` after each. Preserve the cooldown's "do not overwrite a successful result, only transient cooldown" semantics.

---

### WU-3 — Extract explicit start/exit lifecycle transactions
**Files:** `src/controllers/gameLifecycleController.tsx` (560 lines), new sibling module(s) under `src/controllers/`, `src/controllers/gameLifecycleController.test.ts`, `src/controllers/gameLifecycleController.logging.test.ts`, and a new test for the extracted decision logic.
**Verified state:** `handleAppStart` (~207-381, ~175 lines) and `handleAppExit` (~383-535, ~153 lines) are inline transaction coordinators: pre/post-game watch setup, pause/resume, check/restore-or-backup RPC, conflict resolution, Syncthing monitor/handoff, status publication, history sync, and terminal cleanup gated on mutable booleans (`paused`, `retainPreGameWatch`, `handoffTransferred`, etc.). `SILENT_SKIPPED_REASONS` is already a module constant (line ~26) — reuse it.

**Change:**
- Extract the start and exit workflows into **pure decision functions** (or transaction objects) that take the relevant inputs/results and return an explicit list of commands/effects (e.g. `{ resumeProcess, cancelWatch, transferWatch, publishStatus, hideStatus, syncHistory }`), with React/`gameLifecycleController` responsible only for executing the returned effects.
- **Centralize terminal cleanup** so no result branch can leave a paused process or an unowned/leaked Syncthing watch — one cleanup path consumes the decision result and guarantees process-resume, watch cancellation/transfer, status completion/hide, and history sync.
- Replace duplicated silent-reason / result-status branching with typed policy tables (reuse `SILENT_SKIPPED_REASONS`).
- Keep the controller's public hook API and observable behavior identical.

**Tests (write first for the extracted functions):** table-driven tests over **every** lifecycle result status and **every** cleanup obligation, asserting no terminal path leaves a paused process or unowned watch. Existing `gameLifecycleController.test.ts` and `...logging.test.ts` must pass unchanged. Add budget for any new module in `tests/test_module_size_budgets.py`.

**Risk:** correctness-sensitive (process resume + watch ownership). Decision functions should be pure and exhaustively tested; the React layer just runs effects. Do not change the RPC calls or the status-surface contract.

---

### WU-4 — Make the update workflow an explicit reducer/controller
**Files:** `src/controllers/pluginUpdateController.tsx` (521 lines), new sibling reducer/controller module under `src/controllers/`, `src/controllers/pluginUpdateController.test.tsx` (exists — extend it), `src/types/index.ts` if a state type is added.
**Verified state:** the workflow is an implicit state machine across ~9 `useState` + ~8 `useRef` + 5 `useEffect` (hydration/check/install/handoff). The install-abort correctness fix and `RpcResult<…>` typing are **already done** (do not redo them) — this WU is the structural reducer extraction only.

**Change:**
- Move check/install/handoff transitions into a **framework-independent reducer or controller** with a discriminated state such as `hydrating | idle | checking | available | recording | handoff_pending | installed | failed`. Collapse the scattered booleans/refs into that state where they represent workflow phase (keep refs that are genuinely imperative, e.g. timeout ids / in-flight cancellation tokens, but drive phase from the reducer).
- Keep React responsible only for binding props/effects and rendering controller state. Preserve the public hook API (`usePluginUpdateController(...)` return shape) so callers in `LudusaviContent.tsx` are unaffected.
- Preserve the existing install-abort behavior: Decky Installer is invoked only when revalidation and pending-install persistence both succeed.

**Tests:** extend `pluginUpdateController.test.tsx` with reducer transition tests: failed pending-install persistence, timed-out checks, stale checks, slow/rejected handoff, hydration with a pending install, unmount cleanup. Pure reducer transitions should be testable without rendering React. All existing controller tests pass unchanged. Add a budget entry for the new reducer module.

**Risk:** this controller has subtle timeout/stale-check/cancellation logic. Extract the reducer as a pure function first (with tests), then wire the hook to it; do not alter timing/cancellation semantics.

---

### WU-5 — Decompose the QAM god component (do last)
**Files:** `src/components/qam/LudusaviContent.tsx` (854 lines), new sibling hook/controller modules under `src/components/qam/` (e.g. `useInitialContent`, `useGameRefresh`, `useSteamContext`, `useManualOperations`), new tests for each extracted unit, and `tests/test_module_size_budgets.py`.
**Verified state:** `LudusaviContent` owns initial hydration, metadata cache, game-refresh policy, Steam-context selection, settings controllers, log retrieval, manual backup/restore (`runForceOperation` ~624-706) and snapshot restore (`runSnapshotRestore` ~708-787). The two operation paths **duplicate** the same finalize sequence (refresh games → operation status → recent logs → game history → apply to store + setOperation/setLogs/setGameHistory, with shared `finally` resetting `operationInProgress`/`busyLabel`).

**Sub-commits (land in this order):**
1. **Extract the shared manual-operation finalize pipeline (low-risk dedup first).** One function/hook that runs the identical refresh/status/logs/history finalize used by backup, latest restore, and snapshot restore — `runForceOperation` and `runSnapshotRestore` both call it (only the operation RPC differs). No behavior change; add a unit test for the pipeline with mocked RPCs.
2. **Extract focused hooks/controllers** for initial-content loading, Steam-context selection, and game refresh, each with **injected RPC dependencies** (so they're testable without rendering the full QAM). Reuse existing store methods (`ludusaviStore.setGameHistory`, `applyRefreshResult`, the settings runtime) — do not duplicate store logic.
3. **Reduce `LudusaviContent` to state selection, controller composition, and section rendering.** Leave the out-of-scope 500ms hidden-QAM polling effect as-is.

**Tests (write first for each extracted unit):** unit tests for the load, refresh, and manual-operation pipelines without rendering the full QAM (inject mock RPCs). Assert backup + latest restore + snapshot restore all share one finalize implementation. Existing QAM-related tests pass unchanged. Update `tests/test_module_size_budgets.py`: add budgets for the new QAM modules and tighten `LudusaviContent.tsx`'s budget to its new (smaller) reality.

**Risk:** biggest/highest-churn unit; it composes the controllers refactored in WU-3/WU-4 — do it last. Preserve the exact user-visible operation flow (optimistic status, logs, history refresh, busy-label reset in `finally`). Don't change the settings-runtime or store contracts.

---

## Quality Gates (run before every `mark-finished`)

```bash
./run.sh bash scripts/quality_gates.sh check
```

This runs ruff (check + format-check), `ty`, the full `pytest` suite, and `pnpm run verify` (frontend supply-chain + build + vitest + tsc), with frontend deps installed before pytest. All must pass. (Equivalent expanded form: `./run.sh uv run ruff check .` → `ruff format --check .` → `ty check py_modules/sdh_ludusavi/` → `pnpm install --frozen-lockfile` → `pytest` → `pnpm run verify`.)

## Verification (end-to-end, before approval)

- Full backend suite green, including new WU-1 concurrency tests, new WU-2 parser/ledger unit tests, and all existing `test_updater*.py`, `test_watcher.py`, `test_lifecycle.py` unchanged.
- Full frontend suite green (`pnpm run verify`): new WU-3 decision-function tests, extended WU-4 reducer tests, new WU-5 hook/pipeline tests, and existing `gameLifecycleController.*test`, `pluginUpdateController.test.tsx`, settings tests unchanged.
- Architecture/budget guards green: `tests/test_architecture.py`, `tests/test_module_size_budgets.py` (updated with new-module budgets + tightened shrunk-file budgets), `tests/test_architectural_constraints.py`, `tests/test_status_flow_diagram.py`.
- `git status --short` clean of caches (`__pycache__`, `.ruff_cache`, etc.).
- Confirm the out-of-scope items are untouched: `window.setInterval(captureSteamUiGameContext, 500)` still present in `LudusaviContent.tsx`; action refs still `@v6`/`@v8.1.0` (no SHA pinning).
- On-device Steam Deck testing is deferred until after the `dev` push (finalize step).

## Constraints
- No behavior change except WU-1 (race fix). Preserve public RPC/hook APIs and return shapes; existing tests pass without weakened assertions.
- Atomic commits per logical step (the noted sub-commits for WU-2 and WU-5 land low-risk extraction first).
- No new third-party dependencies.
- Do not implement the out-of-scope items (event-driven QAM capture, full-SHA action pinning) and do not re-address `june-review-remediation` findings.
- Do not create, delete, or edit files under `docs/review/` except to commit review notes the orchestrator writes there.
