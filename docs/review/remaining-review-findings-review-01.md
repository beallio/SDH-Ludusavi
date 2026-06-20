# Review — remaining-review-findings (round 01)

Branch: `feat/remaining-review-findings`
Commit reviewed: `8ddcbe0` (round-complete marker stamped at this SHA)
Reviewed against: `docs/plans/2026-06-19_remaining-review-findings.md`

## Verdict

CHANGES_REQUESTED. The round is **incomplete**: WU-5 (the QAM god-component
decomposition) was not implemented at all. The work that *was* committed (WU-1, WU-2, WU-3,
WU-4) is structurally sound and gate-green — keep it. This round is about finishing WU-5.
A secondary commit-hygiene issue (WU-1 + WU-2 bundled) is noted below as non-blocking
guidance — do not rewrite already-merged-quality history for it.

## Gate status

All green at `8ddcbe0` (`./run.sh bash scripts/quality_gates.sh check`):
- ruff check + format-check: pass
- ty: pass
- pytest: 637 passed, coverage 86.63% (≥83% required)
- frontend `pnpm run verify`: supply-chain clean, build OK, vitest 219 passed, tsc clean

## What is correct (no action needed)

- **WU-1 watcher race** — `start_watch` now re-checks `self.watches.get(watch_id) is watch`
  under the lock before `watch.start()`, and `SyncthingWatch.stop()` is safe on a
  never-started watch. New concurrency tests in `tests/test_watcher.py` cover the orphan
  case and the never-started `stop()`.
- **WU-2 updater split** — `updater.py` 928→607 lines; new `updater_rate_limit.py`,
  `updater_discovery.py`, `updater_pending.py` modules. The 403/429 cooldown duplication
  is gone: `parse_rate_limit_retry_after(...)` is the single shared parser used by both
  `check_for_update()` and `revalidate()`. Public RPC signatures/return shapes preserved.
- **WU-3 lifecycle** — `gameLifecycleDecision.ts` pure decision functions extracted;
  `gameLifecycleController.tsx` 560→executes returned effects. Table-driven tests added.
- **WU-4 update reducer** — `pluginUpdateReducer.ts` extracted; controller drives phase
  from the reducer. Reducer transition tests added.
- Out-of-scope items correctly untouched: `captureSteamUiGameContext, 500` interval still
  present in `LudusaviContent.tsx`; action refs still `@v6`/`@v7`/`@v3` tags (no SHA pin).

## Required changes

1. **Implement WU-5 — decompose the QAM god component (blocking; only required change).** This was entirely
   skipped: `src/components/qam/LudusaviContent.tsx` is still 854 lines and no new
   extraction hooks/modules were added. Per the plan, land it in the prescribed order:
   1. Extract the shared manual-operation finalize pipeline first (the duplicated
      refresh→status→logs→history→store sequence shared by `runForceOperation`,
      latest restore, and snapshot restore `runSnapshotRestore`). Add a unit test asserting
      backup + latest restore + snapshot restore all call the one finalize implementation.
   2. Extract focused hooks/controllers (initial-content load, Steam-context selection,
      game refresh) with **injected RPC dependencies**, testable without rendering the QAM.
      Reuse existing store methods; do not duplicate store logic.
   3. Reduce `LudusaviContent.tsx` to state selection + controller composition + section
      rendering. Leave the 500ms hidden-QAM polling effect as-is (out of scope).
   - Update `tests/test_module_size_budgets.py`: add budgets for the new QAM modules and
     **tighten `LudusaviContent.tsx`'s budget to its new (smaller) reality**. Preserve the
     exact user-visible operation flow (optimistic status, logs, history refresh, busy-label
     reset in `finally`). No behavior change.

## Non-blocking note (do NOT rewrite history)

Commit `7930790` ("fix(watcher): prevent orphan threads...") bundles the entire WU-2
updater split (updater.py + 3 new modules + their tests) into the watcher commit, where the
plan called for one commit per work unit and WU-2 in three ordered sub-commits. The content
is correct and gate-green, and this repo's `.git` is Dropbox-synced (history rewrites risk
transient object corruption), so **do not rebase/re-split the already-committed
WU-1/WU-2 history** — the cost outweighs the cosmetic benefit. Just keep WU-5's commits
atomic (its own sub-commits) going forward.

## How to proceed

After implementing WU-5: run the quality gates, ensure the tree is clean, commit the WU-5
work in its sub-commits, commit this review note, then re-run
`scripts/orchestration/mark-finished remaining-review-findings`.

STATUS: CHANGES_REQUESTED
