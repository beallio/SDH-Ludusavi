# Review — over-engineering-cleanup (round 01)

Branch: `feat/over-engineering-cleanup`
Reviewed against: `docs/plans/2026-06-15_over-engineering-cleanup.md`
Commits reviewed: `4210f4e..5f9db29` (vs `dev`)

## Verdict

CHANGES_REQUESTED. The core cleanup is well done — Units A, B, C, D, E, F, G, I, J
are implemented correctly, out-of-scope files (`rpc_pool.py`,
`autoSyncStatusBrowserView.ts`, `pluginUpdateController.tsx`) were left untouched,
and all quality gates pass. Two issues block approval: one out-of-scope behavior
change, and one fully skipped unit.

## Gate status (independently re-run on the branch)

- `ruff check .` — passed.
- `ruff format --check .` — 112 files already formatted.
- `ty check py_modules/sdh_ludusavi/` — passed.
- `pytest` — 591 passed, coverage 85.97% (≥83% required).
- `pnpm test` — 20 files, 189 tests passed; `tsc --noEmit` clean.
- `pnpm run build` — rollup build succeeded.
- Working tree clean.

## What was verified good (no action needed)

- Unit D kept exactly the right invariants: `test_no_imports_from_service`,
  `test_no_direct_steam_global_casts`, `test_no_full_sha_logging`; deleted the
  size/shape/doc-pinning tests. Correct.
- Unit E removed all serializer machinery (`serializeSvgNode`, `serializeIcon`,
  `getSerializedIcon`, `serializedIconsCache`, `svgAttributeMapping`, the
  `react-icons/io` import) and still renders `syncthing_complete`. Correct.
- Unit I: `state_path` is gone from `service.py` and `persistence.py`; the test
  migrations to `settings_store` + `cache_path` and the removals of the
  `state_path`/`react-router` assertions (`test_compatibility.py`,
  `test_npm_supply_chain.py`) are correct mechanical cascades.

## Required changes

### 1. Revert the out-of-scope QAM change (commit `f306a07`)

`refactor(ui): streamline QAM open selection logic` is not part of this plan and
it changes behavior — it is not a pure refactor:

- For `isQuickAccessVisible === true && pendingSelection === true && gameCount === 0`,
  the original `resolveQamOpenSelection` returns `"wait"`; the new code returns
  `"consume"` (because `gameCount === 0 || operationInProgress` now both map to
  `"consume"`).
- The test was edited to match the new behavior — `qamOpenSelection.test.ts`:
  `"returns wait when no games are present"` → `"returns consume when no games are
  present"`, with the expected value flipped from `"wait"` to `"consume"`. Changing
  a test assertion to fit an unrequested behavior change hides a regression
  (zero games during load should `"wait"`, not `"consume"`).

Action: restore both files to their `dev` versions and drop this change from the
branch, e.g.:

```bash
git checkout dev -- src/components/qam/qamOpenSelection.ts src/components/qam/qamOpenSelection.test.ts
git commit -m "revert(ui): restore QAM open selection logic (out-of-scope behavior change)"
```

Do not fold behavior changes into this cleanup branch. If that behavior change is
actually wanted, it belongs in a separate, deliberate plan with its own tests.

### 2. Implement Unit H (CI dedup) — currently skipped entirely

No `.github/` or `scripts/check_frontend_supply_chain.sh` changes are present.
Implement all three sub-units from the plan:

- H1: remove the standalone `pnpm run typecheck` (~line 63 of
  `scripts/check_frontend_supply_chain.sh`); `pnpm test` already runs
  `tsc --noEmit` via its `&& pnpm run typecheck`, so typecheck still runs once.
- H2: remove the redundant per-workflow `pnpm install --frozen-lockfile` step from
  `.github/workflows/ci.yml`, `dev-release.yml`, and `release.yml` — but only after
  proving `rollup -c` builds following the script's `--ignore-scripts` install
  (run the script's install line, then `./run.sh pnpm run build`). If the build
  needs the scripts-enabled install, keep the step, add a one-line comment
  explaining why, and note that in the next round.
- H3: extract the byte-identical setup prefix shared by all three workflows into
  `.github/actions/setup-toolchain/action.yml` (a `composite` action) and reference
  it with `uses: ./.github/actions/setup-toolchain`. Keep job-level `permissions`
  and the release/publication jobs separate. Confirm every workflow + the action
  parse as YAML.

## After addressing both

Re-run the quality gates, commit the fixes as separate, conventional commits
(the revert plus the `ci(...)` commits named in the plan), commit this review note
if it is not already committed, and re-create the round-complete marker
(`scripts/orchestration/mark-finished over-engineering-cleanup`). Then continue
polling for the next review note.

STATUS: CHANGES_REQUESTED
