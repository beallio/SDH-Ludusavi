# Sticky Action Game + Debug Log Prefix Fix

Slug: `2026-06-14_sticky_action_game_and_debug_log`
Branch: `fix/qam-selection-and-debug-log`
Execution skill: `implementer`

## Context

Two defects were observed on-device (log: `/tmp/sdh_ludusavi/steamdeck-logs/2026-06-14 17.24.16.log`).

1. **Selected game jumps away after an action.** A user selects a game in the QAM (e.g. "Wobbly Life"), runs Force Backup or Restore, and the moment the operation finishes the QAM selection flips to a *different* game — the one currently hovered in the Steam library (e.g. "X-Men Origins: Wolverine", derived from the QAM route). In the log this is lines 156–164: the restore completes for Wobbly Life (156), the post-action refresh applies (161), and `selectCurrentSteamGameIfAvailable` immediately re-selects the route-hovered game (163), so `qam_closed` reports the wrong game (164). Desired: the game an action ran on stays selected, even when a different game is hovered in the library. The library-hovered game should only take over when the user leaves (closes the QAM or switches plugins) and returns.

2. **Doubled log level prefix.** Many lines read `[INFO]: [DEBUG] ...` (e.g. lines 3–10). Debug-level messages are routed through Decky's `logger.info()` with a literal `[DEBUG] ` string prepended. The line should read just `[INFO]: ...`.

Outcome: post-action selection is sticky; debug lines in the Decky log no longer carry the redundant `[DEBUG]` tag. The in-plugin Log modal continues to show the true level (the diagnostic ring buffer is unaffected).

## Problem Definition

### Bug 1 — selection
`applyRefreshResult` (`src/components/qam/LudusaviContent.tsx:452`) and `applyCachedRefreshResult` (`:428`) unconditionally call `selectCurrentSteamGameIfAvailable(...)` (`:480`, `:436`) **before** honoring the preferred/current selection. `selectCurrentSteamGameIfAvailable` (`:166`) reads the live Steam route/hover via `getPreferredSteamGameSession()` (`src/utils/steam.ts:310`) and overwrites the selection with the hovered library game. Because the post-action handlers `runForceOperation` (`:671`) and `runSnapshotRestore` (`:749`) call `applyRefreshResult(refreshed)` with no preferred game, the route-hovered game wins.

The "return to plugin shows the hovered game" behavior (the desired case) is handled separately and correctly by the QAM-open effect: `qam_opened` sets `pendingCurrentGameSelection.current = true` (`:219`) and the deferred effect (`:234`–`241`) runs `selectCurrentSteamGameIfAvailable` once when games are present. That path must stay intact — do not touch it.

Fix: route/hover auto-selection must happen **only** through that QAM-open path. `applyRefreshResult`/`applyCachedRefreshResult` must default to preserving the current selection, and only opt into route auto-selection on the initial load.

### Bug 2 — logging
`_decky_log_fallback` (`py_modules/sdh_ludusavi/log_buffer.py:60`) prepends `[DEBUG] ` to debug messages at `:74`:
```python
logger_level(f"[DEBUG] {message}" if level == "debug" else message)
```
Decky's logger (a stdlib `logging.Logger`, see `decky.pyi:169`) is at INFO level, so the line surfaces as `[INFO]: [DEBUG] ...`. Remove the prefix so debug lines render as plain `[INFO]: ...`. Keep the debug→info routing (map at `:69`) and the ring-buffer level (`push_log_record` stores the real `"debug"` level, so the Log modal is unchanged).

## Architecture Overview

- Selection decisions are centralized in a new pure helper `resolveRefreshedSelection` that both `applyRefreshResult` and `applyCachedRefreshResult` use for the non-route path (this also removes the duplicated preferred/first fallback blocks at `:484`–`493` and `:440`–`448`).
- A new boolean parameter `allowSteamContextSelection` (default `false`) gates the route/hover auto-selection. Only the initial-load caller passes `true`.
- The logging fix is a one-line change plus a covering test.

## Core Data Structures

New file `src/components/qam/refreshSelection.ts`:
```ts
export interface RefreshSelectionInput {
  games: readonly { name: string }[];
  preferredGame?: string;
  currentSelectedGame: string;
}

export interface RefreshSelectionOutcome {
  game: string;
  source: "preferred" | "first" | "none";
}

export function resolveRefreshedSelection(
  input: RefreshSelectionInput,
): RefreshSelectionOutcome {
  const target = input.preferredGame || input.currentSelectedGame;
  if (target && input.games.some((game) => game.name === target)) {
    return { game: target, source: "preferred" };
  }
  const first = input.games[0]?.name ?? "";
  return { game: first, source: first ? "first" : "none" };
}
```

## Public Interfaces

`src/components/qam/LudusaviContent.tsx`:
- `applyRefreshResult(result, preferredGame?, allowSteamContextSelection = false)`
- `applyCachedRefreshResult(preferredGame?, allowSteamContextSelection = false)`

Both gate the existing `selectCurrentSteamGameIfAvailable(...)` call behind `allowSteamContextSelection`, and use `resolveRefreshedSelection(...)` for the fallback. Example for `applyRefreshResult` (replacing current `:480`–`495`):
```ts
if (
  allowSteamContextSelection &&
  selectCurrentSteamGameIfAvailable(result.games, result.aliases || {})
) {
  return true;
}

const outcome = resolveRefreshedSelection({
  games: result.games,
  preferredGame,
  currentSelectedGame: selectedGame,
});
if (outcome.source === "first") {
  log("debug", `Defaulting selected game to ${outcome.game}`);
}
ludusaviStore.setSelectedGame(outcome.game);
syncSelectedGameCache(outcome.game);
return true;
```
Apply the analogous change to `applyCachedRefreshResult` (replacing `:436`–`449`; it has no `"Defaulting..."` log today — keep it without one).

Call-site updates in the same file:
- `synchronizeGameList` (`:412`, `:418`) — pass `true`: `applyCachedRefreshResult(preferredGame, true)` and `applyRefreshResult(refreshed, preferredGame, true)`. (Initial load: hovered game shows on first open.)
- `runForceOperation` (`:671`) — `applyRefreshResult(refreshed, selectedGame)`. (Sticky to the acted-on game; `allowSteamContextSelection` stays `false`.)
- `runSnapshotRestore` (`:749`) — `applyRefreshResult(refreshed, selectedGame)`.
- `refreshGames` (`:514`) — leave as `applyRefreshResult(result)`; the new `false` default makes manual refresh preserve the current selection instead of jumping to the hovered game.

`py_modules/sdh_ludusavi/log_buffer.py` — `_decky_log_fallback` `:74` becomes:
```python
logger_level(message)
```

## Dependency Requirements

None. No new packages. Reuse existing `getPreferredSteamGameSession` / `selectCurrentSteamGameIfAvailable` (unchanged) and the existing `ludusaviStore.setSelectedGame` / `syncSelectedGameCache` calls.

## Implementation Steps (strict TDD — RED before GREEN)

1. Create branch `fix/qam-selection-and-debug-log` off `dev`.

2. **Bug 2 test (RED).** Add to `tests/test_log_buffer.py` a test that injects a fake decky module and asserts debug messages have no `[DEBUG]` prefix:
   ```python
   def test_decky_log_fallback_debug_has_no_prefix(monkeypatch, tmp_path):
       import sys
       from tests.test_main import fake_decky_module
       from sdh_ludusavi.log_buffer import _decky_log_fallback

       decky, logger = fake_decky_module(tmp_path)
       monkeypatch.setitem(sys.modules, "decky", decky)
       _decky_log_fallback("debug", "refresh: hello")

       assert logger.infos == ["refresh: hello"]
       assert all("[DEBUG]" not in m for m in logger.infos)
   ```
   Run `./run.sh uv run pytest tests/test_log_buffer.py` and confirm it fails (current output is `["[DEBUG] refresh: hello"]`).

3. **Bug 2 GREEN.** Change `log_buffer.py:74` to `logger_level(message)`. Re-run; confirm green. Grep the repo for other assertions on the `[DEBUG]` prefix (`grep -rn "\[DEBUG\]" tests/`) and update any that encode the old behavior.

4. **Bug 1 test (RED).** Add `src/components/qam/refreshSelection.test.ts` covering `resolveRefreshedSelection`:
   - preferred game present in list → `{ source: "preferred", game: preferred }`.
   - no `preferredGame`, `currentSelectedGame` present → returns current selection (this is the sticky post-action case).
   - target absent from list → `{ source: "first" }` (first game).
   - empty list → `{ source: "none", game: "" }`.
   Run `pnpm run test:unit` (the import will fail because the module doesn't exist yet → RED).

5. **Bug 1 GREEN.** Create `src/components/qam/refreshSelection.ts` (code above). Re-run unit tests; confirm green.

6. **Bug 1 wiring.** In `LudusaviContent.tsx`: add the `allowSteamContextSelection` parameter and the `resolveRefreshedSelection` usage to `applyRefreshResult` and `applyCachedRefreshResult`; import `resolveRefreshedSelection`; update the four call sites per "Public Interfaces". Do **not** modify `selectCurrentSteamGameIfAvailable`, the `qam_opened` effect, or the deferred selection effect (`:234`–`241`).

7. Run the full quality gate (see Validation). Fix any issues at the root cause.

8. Commit as two atomic commits:
   - `fix(logging): drop redundant [DEBUG] prefix on forwarded debug logs`
   - `fix(qam): keep the acted-on game selected after backup/restore`

9. Write the session log `docs/agent_conversations/2026-06-14_sticky_action_game_and_debug_log.json` (date, task objective, files modified, tests added, design decisions, results) and commit as `docs(session): record sticky action game + debug log fix`.

## Testing Strategy

- Backend: `tests/test_log_buffer.py` new test (debug prefix removed), existing tests stay green.
- Frontend: `src/components/qam/refreshSelection.test.ts` new (pure decision logic, including the sticky-selection case).
- The `allowSteamContextSelection` gate itself is wiring over the tested decision helper; its end-to-end effect is confirmed on-device after the dev release (see Validation).

## Validation

Run from the repo root and require all green:
```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run test
pnpm run typecheck
pnpm run build
```
Use `./run.sh` for all Python tooling; caches stay under `/tmp/sdh_ludusavi`. Do not run any Steam Deck / on-device test — on-device verification of both behaviors is deferred until the dev release is pushed to GitHub.

## Completion and Review Handoff

1. After all commits and a clean quality gate, create an empty marker file at:
   ```
   /tmp/sdh_ludusavi/2026-06-14_sticky_action_game_and_debug_log_finished
   ```
   This signals the implementation pass is complete.

2. Then watch for review notes at:
   ```
   docs/review/2026-06-14_sticky_action_game_and_debug_log_review.md
   ```
   Poll for this file. Do **not** create or write it — review notes are provided there externally. While it is absent, or its first line is not `STATUS: APPROVED`, keep waiting.

3. When the review file shows `STATUS: CHANGES_REQUESTED` and a numbered list of notes: address every note (RED→GREEN for any behavior change), re-run the full quality gate, commit the fixes, recreate the `_finished` marker, and continue watching.

4. When the review file shows `STATUS: APPROVED`:
   - Commit the review file if it is not already committed (`docs(review): record review notes for sticky action game + debug log`).
   - Run the full quality gate once more (all green).
   - Merge `fix/qam-selection-and-debug-log` into `dev` and delete the working branch.
   - Push `dev` to GitHub.
   - Dispatch a dev release from `dev` HEAD: `./scripts/request_dev_release.sh 0.3.0`.

Do not publish stable releases, push tags, or run any other release path.

## Files

- `src/components/qam/LudusaviContent.tsx` — gate route auto-selection; use `resolveRefreshedSelection`; update 4 call sites.
- `src/components/qam/refreshSelection.ts` — new pure helper.
- `src/components/qam/refreshSelection.test.ts` — new tests.
- `py_modules/sdh_ludusavi/log_buffer.py` — drop `[DEBUG]` prefix (`:74`).
- `tests/test_log_buffer.py` — new prefix test.
- `docs/plans/2026-06-14_sticky_action_game_and_debug_log.md` — this plan.
- `docs/agent_conversations/2026-06-14_sticky_action_game_and_debug_log.json` — session log.
