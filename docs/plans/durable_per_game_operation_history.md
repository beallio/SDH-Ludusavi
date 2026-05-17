# Durable Per-Game Operation History Implementation Plan

## Problem Definition

The plugin currently exposes current Ludusavi game status and recent logs, but
users cannot quickly tell what SDH-ludusavi last did for a specific game after a
plugin reload. This makes successful syncs, conservative skips, and failures
harder to verify from the main panel.

Add durable latest-summary history per Ludusavi game and show it compactly for the
selected game.

## Architecture Overview

Extend the existing backend state file with a `game_history` map keyed by Ludusavi
game name, stored alongside the current game cache markers. The service records
history at the same decision points where it already returns operation results or
skip reasons. The frontend receives history with `refresh_games`, stores it in
React state, and renders the selected game's summary below the current status line.

No new backend RPC is required for v1.

## Core Data Structures

Backend:

- Add a game history summary type with `last_backup`, `last_restore`, `last_skip`,
  and `last_failure`.
- Add a history entry type with `operation`, `trigger`, `status`, `reason`,
  `message`, and `timestamp`.
- Store `_game_history: dict[str, GameOperationHistory]` in
  `SDHLudusaviService`.
- Preserve existing `_installed_app_ids` and `_ludusavi_config_mtime_ns` cache
  marker fields independently from history.

Frontend:

- Add `GameOperationHistoryEntry` and `GameOperationHistory` TypeScript types.
- Extend `RefreshResult` with `history: Record<string, GameOperationHistory>`.
- Add `gameHistory` React state and derive `selectedHistory` from `selectedGame`.

## Public Interfaces

Update `refresh_games(force, installed_app_ids=None)` payloads:

```json
{
  "games": [],
  "aliases": {},
  "dependency_error": null,
  "history": {}
}
```

Keep these interfaces unchanged:

- `get_settings`
- `set_auto_sync_enabled`
- `set_selected_game`
- `force_backup`
- `force_restore`
- `handle_game_start`
- `handle_game_exit`
- `get_operation_status`
- `get_recent_logs`

Also keep the existing frontend callable argument shape unchanged:

```ts
callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>(
  "refresh_games"
);
```

## Implementation Steps

1. Create the feature branch:

   ```bash
   git switch -c feat/per-game-operation-history
   ```

2. Add red backend tests before implementation:

   - Successful manual backup records `last_backup`.
   - Successful manual restore records `last_restore`.
   - Auto-start skip after a matched game records `last_skip`.
   - Global Automatic Sync disabled before a game match remains log-only and does
     not create per-game history.
   - Auto-exit skip after a matched game records `last_skip`.
   - Game-scoped backup or restore exception records `last_failure`.
   - Reloading the service preserves `game_history`.
   - Malformed `game_history` state loads safely.
   - Refreshing after a game disappears does not prune history.
   - A dependency-error refresh still returns cached `history`.
   - Cache-hit refreshes return cached `history` without touching Ludusavi.
   - Operation-locked refresh responses preserve the existing `RpcStatus` shape,
     and the frontend leaves existing history state unchanged.
   - Adding history does not alter `installed_app_ids` or
     `ludusavi_config_mtime_ns` persistence.
   - Existing exact-payload tests for `refresh_games` are updated to include
     `history: {}` where no history exists.

3. Add red frontend static tests before implementation:

   - `RefreshResult` includes `history`.
   - UI state stores `gameHistory`.
   - A compact `Last Operation` row is rendered below the status row.
   - Only the highest-priority selected-game history entry is displayed.
   - Dropdown labels remain game names only.

4. Implement backend history support:

   - Add history models/helpers in `py_modules/sdh_ludusavi/service.py`.
   - Load and save `game_history` in `_load_state` and `_save_state`.
   - Return history in all `RefreshResult` payloads: cache hit, successful
     refresh, and dependency error.
   - Do not change the `RpcStatus` shape returned by the async RPC wrapper for
     operation lock errors.
   - Keep cache marker normalization, config marker checks, and operation-bound
     marker commits unchanged.
   - Record success after backup/restore success.
   - Record matched-game skips from existing skip paths.
   - Record game-scoped failures where exceptions are caught or re-raised.
   - Preserve existing log behavior and operation-lock behavior.

5. Implement frontend display:

   - Add history types and `gameHistory` state in `src/index.tsx`.
   - Update `applyRefreshResult` to store `result.history ?? {}`.
   - Render one compact selected-game `Last Operation` row below the status text.
   - Prefer failure when present; otherwise show the most recent backup, restore,
     or skip entry.
   - Keep the row visually muted and short so the QAM does not push Force Backup
     or Force Restore out of the immediate viewport.
   - Do not add history to dropdown labels.

6. Update docs after behavior lands:

   - README status documentation should mention persisted selected-game history.
   - Add an agent session log under `docs/agent_conversations/`.

## Edge Cases

- Missing history in older state files must not change current behavior.
- Malformed history must not prevent settings, game cache, aliases, or shortcut ID
  from loading.
- Unmatched lifecycle events must not create anonymous history records.
- Auto-sync disabled skips before matching must remain log-only.
- If the user manually deletes backups in Ludusavi, `last_backup` remains a record
  of the last successful plugin backup until a newer selected-game operation
  overwrites a history slot.
- If Ludusavi cannot be discovered during refresh, cached selected-game history
  should remain visible when available.
- If installed app IDs or the Ludusavi config marker are malformed, unavailable,
  or changed, refresh invalidation behaves exactly as it does before this feature;
  history is returned with the resulting cached or refreshed game payload.
- Hidden retained history for missing games must not clutter the UI.

## Validation

Run the standard validation stack:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run typecheck
pnpm run build
```

If `pnpm run verify` is required by the current hook or release path, run it after
the local build. If it fails with a registry/DNS error, rerun with network access
and record that the first failure was environmental.

## Git Strategy

Use atomic commits:

1. `docs(history): add per-game operation history plan and spec`
2. `feat(history): persist per-game operation summaries`
3. `feat(ui): show selected game operation history`

Run the real pre-commit hook before each commit if committing this work.

## Acceptance Criteria

- Per-game history persists across service reloads.
- Current users with old state files do not need migration steps.
- Selected-game history is visible only when history exists and occupies a single
  compact `Last Operation` row.
- Missing games do not lose history during refresh.
- Dependency-error refreshes keep cached history visible for the previously
  selected game when available.
- Steam installed-app and Ludusavi config cache markers continue to invalidate or
  reuse cached game data exactly as they do before this feature.
- Automatic sync behavior, manual actions, logs, versions, and launcher behavior
  remain otherwise unchanged.
