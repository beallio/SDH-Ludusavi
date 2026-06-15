STATUS: APPROVED

# Review — Lock Selected Game During Operations (Round 1 — APPROVED)

Branch: `fix/qam-selection-lock-during-operation`
Reviewed commits: `27f9c1c`, `95174cc`

## Outcome

The implementation matches the plan exactly. Approved on the first pass.

## Verified

- **Helper:** `src/components/qam/qamOpenSelection.ts` implements `resolveQamOpenSelection` as specified (`wait` / `consume` / `select`).
- **Tests:** `src/components/qam/qamOpenSelection.test.ts` covers all five cases, including the `operationInProgress → "consume"` branch that is the fix.
- **Wiring (`LudusaviContent.tsx`):**
  - `operationInProgress` ref added beside the existing refs.
  - The deferred selection effect now routes through `resolveQamOpenSelection` and, on `"consume"`, clears `pendingCurrentGameSelection` without route-selecting (prevents both the mid-op flip and a post-op re-fire); dependency array unchanged.
  - `runForceOperation` and `runSnapshotRestore` set `operationInProgress.current = true` immediately after the `!selectedGame` early-return (before `setBusyLabel`) and clear it unconditionally in `finally` (outside the `isMounted` guard).
  - `selectCurrentSteamGameIfAvailable`, `applyRefreshResult`/`applyCachedRefreshResult`, `resolveRefreshedSelection`, the `qam_opened` effect, the context-capture interval, and the end-of-op `applyRefreshResult(refreshed, selectedGame)` calls are untouched.
- **Session log:** snake_case keys, matching `docs/agent_conversations/` convention.
- **Quality gate (re-run, all green):** ruff check, ruff format --check, ty, pytest (612 passed, 85.91% coverage), `pnpm run test` (186 passed, +5 new, + tsc), `pnpm run build`.
- Only the four expected files changed; no caches or stray files.

## Integration steps

1. Commit the still-untracked docs in the project dir (both created during planning/review):
   - `docs/plans/2026-06-14_lock_selected_game_during_operation.md` → `docs(plans): add selected-game lock during operations plan`
   - `docs/review/2026-06-14_lock_selected_game_during_operation_review.md` → `docs(review): record review notes for selected-game lock during operations`
2. Run the full quality gate once more (all green).
3. Merge `fix/qam-selection-lock-during-operation` into `dev` and delete the working branch.
4. Push `dev` to GitHub.
5. Dispatch a dev release from `dev` HEAD: `./scripts/request_dev_release.sh 0.3.0`.

On-device (Steam Deck) verification — open the Backup Browser for a game while hovering a different library game, click Restore, and confirm the QAM keeps showing the restored game (greyed is fine) throughout — is deferred until after the dev release is pushed. Do not publish stable releases, push tags, or run any other release path.
