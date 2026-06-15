# Lock Selected Game to the Acted-On Game During Operations

Slug: `2026-06-14_lock_selected_game_during_operation`
Branch: `fix/qam-selection-lock-during-operation` (branch off `dev`)
Execution skill: `implementer`

## Context

A prior fix (already merged to `dev`: `fix(qam): keep the acted-on game selected after backup/restore`) made the **end-state** selection correct after a backup/restore. This plan fixes a remaining **in-progress display** defect:

When the user opens the Backup Browser for a game and clicks Restore while a *different* game is hovered/selected in the Steam library, the QAM transiently shows the **library** game name (greyed out, because the panel is disabled while busy) for the duration of the restore. When the restore finishes, the name corrects to the game that was actually restored.

Desired: the QAM shows the **acted-on** game name for the entire operation (it may remain greyed/disabled while busy — that part is fine), with no transient flip to the library game.

## Problem Definition

Restore from the Backup Browser flows like this:
- `GameSettingsSection` "Browse Backups" opens `BackupBrowserModal` with `gameName={selectedGame}` and `onRestoreSnapshot={runSnapshotRestore}` (`src/components/qam/LudusaviContent.tsx:810`–`820`).
- Clicking Restore → `ConfirmModal` → `onOK` runs `closeModal()` then `onRestoreSnapshot(backupId, whenLabel)` (`src/components/modals/BackupBrowserModal.tsx:68`–`80`).
- `runSnapshotRestore` (`LudusaviContent.tsx:710`) restores `selectedGame` and, at the end, calls `applyRefreshResult(refreshed, selectedGame)` which restores the correct selection.

The transient flip happens because closing the modal re-opens the QAM. `useQuickAccessVisible()` goes `false → true`, so the `qam_opened` effect (`:209`–`233`) sets `pendingCurrentGameSelection.current = true`, and the **deferred selection effect** (`:235`–`242`) then runs `selectCurrentSteamGameIfAvailable(games, gameAliases)` — which reads the live Steam route/hover and sets `selectedGame` to the **library** game *while the restore is in progress*. The dropdown (`GameSettingsSection.tsx:54`–`67`, `selectedOption={selectedGame}`, `disabled={isBusy}`) then shows the library game, greyed. The end-of-restore `applyRefreshResult(refreshed, selectedGame)` later restores the acted-on game.

The displayed name is greyed because `disabled={isBusy}` and `isBusy` is true during the op — that styling is correct and must stay. Only the *value* is wrong mid-op.

## Fix

Suppress the deferred QAM-open route-selection while an operation is in progress, using a ref set synchronously at operation start. A ref (not React state) is required: the modal-close re-render and its effects run after the synchronous `onOK` handler, so a ref set inside `runSnapshotRestore` is already `true` when the deferred effect runs, regardless of React batching.

Two parts:

1. **New pure helper** `src/components/qam/qamOpenSelection.ts` that decides what the deferred effect should do (mirrors the existing `src/components/qam/refreshSelection.ts` pattern):
   ```ts
   export type QamOpenSelectionAction = "wait" | "consume" | "select";

   export interface QamOpenSelectionInput {
     isQuickAccessVisible: boolean;
     pendingSelection: boolean;
     gameCount: number;
     operationInProgress: boolean;
   }

   export function resolveQamOpenSelection(
     input: QamOpenSelectionInput,
   ): QamOpenSelectionAction {
     if (!input.isQuickAccessVisible || !input.pendingSelection || input.gameCount === 0) {
       return "wait";
     }
     if (input.operationInProgress) {
       return "consume";
     }
     return "select";
   }
   ```
   - `"wait"` = do nothing, keep the pending flag.
   - `"consume"` = clear the pending flag but do **not** route-select (this is the fix: an operation is running).
   - `"select"` = route-select and clear the pending flag (unchanged behavior).

   `"consume"` (rather than just skipping) is essential: after the op, `applyRefreshResult` mutates `games`, which re-runs the deferred effect; if the pending flag were still set it would route-select *after* the op and reintroduce the flip. Consuming it prevents that.

2. **Wire it into `LudusaviContent.tsx`:**
   - Add a ref next to the existing refs (after `:89` `const isMounted = useRef(true);`):
     ```ts
     const operationInProgress = useRef(false);
     ```
   - Replace the deferred selection effect body (`:235`–`242`) with:
     ```ts
     useEffect(() => {
       const action = resolveQamOpenSelection({
         isQuickAccessVisible,
         pendingSelection: pendingCurrentGameSelection.current,
         gameCount: games.length,
         operationInProgress: operationInProgress.current,
       });
       if (action === "wait") {
         return;
       }
       if (action === "consume") {
         pendingCurrentGameSelection.current = false;
         return;
       }
       selectCurrentSteamGameIfAvailable(games, gameAliases);
       pendingCurrentGameSelection.current = false;
     }, [gameAliases, games, isQuickAccessVisible]);
     ```
     (Keep the same dependency array — `operationInProgress` is a ref and must not be a dependency.)
   - Import the helper alongside the existing `refreshSelection` import (`:54`):
     ```ts
     import { resolveQamOpenSelection } from "./qamOpenSelection";
     ```
   - In `runForceOperation`: set the ref `true` immediately after the `if (!selectedGame) { ... return; }` guard and before `setBusyLabel(...)` (`:635`→`:638`), and clear it in the `finally` (`:703`–`:707`) **unconditionally** (not inside the `if (isMounted.current)` guard):
     ```ts
     operationInProgress.current = true;   // after the early-return guard, before setBusyLabel
     ...
     } finally {
       operationInProgress.current = false;
       if (isMounted.current) {
         setBusyLabel(null);
       }
     }
     ```
   - In `runSnapshotRestore`: identically — set `operationInProgress.current = true` after `if (!selectedGame) return;` (`:711`) before `setBusyLabel` (`:715`), and clear it unconditionally in the `finally` (`:782`–`:786`).

Do **not** modify `selectCurrentSteamGameIfAvailable`, `applyRefreshResult`/`applyCachedRefreshResult`, `resolveRefreshedSelection`, the `qam_opened` effect, the context-capture interval (`:244`–`252`), or the end-of-operation `applyRefreshResult(refreshed, selectedGame)` calls (the prior fix). This change is additive.

## Dependency Requirements

None. Reuses existing `selectCurrentSteamGameIfAvailable`, `pendingCurrentGameSelection`, and the `runForceOperation`/`runSnapshotRestore` handlers.

## Implementation Steps (strict TDD — RED before GREEN)

1. Branch `fix/qam-selection-lock-during-operation` off `dev`.

2. **Test (RED).** Add `src/components/qam/qamOpenSelection.test.ts` covering `resolveQamOpenSelection`:
   - `isQuickAccessVisible: false` → `"wait"`.
   - visible, `pendingSelection: false` → `"wait"`.
   - visible, pending, `gameCount: 0` → `"wait"`.
   - visible, pending, `gameCount > 0`, `operationInProgress: true` → `"consume"` (the fix).
   - visible, pending, `gameCount > 0`, `operationInProgress: false` → `"select"`.
   Run `pnpm run test:unit`; confirm RED (module missing).

3. **GREEN.** Create `src/components/qam/qamOpenSelection.ts` (code above). Re-run; confirm green.

4. **Wiring.** Apply the `LudusaviContent.tsx` changes (ref, effect, import, two handlers) per "Fix".

5. Run the full quality gate (see Validation); fix any issue at root cause.

6. Commit:
   - `fix(qam): keep the acted-on game shown while a backup/restore runs`

7. Write the session log `docs/agent_conversations/2026-06-14_lock_selected_game_during_operation.json` (date, task_objective, files_modified, tests_added, design_decisions, results — snake_case keys, matching the other files in that directory) and commit as `docs(session): record selected-game lock during operations`.

## Testing Strategy

- Frontend unit: `src/components/qam/qamOpenSelection.test.ts` covers the decision, including the `operationInProgress → "consume"` branch that is the fix.
- The effect/ref wiring is verified on-device after the dev release (see Validation).

## Validation

Run from the repo root; all must be green:
```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run test
pnpm run typecheck
pnpm run build
```
Use `./run.sh` for all Python tooling; caches stay under `/tmp/sdh_ludusavi`. Do not run any Steam Deck / on-device test — on-device verification (open Backup Browser for a game while hovering a different library game, click Restore, confirm the QAM keeps showing the restored game throughout) is deferred until the dev release is pushed to GitHub.

## Completion and Review Handoff

1. After all commits and a clean quality gate, create an empty marker file at:
   ```
   /tmp/sdh_ludusavi/2026-06-14_lock_selected_game_during_operation_finished
   ```
   This signals the implementation pass is complete.

2. Then watch for review notes at:
   ```
   docs/review/2026-06-14_lock_selected_game_during_operation_review.md
   ```
   Poll for this file. Do **not** create or write it — review notes are provided there externally. While it is absent, or its first line is not `STATUS: APPROVED`, keep waiting.

3. When the review file shows `STATUS: CHANGES_REQUESTED` and a numbered list of notes: address every note (RED→GREEN for any behavior change), re-run the full quality gate, commit the fixes, recreate the `_finished` marker, and continue watching.

4. When the review file shows `STATUS: APPROVED`:
   - Commit the still-untracked docs in the project dir if not already committed: the plan (`docs(plans): add selected-game lock during operations plan`) and the review file (`docs(review): record review notes for selected-game lock during operations`).
   - Run the full quality gate once more (all green).
   - Merge `fix/qam-selection-lock-during-operation` into `dev` and delete the working branch.
   - Push `dev` to GitHub.
   - Dispatch a dev release from `dev` HEAD: `./scripts/request_dev_release.sh 0.3.0`.

Do not publish stable releases, push tags, or run any other release path.

## Files

- `src/components/qam/qamOpenSelection.ts` — new pure decision helper.
- `src/components/qam/qamOpenSelection.test.ts` — new tests.
- `src/components/qam/LudusaviContent.tsx` — add `operationInProgress` ref; gate the deferred selection effect via the helper; set/clear the ref in `runForceOperation` and `runSnapshotRestore`.
- `docs/plans/2026-06-14_lock_selected_game_during_operation.md` — this plan.
- `docs/agent_conversations/2026-06-14_lock_selected_game_during_operation.json` — session log.
