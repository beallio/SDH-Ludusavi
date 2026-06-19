# Review — over-engineering-cleanup (round 02)

Branch: `feat/over-engineering-cleanup`
Reviewed against: `docs/plans/2026-06-15_over-engineering-cleanup.md`
Commit reviewed: `daac07f` (tip after round-02 fixes)

## Verdict

APPROVED. Both round-01 findings are resolved, every planned unit is implemented,
out-of-scope files remain untouched, and all quality gates pass.

## Round-01 findings — resolved

1. Out-of-scope QAM behavior change — RESOLVED. `f3705d4 revert(ui): restore QAM
   open selection logic` restores `src/components/qam/qamOpenSelection.ts` and
   `qamOpenSelection.test.ts` byte-for-byte to `dev`; both now diff-clean against
   `dev`. The zero-games case returns `"wait"` again.
2. Unit H (CI dedup) — RESOLVED, all three sub-units:
   - H1 `cfc4bab` removed the duplicate `pnpm run typecheck` from
     `scripts/check_frontend_supply_chain.sh` (typecheck still runs via `pnpm test`).
   - H2 `d3f4a99` removed the per-workflow `pnpm install` from `ci.yml`,
     `dev-release.yml`, `release.yml`. Independently verified the CI scenario:
     `pnpm install --frozen-lockfile --ignore-scripts` followed by `pnpm run build`
     succeeds, so the scripts-disabled install does not break the build.
   - H3 `daac07f` extracted the byte-identical setup prefix into
     `.github/actions/setup-toolchain/action.yml` (composite). All three workflows
     reference `./.github/actions/setup-toolchain`; the gate steps (uv sync, ruff,
     ruff-format, ty, pytest, verify) and the package/validate/upload jobs remain
     in place. All workflows and the action parse as valid YAML.

## Scope and safety

- Out-of-scope files untouched: `py_modules/sdh_ludusavi/rpc_pool.py`,
  `src/surfaces/autoSyncStatusBrowserView.ts`,
  `src/controllers/pluginUpdateController.tsx`.
- Units A–G, I, J verified in round 01 (dead-code removal, test-only seams,
  `UpdaterCacheModel` removal, shape-test deletion keeping the layering/security
  invariants, static cloud-complete SVG, content-load coordinator simplification,
  react-router removal, combined `state_path` removal with mechanical test
  migrations, settings-mutator unification). No regressions introduced in round 02.

## Gate status (independently re-run on `daac07f`)

- `ruff check .` — passed.
- `ruff format --check .` — 112 files already formatted.
- `ty check py_modules/sdh_ludusavi/` — passed.
- `pytest` — 591 passed, coverage 85.97% (≥83% required).
- `pnpm test` — 20 files, 189 tests passed; `tsc --noEmit` clean.
- `pnpm run build` — rollup build succeeded.
- `pnpm install --frozen-lockfile --ignore-scripts` + `pnpm run build` — succeeded
  (H2 CI-path check).
- Working tree clean; review notes intact (round 01 + round 02 committed).

## Finalization instructions

Proceed to finalize:

```bash
scripts/orchestration/check-review-notes-committed over-engineering-cleanup
git status --short
scripts/orchestration/finalize over-engineering-cleanup
```

Confirm `/tmp/sdh_ludusavi/over-engineering-cleanup_finalized` exists, then stop
polling and exit cleanly. Steam Deck / user testing is deferred until after `dev`
is pushed and the dev release is requested.

STATUS: APPROVED
