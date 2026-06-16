# Over-Engineering Cleanup — Implementation Plan

## Context

A whole-tree audit found a set of abstractions, dead code, and tests that cost
maintenance without protecting behavior: structural "shape" tests that freeze
file size and import layout, a generic React-icon serializer driving a single
static icon, a test-only persistence storage mode, an unused dependency, five
hand-duplicated settings mutators, duplicated CI setup, and several dead or
redundant backend helpers. This plan removes them. Every change is either a pure
deletion of unreachable/unused code, a behavior-preserving refactor, or a test
migration. Two findings that looked cuttable were rejected and are explicitly out
of scope (see "Out of Scope") so they are not "tidied" by mistake.

Outcome: ~460 lines of code/tests removed at high confidence, one dependency
dropped, plus an optional larger refactor of the settings mutators. Production
runtime behavior is unchanged.

## Work is organized into ordered, independently committable units

Land them in order. Each unit is its own commit (or small set of commits) so a
review round can request changes on one without blocking the others. Units A–H
are low/medium risk; Units I and J are the heaviest — do them last.

Combine vs. separate:
- **Combine** the three trivial backend removals in Unit A into one commit.
- **Combine** the two CI dedup edits (Unit H1, H2) conceptually but keep them as
  separate commits; keep the composite-action extraction (H3) a separate commit.
- **Separate** every test-migration unit from every pure-removal unit.
- **Separate** Unit J (settings refactor) from everything; it is the only unit
  that adds new implementation code and must be done test-first.

---

## Unit A — Remove dead/redundant backend internals (one commit)

Pure removals of unreachable code. No behavior change, no test migration.

Files:
- `py_modules/sdh_ludusavi/watchdog.py` — delete `_child_pids` (lines ~256–257).
  Confirmed zero callers in `src/`, `py_modules/`, `tests/`.
- `py_modules/sdh_ludusavi/coordinator.py` — in `run_locked`, delete the
  `if self._operation.is_running:` re-check that releases the lock and raises
  (lines ~56–58). The non-blocking `acquire()` above already guarantees
  exclusivity; `is_running` is mutated only at lines 61/77 while the lock is
  held, so this branch is unreachable. Keep the `acquire()` and the rest.
- `py_modules/sdh_ludusavi/gateway.py` — in `get_adapter` (lines ~46–62),
  collapse the two double-checked-lock blocks into one. Ensure the adapter
  exists (create under the lock if `None`), then make a single guarded call to
  `self._log_ludusavi_diagnostics(self._adapter)` (it is already idempotent via
  `_diagnostics_logged`). Drop the now-redundant second `if not
  self._diagnostics_logged` block and the trailing `if self._adapter is None`
  re-check.

Tests: add/update none. Run the full backend suite to prove behavior is
unchanged, paying attention to `tests/test_coordinator.py`,
`tests/test_service.py` (including the concurrent lazy-refresh test), and
`tests/test_watchdog.py`.

Commit: `refactor(backend): remove dead and redundant internal code`

---

## Unit B — Remove test-only backend seams (separate commits)

Two helpers that exist only for tests. Migrate the tests to the real call site,
then delete the wrapper.

B1 — `_match_game` service facade:
- `py_modules/sdh_ludusavi/service.py` — delete `_match_game` (lines ~377–378),
  a 2-line delegator to `self._registry.match_game`.
- Migrate callers in `tests/test_matching.py`, `tests/test_issue_1_matching.py`,
  and `tests/test_service.py` (around line 1765) to call
  `service._registry.match_game(...)` directly. `tests/test_service.py:990`
  already uses that form — copy it.
- Commit: `refactor(service): drop test-only _match_game facade`

B2 — `find_stale_sibling_pids` wrapper:
- `py_modules/sdh_ludusavi/singleton.py` — delete `find_stale_sibling_pids`
  (lines ~138–141). Production never calls it.
- `tests/test_singleton.py` — replace its uses with
  `sorted(s.pid for s in find_stale_siblings(...))` inline.
- Commit: `refactor(singleton): test find_stale_siblings directly`

Risk: a kept shape test in `tests/test_architecture.py` references
`_registry_match_game` (a different name) — no conflict. Run full pytest after
each commit.

---

## Unit C — Remove unused `UpdaterCacheModel` (one commit)

`UpdaterCacheModel` is referenced only by its own test; the production updater
persists raw mappings and never constructs it.

Files:
- `py_modules/sdh_ludusavi/updater_models.py` — delete the `UpdaterCacheModel`
  dataclass (lines ~138–194). After deletion, check whether the `field` import
  and the `Mapping` import are still used elsewhere in the file; remove any that
  become unused (ruff will flag them).
- `tests/test_updater_models.py` — remove `UpdaterCacheModel` from the import
  (line 5) and delete only `test_updater_cache_model` (lines ~42–66). **Keep**
  `test_parse_release_manifest` and the `ReleaseManifest` / `parse_release_manifest`
  imports — that file still covers manifest parsing.

Verify: `grep -rn UpdaterCacheModel py_modules` returns nothing after the change.

Commit: `refactor(updater): remove unused UpdaterCacheModel`

---

## Unit D — Delete code-shape tests (one commit)

These assert file size, class span, import layout, and documentation strings
rather than behavior. Delete the pure ones wholesale; keep only the genuine
layering/security invariants.

Delete entirely:
- `tests/test_module_size_budgets.py`
- `tests/test_status_flow_diagram.py`

Edit `tests/test_architecture.py` — **keep** `test_no_imports_from_service`
(anti-circular-import layering). Delete the rest:
`test_no_service_sys_modules`, `test_no_private_service_access`,
`test_lifecycle_has_no_service`, `test_service_facade_class_size`,
`test_no_registry_match_game_rebinding`, `test_no_direct_service_log_in_gateway`,
`test_no_service_references_in_gateway`, `test_updater_no_service_any`,
`test_main_no_updater_state_access`, `test_service_stores_pluginupdater`,
`test_updater_owns_orchestration`, `test_no_duplicate_sanitize_game_name`.
Remove now-unused imports/helpers (`ast`, `_get_project_source_files`) if nothing
kept uses them.

Edit `tests/test_architectural_constraints.py` — **keep** `test_no_full_sha_logging`
(security) and `test_no_direct_steam_global_casts` (real centralization seam).
Delete `test_no_updater_private_service_access` and
`test_no_updater_orchestration_in_main`.

Do this unit early so later edits do not trip a budget/shape assertion mid-stream.

Commit: `test: remove code-shape and doc-pinning tests`

---

## Unit E — Inline static cloud-complete SVG; drop the icon serializer (one commit)

Every status icon in `autoSyncStatusRenderer.tsx` is a hand-written static SVG
string except `syncthing_complete`, which alone drives a generic React-icon
serializer + cache + the `react-icons/io` import.

File: `src/surfaces/autoSyncStatusRenderer.tsx`

Steps:
1. Capture the exact current output: temporarily print/log
   `serializeIcon(IoMdCloudDone)` (a throwaway vitest case or node snippet) to
   get the serialized `<svg ...>...</svg>` string the current code produces.
2. In `iconSvgForAutoSyncStatus`, replace the `syncthing_complete` branch
   (`return getSerializedIcon(status);`) with `return '<the captured string>';`
   so rendering is byte-identical to today.
3. Delete `svgAttributeMapping`, `serializeSvgNode`, `serializeIcon`,
   `getSerializedIcon`, `serializedIconsCache`, and the `import { IoMdCloudDone }
   from "react-icons/io";` line.
4. `escapeHtml` is used by the deleted serializer. Grep the file; remove
   `escapeHtml` **only if** it has no remaining references.
5. Keep `iconSvgForAutoSyncStatus`, `autoSyncStatusText`,
   `isLudusaviRunningStatus`, `isSyncthingActiveStatus`, `shouldAutoHideStatus`,
   and `renderAutoSyncStatusHtml` exactly as exported.

Tests: `src/surfaces/autoSyncStatusSurface.test.ts` exercises
`iconSvgForAutoSyncStatus` (the public entry). The static string must keep those
green (non-empty, distinct, expected `not.toContain` checks). Add an assertion
that `iconSvgForAutoSyncStatus("syncthing_complete")` returns a non-empty SVG if
one does not already exist.

Commit: `refactor(status-icons): inline cloud-complete SVG, drop react-icon serializer`

---

## Unit F — Replace `createContentLoadCoordinator` with a plain object (one commit)

The factory wraps two nullable promise fields in get/set/dispose accessors that
add no encapsulation.

Files:
- `src/runtime/contentLoadCoordinator.ts` — replace the factory with a tiny
  object holding `initPromise: Promise<OperationStatus> | null` and
  `metadataPromise: Promise<void> | null` (a factory that returns
  `{ initPromise: null, metadataPromise: null }` is fine; keep a no-op-free
  shape). Drop the four accessors and `dispose`.
- `src/runtime/pluginRuntime.ts` — update the type and the unmount sequence
  (remove the `contentLoad.dispose()` call or null both fields there instead).
- `src/components/qam/LudusaviContent.tsx` — replace `getInitPromise()/
  setInitPromise(x)/getMetadataPromise()/setMetadataPromise(x)` with direct field
  reads/writes (`runtime.contentLoad.initPromise` etc.) at lines ~284–379.
- `src/runtime/pluginRuntime.test.ts` — update the fake (lines ~78–81) and the
  assertions (lines ~30–55) to the field form.

Tests: run vitest; `pluginRuntime.test.ts` is the safety net.

Commit: `refactor(runtime): replace content-load coordinator accessors with a plain object`

---

## Unit G — Drop the unused `react-router` dependency (one commit)

`react-router` is declared in `dependencies` but never imported in `src/` and not
externalized in `rollup.config.js`; `@decky/*` only reference
`@types/react-router@5.x`.

Steps:
1. `package.json` — remove the `"react-router"` entry from `dependencies`.
2. Regenerate the lockfile: `./run.sh pnpm install` (updates `pnpm-lock.yaml`).
   Note `check_frontend_supply_chain.sh` requires exact versions and a frozen
   lockfile, so the lockfile must match before the gate runs.
3. Commit both `package.json` and `pnpm-lock.yaml`.

Verify: `./run.sh pnpm run verify` (supply-chain audit + frozen install + tsc +
build + vitest) passes. Watch for any peer-dependency warning naming
`react-router`; a warning is acceptable (Decky provides routing at runtime), a
hard install failure is not — if it fails, stop and report.

Commit: `chore(deps): drop unused react-router dependency`

---

## Unit H — CI dedup (separate commits)

H1 — Remove the duplicate typecheck:
- `scripts/check_frontend_supply_chain.sh` — delete the standalone
  `pnpm run typecheck` (line ~63). `pnpm test` already runs `tsc --noEmit` via
  its `&& pnpm run typecheck` (see `package.json` `scripts.test`), so typecheck
  still runs once.
- Verify: `./run.sh pnpm run verify` still typechecks and fails on a deliberate
  type error (sanity check, then revert the deliberate error).
- Commit: `ci(frontend): remove duplicate typecheck from verify`

H2 — Let frontend verify own the install (gated on a build check):
- The verify script already runs `pnpm install --frozen-lockfile --ignore-scripts`
  (line ~40); the per-workflow `pnpm install --frozen-lockfile` step in
  `.github/workflows/ci.yml`, `dev-release.yml`, and `release.yml` precedes it and
  duplicates it (and runs install scripts, weakening the hardened install).
- **Before removing anything**, prove `rollup -c` builds after a scripts-disabled
  install: from a clean clone state run the verify script's install line, then
  `./run.sh pnpm run build`. If the build needs the scripts-enabled install
  (e.g., a native module fails), **keep** the workflow install step, add a one-line
  comment explaining why, and skip H2.
- If the build succeeds, remove the standalone `pnpm install` step from all three
  workflows. The Python gate steps (ruff/ty/pytest) do not need `node_modules`.
- Commit: `ci: let frontend verify own dependency installation`

H3 — Extract a composite action for shared setup:
- `ci.yml`, `dev-release.yml`, and `release.yml` repeat the same prefix:
  checkout, setup-node@v6, pnpm/action-setup@v6, pnpm store dir + cache, install,
  setup-python@v6, setup-uv@v8.1.0, uv sync, and the ruff/ty/pytest/verify gate.
- Diff the three setup blocks first; extract **only** the steps that are byte-
  identical into `.github/actions/setup-toolchain/action.yml` (a `composite`
  action). Reference it from each workflow with `uses: ./.github/actions/setup-
  toolchain`. Keep job-level `permissions`, release/publication jobs, and any
  per-workflow differences out of the composite.
- Verify: the YAML parses (e.g. `python -c "import yaml;
  [yaml.safe_load(open(f)) for f in (...)]"`). `ci.yml` is exercised on the push to
  `dev` after finalization; `dev-release.yml`/`release.yml` only run on dispatch/
  tag, so they cannot be fully verified pre-merge — preserve their existing
  behavior exactly and flag this in the relevant review note response.
- Commit: `ci: extract shared setup into a composite action`

---

## Unit I — Remove the test-only combined `state_path` persistence mode (one commit)

`PersistenceManager`'s combined single-file mode (`_combined_state_path`) is
reachable only via `state_path=`, which no production caller passes — `main.py`
constructs the service with `settings_store` + `cache_path`. Removing it collapses
persistence to a single read/modify/write path.

Files:
- `py_modules/sdh_ludusavi/persistence.py` — remove `_combined_state_path` and the
  combined branches in `_load_all_locked`, `save_settings`, `save_cache`, plus
  `_load_combined_settings`, `_load_combined_cache`, `_save_combined`. The split
  `settings_store` + `cache_path` path becomes the only path; keep
  `_InterProcessLock`, `JsonSettingsStore`, and atomic temp+rename writes.
- `py_modules/sdh_ludusavi/service.py` — remove the `state_path` parameter from
  `SDHLudusaviService.__init__` and the `state_path cannot be combined ...`
  guard (lines ~40–41); forward only `settings_store` + `cache_path`.
- Migrate every test that constructs the service or manager with `state_path=` to
  the split form. Affected files include `tests/test_issue_2_state_load.py`,
  `tests/test_issue_3_refresh_robustness.py`, `tests/test_refinements.py`,
  `tests/test_log_buffer.py`, `tests/test_last_operation_sync.py`,
  `tests/test_issue_5_env_logging.py`, `tests/test_issue_1_matching.py`, and any
  other `state_path=` hit (`grep -rn "state_path=" tests`). To limit churn, add a
  small local helper or fixture that builds `settings_store=JsonSettingsStore(tmp
  / "settings.json"), cache_path=tmp / "cache.json"` and reuse it.

Tests: behavior is preserved for production. Run the full backend suite; the
migrated tests are the proof. Confirm `grep -rn "state_path" py_modules` shows no
remaining references outside any intentionally-kept docstring.

Risk: this changes the service constructor signature. Do it as one atomic commit
so the signature and all call sites move together.

Commit: `refactor(persistence): remove test-only combined state_path mode`

---

## Unit J — Unify the five settings mutators (test-first; do last)

`settingsMutationRuntime.ts` hand-duplicates the same algorithm five times
(auto-sync, notifications, selected-game, update-channel, automatic-checks):
optimistic store update → enqueue on the serial queue → `withTimeout` RPC →
`updateSeq === xSeq` supersede guard → late-resolution handling → rollback to
`lastPersisted*` → failure notify → structured logging. The behavior is correct
and must be preserved; only the duplication is removed.

This is the only unit that adds new implementation code, so follow TDD: write the
covering test first, watch it fail, then implement.

File: `src/settings/settingsMutationRuntime.ts`

Steps:
1. In `src/settings/settingsMutationRuntime.test.ts`, add tests (if not already
   present) that pin the cross-cutting semantics on at least two settings:
   optimistic update applied immediately, a stale (superseded) RPC result does
   not clobber a newer value, a failed RPC rolls back to the last persisted value
   and notifies, and the queue serializes concurrent updates. Run vitest and
   confirm the new tests pass against current code (they encode existing
   behavior) — if any fail, the current behavior was misread; reconcile before
   refactoring.
2. Introduce one generic executor, e.g.
   `mutateSetting<T>({ seq, readSeq, optimistic, rpc, applyResult, rollback,
   label, log })`, that owns the enqueue/timeout/supersede/rollback/notify dance.
3. Re-express the five mutators as thin callers of `mutateSetting`. Preserve the
   per-field specifics that differ: `selected_game`'s `lastQueuedSelectedGame`
   tracking, and the notifications partial-merge (`{ ...previous, [key]: enabled }`).
   Keep the five sequence counters (or fold them into per-field refs the executor
   reads) so supersede semantics are unchanged.
4. Keep the public surface (`createSettingsMutationRuntime`, the controller it
   returns, queue subscription) identical so `LudusaviContent.tsx` is untouched.

Tests: the full `settingsMutationRuntime.test.ts` suite must stay green; the new
edge tests from step 1 guard the refactor.

Risk: highest of all units — out-of-order resolution and rollback are subtle.
This is also the most likely unit to receive `CHANGES_REQUESTED`; keeping it last
means the earlier banked commits are already reviewable.

Commit: `refactor(settings): unify setting mutators into one executor`

---

## Quality gates (run before marking any round complete)

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

The orchestration gate runs the project checks. If you run them directly:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
```

When formatting/linting, prefer targeting files changed in this branch; do not
reformat unrelated files.

A round is complete only when: all in-scope work is done, all tests pass,
ruff/ty/build/vitest gates pass, review notes have not been deleted, the working
tree is clean, and every change is committed.

## Verification

- Backend units: `./run.sh uv run pytest` green after each unit; targeted runs of
  the named test files during development.
- Frontend units: `./run.sh pnpm run verify` (tsc + build + vitest + supply chain)
  green; for Unit G confirm the bundle builds with `react-router` gone.
- CI units: validate every workflow and the composite action parse as YAML; note
  that `dev-release.yml`/`release.yml` are only exercised at dispatch/tag time.
- Steam Deck / on-device testing is deferred until after `dev` is pushed and a dev
  release is requested.

## Risks and edge cases

- **Unit A/I behavior preservation:** the removed branches are unreachable / the
  combined mode is test-only, but the concurrency and persistence tests are the
  proof — do not skip the full suite.
- **Unit E:** capture the serializer's exact output before deleting it so the
  rendered icon is byte-identical; remove `escapeHtml` only if unreferenced.
- **Unit G:** removing a runtime dep regenerates the lockfile; commit
  `pnpm-lock.yaml` together with `package.json`. A `react-router` peer warning is
  acceptable; a hard install failure is not.
- **Unit H2:** only remove the workflow install after proving the scripts-disabled
  install still builds; otherwise keep it with a comment.
- **Unit H3:** extract only byte-identical steps; release/dev-release workflows
  cannot be fully verified before merge.
- **Unit I:** constructor signature change — keep it atomic across `service.py`
  and all tests.
- **Unit J:** subtle out-of-order/rollback semantics — test-first, last to land.

## Definition of done

- All in-scope units committed on `feat/over-engineering-cleanup`.
- `ruff check`, `ruff format`, `ty check`, `pytest`, and `pnpm run verify` pass.
- No generated caches inside the repo; caches under `/tmp/sdh_ludusavi`.
- A session log recorded under `docs/agent_conversations/` per the project
  protocol.
- Review notes committed; finalized via the orchestration script after approval.

---

## Orchestration contract

**Slug:** `over-engineering-cleanup`

**Plan file:**

```text
docs/plans/2026-06-15_over-engineering-cleanup.md
```

**Implementation branch:**

```text
feat/over-engineering-cleanup
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/over-engineering-cleanup_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/over-engineering-cleanup_finalized
```

**Review notes:**

```text
docs/review/over-engineering-cleanup-review-*.md
```

Each review note ends with exactly one trailer: `STATUS: CHANGES_REQUESTED` or
`STATUS: APPROVED`.

### Required agent protocol

1. Use the **implementer** skill.
2. Work from the repository root; branch from `dev`.
3. Commit this plan as the first commit on the implementation branch.
4. Follow TDD where behavior changes are testable (notably Unit J).
5. Run quality gates before marking any round complete.
6. Do not write your own review. Do not create or delete files under
   `docs/review/`. Review notes are durable audit records and must be committed.
7. After finalization, stop polling and exit cleanly.

### Setup

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/over-engineering-cleanup
git add docs/plans/2026-06-15_over-engineering-cleanup.md
git commit -m "docs(plan): add over-engineering-cleanup implementation plan"
```

### Mark round complete

When a round's work is done and the tree is clean:

```bash
scripts/orchestration/mark-finished over-engineering-cleanup
```

Then poll `docs/review/over-engineering-cleanup-review-*.md`.

### Review polling loop

On a new note ending `STATUS: CHANGES_REQUESTED`:

```bash
scripts/orchestration/clear-finished over-engineering-cleanup
# implement every requested change
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
# commit code/docs fixes
git add docs/review/over-engineering-cleanup-review-*.md
git commit -m "docs(review): record over-engineering-cleanup review notes"
scripts/orchestration/mark-finished over-engineering-cleanup
# continue polling
```

### Approval handling

On a note ending `STATUS: APPROVED`:

```bash
scripts/orchestration/check-review-notes-committed over-engineering-cleanup
git status --short
scripts/orchestration/finalize over-engineering-cleanup
# confirm /tmp/sdh_ludusavi/over-engineering-cleanup_finalized exists, then stop
```

Finalization (via the script) commits any outstanding review note, merges the
branch into `dev`, cleans up the branch, pushes `dev`, and requests a dev
release. Do not merge manually unless the finalize script fails and you are told
to recover manually. Steam Deck / user testing is deferred until after `dev` is
pushed and the dev release is requested.

## Out of scope (do not change)

- `py_modules/sdh_ludusavi/rpc_pool.py` `DaemonThreadPool` — required; stdlib
  `ThreadPoolExecutor` joins workers at interpreter exit and is no longer daemon,
  so it cannot provide the no-join-on-unload guarantee. Leave it.
- `src/surfaces/autoSyncStatusBrowserView.ts` `setContext`/`sync` split — keep
  both. `setContext` is called standalone to update the visibility intent the
  deferred show-timeout reads; merging into one `render` would force reloads or
  drop that intent.
- `src/controllers/pluginUpdateController.tsx` state model — the
  reducer/snapshot rewrite is deferred; its refs are deliberate transient guards
  and the payoff is unproven. Not part of this plan.
