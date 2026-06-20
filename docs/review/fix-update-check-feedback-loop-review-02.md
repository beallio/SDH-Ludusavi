# Review — fix-update-check-feedback-loop (round 02)

Branch reviewed: `feat/fix-update-check-feedback-loop`
Commit reviewed: `22cef58` (round-complete marker stamped at this SHA)
Plan reviewed against: `docs/plans/2026-06-19_fix-update-check-feedback-loop.md`

## Verdict

APPROVED. The production fix is correct and the regression test is now genuinely red-first.
The round-01 finding is resolved. Cleared to finalize.

## Gate status

All green at `22cef58` (`./run.sh bash scripts/quality_gates.sh check`): ruff, ty, pytest,
`pnpm run verify` (vitest passing across 28 files, tsc clean).

## Red-first verification (performed by reviewer)

- Reverted **only** `src/controllers/pluginUpdateController.tsx` to its `dev` (pre-fix)
  version (restoring the `state.phase` dependency arrays) and ran the reworked test
  `"dependency arrays for re-check effects do not change on check result"` → **FAILS**
  (`expect(depsAfter).toEqual(depsBefore)` fails: `state.phase` flips `idle → available`
  between renders, so the effect dependency arrays differ).
- Restored the fix and ran the test → **PASSES** (`isHydrated` is monotonic, so the
  dependency arrays are identical across the `CHECK_SUCCESS_AVAILABLE` transition).
- Working tree restored and clean.

This is the correct, deterministic regression guard: it asserts the invariant "a check-result
phase change must not change the re-check effect's dependencies", which is exactly the
property that broke in the WU-4 regression.

## Resolution of prior findings

- **Round-01 (regression test not red-first):** resolved in `22cef58`. The previous
  loop-bound test (which passed against the buggy controller) was replaced with a direct
  dependency-array invariant test that is demonstrably red on the pre-fix code and green with
  the fix. The brittle `renderAndRunEffects` harness was removed.

## Production fix (unchanged from round 01, accepted)

`pluginUpdateController.tsx`: `const isHydrated = state.phase !== "hydrating"` replaces
`state.phase` in the dependency arrays and guards of both re-check effects; the `install`
callback's `state.phase` dependency is correctly untouched. This eliminates the on-device
runaway (2030 forced checks in ~47s when an update is available).

## Finalization instructions

1. Confirm all review notes are committed and the tree is clean.
2. Run `scripts/orchestration/finalize fix-update-check-feedback-loop`.
3. Confirm `/tmp/sdh_ludusavi/fix-update-check-feedback-loop_finalized` exists.
4. Stop polling and exit. Finalize merges `feat/fix-update-check-feedback-loop` into `dev`,
   cleans up the branch, pushes `dev`, and requests a dev release.

Deferred (on-device, after the dev push): install the resulting dev build with an update
genuinely available, open the QAM, and confirm the log shows a single
`check_start`/`check_success: status=available` per legitimate trigger — no repeated
`force=True` loop.

STATUS: APPROVED
