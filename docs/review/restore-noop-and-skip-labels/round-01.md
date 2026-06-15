# Review Round 1 — restore-noop-and-skip-labels

**Branch:** `fix/restore-noop-and-skip-labels`
**Commits reviewed:** `4255be1` (fix(qam): report point-in-time restore no-op as skipped) · `2e84f90` (fix(ui): make Last Operation skip text operation-aware)
**Reviewer gates run:** `pnpm run test:unit` ✅ (177 passed) · `pnpm run typecheck` ✅ · `ruff check` ✅ · `ty check` ✅ · `pytest -k restore_backup_version` ✅ (3 passed)

## Verdict: CHANGES REQUESTED

The **code, tests, and gates are all correct and complete** — see "What's correct" below. Two
**working-tree hygiene** problems must be fixed before approval, because they would otherwise be
swept into `dev` during finalization. Both are quick.

---

## What's correct (no action needed)

- **Backend** (`py_modules/sdh_ludusavi/lifecycle.py`, `restore_backup_version`): matches plan §5A
  exactly — `change = self._result_change(result, game.name)` inside the `try`; `change == "Same"`
  records `skipped`/`local_current`, else `restored`; `except OperationLockedError: raise` and the
  broad `except` are preserved; `refresh_after_operation` runs on both paths; the skip path logs
  *"Restore skipped for {game} from backup {id}: local save already matches backup"* and returns
  `{"status":"skipped","reason":"local_current","game":…,"backup_id":…,"result":…}`. `ty`/`ruff`
  are clean without a pre-init of `change` (consistent with `force_restore`).
- **Frontend** (`src/formatting/operationText.ts`): operation-aware `getLastOperationText` with the
  4th optional `operation` param; `case "failed"` and `case "skipped"` are now block-scoped
  (correctly fixing the lexical-declaration-in-switch hazard); label mapping
  (backup/exit→"Backup skipped", restore/start→"Restore skipped", else "Skipped"); `local_current`
  detail is restore-aware. All acceptance strings from plan §5B are produced.
- **Call site** (`src/components/qam/GameSettingsSection.tsx`): passes `selectedHistory.operation`.
- **Tests:** 3 backend tests (`test_restore_backup_version_no_changes_records_skip`,
  `…_different_records_restored`, `…_missing_change_defaults_restored`) and the new
  `src/formatting/operationText.test.ts` are present, match the plan, and pass.
- **Scope respected:** `force_backup`, `force_restore`, `runSnapshotRestore`, and
  `summarizeOperationResult` were left untouched, as intended.

---

## Required fixes

### 1. Revert the uncommitted `uv.lock` change
`git status --short` shows `uv.lock` modified. The diff flips the dependency policy:

```
[options.exclude-newer-package]
- pyludusavi = "2026-06-14T00:00:00Z"
+ pyludusavi = false
```

This is an unintended lockfile/dependency-policy change (not part of this task) and must not reach
`dev`. Fix it:

```
git checkout -- uv.lock
git status --short        # must NOT list uv.lock anymore
```

For any further `uv` commands this round, prefix them with `UV_FROZEN=1` (plan §2 gotcha) so the
lockfile is not regenerated again.

### 2. Commit the plan doc (currently untracked)
`docs/plans/restore-noop-and-skip-labels.md` is untracked. Plan §8 lists it as part of the change
set, and the branch should be self-contained. Commit it on the branch:

```
git add docs/plans/restore-noop-and-skip-labels.md
git commit -m "docs(plans): add restore no-op and skip labels plan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## After addressing
1. Re-run the full quality gates (plan §7) and confirm they pass.
2. Confirm `git status --short` is clean (no stray `uv.lock`, no repo caches).
3. `touch /tmp/sdh_ludusavi/restore-noop-and-skip-labels_finished` to signal the next review pass.
4. Do **not** create `APPROVED` or write review notes yourself — that is the reviewer's job.
