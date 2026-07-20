# Review — explicit-selection-beats-autoselect (round 01)

Branch: `feat/explicit-selection-beats-autoselect`
Reviewed against: `docs/plans/2026-07-20_explicit-selection-beats-autoselect.md`
Reviewed commit: `a477f45`

## Verdict

Tasks 1, 2, 3, 4 and 5 are implemented as specified, and the logic is correct as
written: with an explicit selection pending, the arm is consumed and the running
game is not selected. One required change below hardens how the signal reaches
the effect; it is a robustness fix, not a behavior change.

## Gate status

Quality gates re-run independently by the orchestrator on the branch head:
passed (839 Python tests at 88.69% coverage, frontend suite, typecheck, build,
supply-chain). Working tree clean; no review notes deleted.

Plan targeted checks all pass:

1. `explicitSelectionPending` appears only in `qamOpenSelection.ts`,
   `useSteamContext.ts`, and `LudusaviContent.tsx`.
2. Both refresh-path `selectCurrentSteamGameIfAvailable` call sites
   (`LudusaviContent.tsx:257`, `:303`) are unchanged, as Task 4 required.
3. No `py_modules/` file changed.
4. `GameSettingsSection.tsx` is not in the diff.

The new decision-function tests cover all four required cases, and the
`useSteamContext` test exercises the real `resolveQamOpenSelection` rather than a
stub, so it covers the integration between the hook and the pure function.

## Required changes

### 1. Do not feed a ref snapshot into an effect dependency array

`LudusaviContent.tsx:163` passes `explicitSelectionPending:
explicitSelectionRef.current` — a render-time read of a ref — and
`useSteamContext.ts:118` lists that value in the effect's dependency array. Refs
are not reactive: React cannot re-run the effect when `.current` changes, so the
dependency entry is inert and the effect body can observe a stale boolean.

This is correct **today**, but only because of two incidental properties:

- `useQuickAccessVisible()` (`LudusaviContent.tsx:84`) is a `@decky/api` hook, so
  every QAM visibility transition re-renders the component and refreshes the
  snapshot immediately before the arm happens;
- `setDisplayedGame` and `onExplicitSelectionConsumed` are inline arrows with a
  fresh identity on every render, so the effect re-runs every render regardless
  of the dependency array.

Both are accidents of the current code, not guarantees. Wrapping either callback
in `useCallback` — an ordinary, apparently safe optimization — would stop the
per-render re-run and leave the effect reading a stale value. The failure is
silent in both directions: either the bug this plan fixes returns, or a genuine
QAM reopen has its auto-selection suppressed. Neither surfaces in a test or a
log.

Change the signal from a captured value to a getter read at effect time:

- In `UseSteamContextOptions`, replace
  `explicitSelectionPending: boolean` with
  `isExplicitSelectionPending: () => boolean`.
- Inside the second effect, read it once at the top:
  `const explicitSelectionPending = isExplicitSelectionPending();`
  and pass that local into `resolveQamOpenSelection` and the consume branch.
- Remove `explicitSelectionPending` from the dependency array. Keep
  `isExplicitSelectionPending` and `onExplicitSelectionConsumed` there. The
  effect still re-runs on `isQuickAccessVisible` changes, which is exactly when
  the flag must be evaluated.
- In `LudusaviContent.tsx`, pass
  `isExplicitSelectionPending: () => explicitSelectionRef.current`.

Do **not** change `resolveQamOpenSelection`. Its `explicitSelectionPending:
boolean` input is correct and its tests must remain as they are — the point of
this change is that the boolean is computed at effect time rather than captured
at render time.

Update `useSteamContext.test.ts` to pass the getter. Add one case proving the
value is read at effect time rather than at call time: pass a getter returning
`true` and assert `setDisplayedGame` is not called and the consumed callback
fires; then a getter returning `false` and assert the running game *is* selected.

### 2. Restore the removed blank line

`useSteamContext.ts` lost the blank line between the import block and
`selectCurrentSteamGameIfAvailable`. It is unrelated to this change; restore it.

## Not required — do not do

Do not add a timeout, debounce, or elapsed-time heuristic for the false
close/open transition. Do not touch the refresh-path call sites. Do not attempt
to make the one-shot flag survive multiple arms — the known limitation recorded
in the plan and session log is accepted.

STATUS: CHANGES_REQUESTED
