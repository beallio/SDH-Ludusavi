# Durable Per-Game Operation History Spec

## Purpose

SDH-ludusavi currently exposes live game status, a global operation status, and a
recent in-memory log buffer. Users can see whether the selected game has a backup,
but they cannot quickly answer what the plugin last did for that game after reloads.

Durable per-game operation history adds a persisted latest-summary record for each
Ludusavi game. The feature is diagnostic and confidence-building: it makes the
selected game's last backup, restore, skip, or failure visible without requiring
users to inspect logs.

## Product Contract

- History is keyed by Ludusavi game name. Steam app IDs are optional matching
  metadata and must not be the history identity.
- History is latest-summary-only for v1. It is not a full event log.
- The UI displays history only for the currently selected game.
- The UI history surface must be compact enough for Decky QAM. It should not push
  Force Backup or Force Restore out of the immediate viewport on normal Deck
  resolutions.
- History for games missing from the latest Ludusavi refresh remains persisted but
  hidden unless the game appears again or is selected from cached state.
- The feature must not make auto-sync more aggressive. Existing conservative skip
  behavior remains unchanged.
- Manual Force Backup and Force Restore remain available when Automatic Sync is
  disabled, subject to current game status and the global operation lock.

## Persisted State

Add a `game_history` object to `sdh_ludusavi.json`.

```json
{
  "auto_sync_enabled": true,
  "selected_game": "Hades",
  "ludusaviLauncherShortcutAppId": 123456,
  "games": [],
  "aliases": {},
  "ids": {},
  "installed_app_ids": "220,1145360",
  "ludusavi_config_mtime_ns": 1779045930123456789,
  "game_history": {
    "Hades": {
      "last_backup": {
        "operation": "backup",
        "trigger": "manual_backup",
        "status": "backed_up",
        "reason": null,
        "message": null,
        "timestamp": "2026-05-17 14:25:30"
      },
      "last_restore": null,
      "last_skip": {
        "operation": "start",
        "trigger": "auto_start",
        "status": "skipped",
        "reason": "local_current",
        "message": null,
        "timestamp": "2026-05-17 15:10:11"
      },
      "last_failure": null
    }
  }
}
```

### History Summary

Each game maps to a `GameOperationHistory` summary:

- `last_backup`: latest successful backup for the game, or `null`.
- `last_restore`: latest successful restore for the game, or `null`.
- `last_skip`: latest matched-game skip for the game, or `null`.
- `last_failure`: latest game-scoped operation failure for the game, or `null`.

### History Entry

Each non-null entry contains:

- `operation`: one of `backup`, `restore`, `start`, or `exit`.
- `trigger`: one of `manual_backup`, `manual_restore`, `auto_start`, or
  `auto_exit`.
- `status`: one of `backed_up`, `restored`, `skipped`, or `failed`.
- `reason`: skip reason when `status` is `skipped`; otherwise `null`.
- `message`: failure message or optional detail; otherwise `null`.
- `timestamp`: local timestamp formatted like existing recent logs,
  `YYYY-MM-DD HH:MM:SS`.

## Recording Rules

The backend records history only after a Ludusavi game has been matched.

Record success:

- `force_backup(game_name)` updates `last_backup` with trigger `manual_backup`.
- Auto exit backup updates `last_backup` with trigger `auto_exit`.
- `force_restore(game_name)` updates `last_restore` with trigger `manual_restore`.
- Auto start restore updates `last_restore` with trigger `auto_start`.

Record skips:

- Matched-game auto-start skips update `last_skip`.
- Matched-game auto-exit skips update `last_skip`.
- Manual restore skip for `no_backup` updates `last_skip`.
- Manual backup or restore skip for `unmatched_game` does not update history
  because no canonical game key is available.

Do not record:

- Auto-sync disabled before a game is matched.
- Operation lock skips before a game is matched.
- Unmatched lifecycle events.
- Refresh, version lookup, launcher, or log operations.
- Dependency refresh failures that are not scoped to a single matched game.

Global Automatic Sync disabled skips are intentionally log-only. The UI should not
present them as selected-game history because they reflect a global setting gate,
not a game-specific decision.

Record failures:

- Game-scoped exceptions during backup or restore update `last_failure`.
- The entry uses the matched Ludusavi game name, the attempted operation, the
  appropriate trigger, status `failed`, and the exception message.

## State Loading And Compatibility

- Missing `game_history` loads as an empty map.
- A malformed top-level `game_history` value loads as an empty map.
- A malformed per-game history summary is ignored for that game.
- A malformed history entry is ignored for that entry only.
- Existing state files remain valid.
- Refreshing games must not prune `game_history`.
- `game_history` is persisted beside the existing cache markers. Loading,
  saving, or updating history must not clear, rewrite, or reinterpret
  `installed_app_ids` or `ludusavi_config_mtime_ns`; those markers continue to
  control whether cached game status can be reused on QAM open.

## Backend Interfaces

`refresh_games(force, installed_app_ids=None)` gains a `history` field:

```json
{
  "games": [],
  "aliases": {},
  "dependency_error": null,
  "history": {}
}
```

The `history` field is a map of Ludusavi game name to `GameOperationHistory`.
It may include entries for games not present in the current `games` list.
When `dependency_error` is non-null, the backend still returns cached history so
the frontend can show the previously selected game's last operation if available.

No new RPC is required for v1.
The current `installed_app_ids` cache marker parameter remains unchanged and must
continue to flow from the frontend to the backend on initial and manual refreshes.

## Frontend Interfaces

Mirror the backend shape in TypeScript:

```ts
type GameOperationHistoryEntry = {
  operation: "backup" | "restore" | "start" | "exit";
  trigger: "manual_backup" | "manual_restore" | "auto_start" | "auto_exit";
  status: "backed_up" | "restored" | "skipped" | "failed";
  reason: string | null;
  message: string | null;
  timestamp: string;
};

type GameOperationHistory = {
  last_backup: GameOperationHistoryEntry | null;
  last_restore: GameOperationHistoryEntry | null;
  last_skip: GameOperationHistoryEntry | null;
  last_failure: GameOperationHistoryEntry | null;
};
```

`RefreshResult` gains:

```ts
history: Record<string, GameOperationHistory>;
```

The existing callable signature remains:

```ts
callable<[force: boolean, installed_app_ids?: string], RpcResult<RefreshResult>>(
  "refresh_games"
);
```

History must be included in all `RefreshResult` paths: cache hit, successful
forced refresh, and dependency-error refresh. Operation-locked refresh calls keep
the existing `RpcStatus` response shape; the frontend should leave its current
`gameHistory` state unchanged when it receives that non-`RefreshResult` payload.

## UI Behavior

The selected-game status area gains a compact `Last Operation` row below the
current status text. The row should use short labels and muted styling so it is
visually distinct without becoming a new panel section.

Display priority:

- Show `last_failure` first when present.
- Otherwise show the most recent entry among `last_backup`, `last_restore`, and
  `last_skip`.
- Include timestamp plus a short outcome phrase such as `Backup completed`,
  `Restore completed`, `Skipped: local_current`, or `Failed: <message>`.

If the selected game has no history, the UI shows no additional empty history
block. Dropdown labels remain game names only.

## Known Stale States

History records what SDH-ludusavi last did; it is not a live assertion that the
backup still exists. If a user manually deletes backups in Ludusavi, `last_backup`
may still show the previous successful backup until a later selected-game
operation records a newer skip, restore, backup, or failure.

## Documentation

README status documentation should mention that selected-game history is persisted
and distinguish it from the recent log buffer, which remains a chronological
diagnostic view.
