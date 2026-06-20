# Review — fix-update-check-feedback-loop (round 01)

Branch: `feat/fix-update-check-feedback-loop`
Commit reviewed: `9538bbd` (round-complete marker stamped at this SHA)
Reviewed against: `docs/plans/2026-06-19_fix-update-check-feedback-loop.md`

## Verdict

CHANGES_REQUESTED. The production fix is correct and accepted. The blocking issue is the
**regression test is not red-first** — it passes against the unpatched (buggy) controller,
so it guards nothing. Make the test genuinely fail on the pre-fix code, then keep it green.

## Gate status

All green at `9538bbd` (`./run.sh bash scripts/quality_gates.sh check`): ruff, ty, pytest,
`pnpm run verify` (vitest 228 passed across 28 files, tsc clean).

## Production fix — accepted

`src/controllers/pluginUpdateController.tsx`:
- Adds `const isHydrated = state.phase !== "hydrating";` and replaces `state.phase` with
  `isHydrated` in the dependency arrays (and the early-return guards) of **both** re-check
  effects (the `force:true` re-check effect and the `force:false` toggle effect).
- The `install` callback's `state.phase` dependency is correctly left untouched.

This is the right fix: `isHydrated` is monotonic (phase never returns to `hydrating` after
`HYDRATION_COMPLETE`), so it flips `false→true` exactly once. The effects therefore re-run
only on hydration-complete and on `updateChannel`/`currentVersion` changes — never on the
`checking ↔ available` oscillation that produced the loop. I verified the mechanism against
the reducer transitions; the production change resolves the on-device runaway.

## Required changes (blocking)

1. **Make the regression test actually fail on the buggy code (red-first).**
   `src/controllers/pluginUpdateController.test.tsx::"does not loop forced checks when update
   is available"` currently **passes even with the pre-fix controller**. I verified this:
   reverting only `pluginUpdateController.tsx` to its `dev` (pre-fix) version — restoring the
   `state.phase` dependency arrays — and running that test still reports **1 passed**. A
   regression test that is green on the bug it targets provides no protection.

   The `renderAndRunEffects` harness does not reproduce the runaway because of how the real
   controller behaves under it: `checkForUpdates` has an `inFlightCheck.current` dedup guard
   and dispatches across `await`/macrotask boundaries, while the harness re-runs effects by
   array index with reference-compared deps and only a single `setTimeout(0)` settle per
   iteration. The cascade that occurs in real React (a check result mutates `state.phase` →
   effect with `state.phase` dep re-runs → forces another check) never materialises, so the
   loop never triggers and the `loops < 50` / `checkCalls <= 2` assertions pass either way.

   Required: write the regression at a level that deterministically discriminates pre-fix
   from post-fix. A clean approach is to assert the **invariant directly** — *a check-result
   phase change must not change the re-check effect's dependencies*:
   - render the hook once in a hydrated, non-`hydrating` state and capture the dependency
     array of the `force:true` re-check effect;
   - dispatch / drive a `CHECK_SUCCESS_AVAILABLE` transition so `state.phase` goes
     `idle`/`checking` → `available`;
   - re-render and capture that effect's dependency array again;
   - assert the dependency array is unchanged (reference-equal element-wise).

   With the pre-fix code (`state.phase` in the deps) the arrays differ → test fails; with the
   fix (`isHydrated`, monotonic) they are identical → test passes. Alternatively, fix the
   harness so it faithfully models React re-render + effect-rerun-on-dep-change (awaiting the
   real in-flight check promise, not just a macrotask) and keep the call-count/loop-bound
   assertion — but only if you first confirm it fails on the reverted controller.

   **Verify red-first explicitly:** temporarily revert `pluginUpdateController.tsx` to its
   `dev` version, confirm the new test FAILS, then restore the fix and confirm it PASSES.
   Do not rely on a bound the buggy code already satisfies.

2. Keep the production fix as-is (no change needed) and keep all existing controller/reducer
   tests passing unweakened.

## How to proceed

Rework the regression test so it is demonstrably red on the pre-fix controller and green with
the fix, run the quality gates, ensure the tree is clean, commit, commit this review note,
then re-run `scripts/orchestration/mark-finished fix-update-check-feedback-loop`.

STATUS: CHANGES_REQUESTED
