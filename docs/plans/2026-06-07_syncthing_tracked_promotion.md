# Fix Plan: Promote `tracked` After Backend Match Confirmation

## Problem Definition

The plugin uses a frontend `isTracked(name, appID)` check to decide whether to start a
Syncthing watch for a game. This check queries `LudusaviStateStore.trackedAppIDs` and
`trackedNames`, which are populated from the last Ludusavi refresh result.

Two failure modes cause `tracked=false` despite the backup succeeding:

1. **Timing race**: The Ludusavi refresh result may not have been pushed to the frontend
   state at the moment `isTracked` is called (milliseconds after plugin load). The
   check fires at game-start and game-exit, both of which can race with initial state
   hydration.

2. **Non-Steam appID**: `buildTrackedAppIDs` only indexes `game.steam_id`. Heroic or
   non-Steam games have a different appID format (10-digit vs 7-9 digit Steam IDs) and
   will never match by appID, falling back to name matching — which fails during the
   timing window.

Result: `autoSyncEnabledExit && tracked` is `false`, no Syncthing watch is started, and
no Syncthing status is ever shown — even though the backup completed successfully.

## Architecture Overview

The fix is a **post-RPC tracked promotion**: after `check_game_exit` returns `needed`
(backup required) or `backed_up`, re-evaluate `tracked` using the backend-confirmed
game name from the RPC response. If the RPC response contains a matched game name, treat
the game as tracked for the Syncthing gate — the backend match is authoritative proof
that Ludusavi owns this game.

This approach:
- Does not change the `isTracked` function or state schema
- Does not require a new RPC
- Does not change backend code
- Promotes `tracked` exactly once, only when the backend confirms a match
- Is safe: only activates Syncthing on a path where backup is confirmed necessary

## Core Data Structures

No new types. The existing `checkResult` from `check_game_exit` includes `game` (the
matched game name). After promotion, `tracked` is a local `let` variable that can be
reassigned to `true`.

## Public Interfaces

`handleAppExit` internal flow change only. No API surface changes.

## Fix Detail

In `handleAppExit`, after `check_game_exit` returns `needed`:

```ts
// Re-evaluate tracked using the backend-confirmed game name.
// The backend match is authoritative: if it returned 'needed', Ludusavi owns
// this game regardless of whether isTracked() found it in the frontend registry.
if (!tracked && checkResult.status === "needed") {
  tracked = true;
  log("info", `tracked promoted via backend match: ${name} (${appID})`);
}

if (autoSyncEnabledExit && tracked) {
  // start Syncthing watch
}
```

Currently the Syncthing watch start is at line 328-330, **before** the check_game_exit
call. The fix requires reordering: move the watch start to after `check_game_exit`
confirms the game is needed, using the promoted `tracked` value.

This is safe because:
- The plan spec says the watch must begin before `backupGameOnExitCall` — that
  constraint is still satisfied if we start between check and backup.
- Starting between check and backup means the watch has 2-4 seconds of backup time to
  initialize.

## Testing Strategy

Add tests to `src/controllers/gameLifecycleController.test.ts`:

1. `untracked game that backend matches starts Syncthing watch after check confirms needed`
2. `untracked game with local_current result does not start Syncthing watch`
3. `untracked game with failed check does not start Syncthing watch`

All tests use fake timers, vitest, and the existing mock patterns.
