# Plan: Address thermo-nuclear code quality review (code-quality-fixes)

## Context

A thermo-nuclear code-quality review of `dev` vs `main` gave a conditional approval with
two blockers plus several "should fix" cleanups. This plan addresses the **two blockers and
the five medium-priority cleanups**. The three "Future PR" items are explicitly **out of
scope** (see below).

This plan is self-contained — every item below has the exact file/line references you need.
The full source review is available (optional reading) at
`/tmp/orch-trial-stash/2026-06-18_thermo-nuclear-code-quality-review.md`.

This is the first dogfood run of the extracted orchestrator, on a local-only trial branch
(`orchestrator-trial`); finalize stays local (no push, no release).

**Out of scope (do NOT do these):**
- Table-driven rewrite of `settingsMutationRuntime.ts` (`MUTATION_TABLE`) — future PR.
- Typing `MutateOptions.settingValue`/etc. as `V` instead of `any` — future PR.
- Pre-existing `BaseException` catch in `main.py` — future PR.

**Slug used throughout this plan:** `code-quality-fixes`

---

## Orchestration Contract

**Slug:** `code-quality-fixes`

**Plan file:**

```text
docs/plans/2026-06-18_code-quality-fixes.md
```

**Implementation branch:**

```text
feat/code-quality-fixes
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/code-quality-fixes_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/code-quality-fixes_finalized
```

**Review notes:**

```text
docs/review/code-quality-fixes-review-*.md
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
3. Branch from `orchestrator-trial`.
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

## Setup

Start from `orchestrator-trial`:

```bash
git checkout orchestrator-trial
# ORCH_LOCAL_ONLY: local trial branch, skipping origin pull
git checkout -b feat/code-quality-fixes
```

Commit this plan first:

```bash
git add docs/plans/2026-06-18_code-quality-fixes.md
git commit -m "docs(plan): add code-quality-fixes implementation plan"
```

---

## Implementation Tasks

Work in small, atomic commits — ideally one commit per numbered item. Follow TDD where a
test is the deliverable or where behavior changes (items 1, 2, 3, 5). Run the quality gates
before marking the round complete.

### 🔴 Blocker 1 — Restore architectural guard tests

The branch deleted/gutted architecture guard tests. Restore the enforcement with thresholds
updated to current reality + a modest buffer (do not just re-add stale numbers, and do not
weaken intent).

1. Recover the deleted content from `main` for reference:
   - `git show main:tests/test_architecture.py`
   - `git show main:tests/test_module_size_budgets.py`
   - `git show main:tests/test_status_flow_diagram.py`
2. **`tests/test_architecture.py`** — restore the assertions that were dropped (it went 126→33
   lines): `SDHLudusaviService` class span budget; decomposed modules cannot import from
   `service.py`; gateway cannot reference `self._service`; no `service: Any` in updater
   modules; no raw updater state fields on the service; no duplicate `sanitize_game_name`
   definitions. Update any literal size/threshold to the **current** measured value + ~10-15%
   headroom so it passes today but still catches drift.
3. **`tests/test_module_size_budgets.py`** — restore it with per-file LOC budgets for the
   complexity-prone frontend modules (e.g. `autoSyncStatusSurface.tsx`,
   `gameLifecycleController.tsx`, `LudusaviContent.tsx`, `settingsMutationRuntime.ts`,
   `syncthingMonitor.ts`). Set each budget to current lines + modest buffer.
4. **`tests/test_status_flow_diagram.py`** — only restore if the HTML flow diagram it
   guarded still exists in the tree; if the diagram was intentionally removed, leave this
   deleted and note that in the round summary. Do not invent a new guard for a file that no
   longer exists.
5. After restoring, items 4–8 below must keep these guard tests green (e.g. removing
   `service: Any` satisfies the updater-module assertion).

### 🔴 Blocker 2 — Fix `_warn_load` wrong path (persistence.py)

6. `py_modules/sdh_ludusavi/persistence.py` `_warn_load` always logs `self._cache_path`, even
   when called from the settings read path — misleading for settings errors. Fix it so the
   message reflects the actual source (pass a `source`/path argument from each call site, or
   drop the path from the message since `reason` already carries context). Add/adjust a unit
   test asserting a settings-read failure does **not** log the cache path.

### 🟡 Medium-priority cleanups

7. **Extract `_atomic_json_write(path, data)`** in `persistence.py` and call it from both
   `JsonSettingsStore.write()` and `PersistenceManager.save_cache()` (identical
   temp-file + `os.replace` + cleanup pattern). Preserve exact write semantics
   (`json.dumps(..., indent=2, sort_keys=True)`, encoding, temp-name scheme, except-cleanup).
8. **Remove dead options** from `SettingsMutationControllerOptions` in
   `src/settings/settingsMutationRuntime.ts`: `isMounted` and `setBusyLabel` are accepted but
   never used. Remove both from the type and any now-unused plumbing. Update tests that
   referenced them.
9. **Remove dead `service: Any`** constructor params + stored attributes from
   `py_modules/sdh_ludusavi/coordinator.py` and `py_modules/sdh_ludusavi/log_buffer.py`
   (stored but never used). Update call sites and tests.
10. **Consolidate syncthing status predicates**: the surface
    (`src/surfaces/autoSyncStatusSurface.tsx`) has a private `isSyncthingStatus()` (4 statuses,
    incl. `syncthing_complete`) while the renderer
    (`src/surfaces/autoSyncStatusRenderer.tsx`) exports `isSyncthingActiveStatus()` (3
    statuses). Consolidate into the renderer/shared util with clear names:
    `isSyncthingActiveStatus` (3) and `isSyncthingStatus` (4). Remove the surface's private
    duplicate and import both. Keep current behavior at each call site (mind which set each
    used).
11. **Extract `silentReasons` constant** in `src/controllers/gameLifecycleController.tsx`:
    the identical array is defined twice (~L255 and ~L420). Hoist to one module-level
    constant and reference it in both places.

Each item must keep the full suite green and not regress the restored guard tests.

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

1. `scripts/orchestration/run-quality-gates` passes (pnpm test/build + ruff/ty/pytest).
2. The restored guard tests (`test_architecture.py`, `test_module_size_budgets.py`) run and
   pass, and actually fail if a budget is exceeded (spot-check by temporarily bloating a file
   locally, confirm red, revert — do not commit the bloat).
3. `_warn_load` settings-path test passes; grep confirms no remaining call logs the cache
   path for a settings error.
4. No remaining `service: Any` in `coordinator.py`/`log_buffer.py`; no `isMounted`/
   `setBusyLabel` in `SettingsMutationControllerOptions`; `silentReasons` defined once; one
   canonical pair of syncthing status predicates.
5. `git grep` shows no duplicate atomic-write blocks (single `_atomic_json_write`).

Deferred: on-device Steam Deck testing is **not** part of this trial (local-only run; no dev
push, no release).

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished code-quality-fixes
```

This writes:

```text
/tmp/sdh_ludusavi/code-quality-fixes_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer code-quality-fixes`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/code-quality-fixes-review-*.md
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
   scripts/orchestration/clear-finished code-quality-fixes
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
   git add docs/review/code-quality-fixes-review-*.md
   git commit -m "docs(review): record code-quality-fixes review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished code-quality-fixes
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer code-quality-fixes` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed code-quality-fixes
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize code-quality-fixes
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/code-quality-fixes_finalized
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
scripts/orchestration/finalize code-quality-fixes
```

Do not manually merge into `orchestrator-trial` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/code-quality-fixes_finished
/tmp/sdh_ludusavi/code-quality-fixes_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
