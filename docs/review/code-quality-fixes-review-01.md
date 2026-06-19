# Review — code-quality-fixes (round 01)

Branch: `feat/code-quality-fixes`
Reviewed against: `docs/plans/2026-06-18_code-quality-fixes.md`
Commit reviewed: `c40487b`

## Verdict

Strong round. All 7 scoped items are implemented correctly and the full quality gates
pass (621 pytest @ 85.9% coverage; pnpm vitest 202 + tsc typecheck + rollup build all
green). One small correctness nit in a restored guard test must be fixed before approval,
plus two trivial cleanups. None of the medium items regressed the restored guards.

## Gate status

- `scripts/orchestration/run-quality-gates`: PASS (verified by reviewer on `c40487b`).
- Restored guard tests run and pass.

## What's correct (no action needed)

- **Blocker 1** — `test_architecture.py` faithfully restored (diff vs `main` is *only* the
  class-size threshold; assertions not weakened). `test_module_size_budgets.py` and
  `test_status_flow_diagram.py` restored.
- **Blocker 2** — `_warn_load` no longer logs the cache path (drops the path; `reason`
  carries context). Test added.
- `_atomic_json_write` extracted and used by both `JsonSettingsStore.write()` and
  `PersistenceManager.save_cache()`; write semantics preserved.
- Dead `service: Any` removed from `coordinator.py` + `log_buffer.py` (+ unused import) and
  both `service.py` call sites updated.
- `isMounted`/`setBusyLabel`/`MountedRef` removed; `SILENT_SKIPPED_REASONS` hoisted;
  syncthing predicates consolidated into the renderer (`isSyncthingStatus` /
  `isSyncthingActiveStatus`) with the surface duplicate removed.
- Session log recorded.

## Required changes

1. **Fix the misleading docstring in `tests/test_architecture.py`
   `test_service_facade_class_size`.** It reads `"""SDHLudusaviService class span must be
   under 400 lines."""` but the assertion is `span < 580`. A guard test whose docstring
   contradicts its threshold undermines the guard. Update the docstring to state the actual
   budget (`< 580`) and briefly note it is "current size + buffer" so a future reader knows
   why.

2. **Remove the leftover double blank lines** introduced by the deletions, so the style
   stays clean:
   - `src/settings/settingsMutationRuntime.ts` — blank line left where `MountedRef`/the
     dead options were removed (top of file and inside the options type).
   - `src/surfaces/autoSyncStatusSurface.tsx` — blank line left where the private
     `isSyncthingStatus` was removed.

## Non-blocking observations (optional; do not redo history)

- The 580-line class budget and a few module budgets (e.g. `gameLifecycleController.tsx`
  645 vs current 560) sit near the upper end of "modest buffer." Acceptable per the plan;
  tightening later is fine.
- Commit hygiene: several items were bundled under commit messages that don't fully
  describe their contents (e.g. `7edacc7` "remove misleading cache path log" also contains
  `_atomic_json_write`; items 9-11 aren't individually titled). Not worth rewriting history
  now — just aim for one-item-per-commit next round.

STATUS: CHANGES_REQUESTED
