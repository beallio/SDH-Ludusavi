# Steam-Aligned Autosync Status Strip Messaging

## Problem Definition

The autosync status strip currently shows restore or backup action language before the
backend has verified whether any save data must move. This can mislead users during
game launch and exit because the plugin may only be checking recency or previewing a
backup.

## Architecture Overview

Split lifecycle autosync into explicit check and action RPCs. The frontend publishes a
checking state first, calls the check RPC, and only publishes download or upload action
copy when the check reports that an action is needed. Existing compatibility wrappers
keep the current one-call backend behavior for callers that still use
`handle_game_start` and `handle_game_exit`.

## Core Data Structures

- `OperationResult`: existing backend result shape for actual backup and restore work.
- Check result dictionaries: `{"status": "needed" | "skipped", "operation": ...}` for
  actionable checks or existing skipped result shapes for disabled, unmatched, current,
  unknown, and failure-adjacent conditions.
- `AutoSyncStatusKind`: frontend status kinds extended with `checking` and `unknown`.

## Public Interfaces

- `check_game_start(game_name, app_id?)`
- `restore_game_on_start(game_name, app_id?)`
- `check_game_exit(game_name, app_id?)`
- `backup_game_on_exit(game_name, app_id?)`
- Existing `handle_game_start(game_name, app_id?)` and
  `handle_game_exit(game_name, app_id?)` remain compatibility wrappers.

## Dependency Requirements

No new runtime dependencies are required. Existing Ludusavi adapter calls provide the
required recency and backup-preview data.

## Testing Strategy

- Backend tests prove checks do not call restore/backup and action methods preserve
  history and refresh behavior.
- Main RPC tests prove Decky bridge methods expose the new service calls.
- Frontend static tests prove checking is published before check RPCs and action
  messages are published only after needed results.
- HTML diagram tests prove the documentation artifact captures both launch and exit
  state flows and the visible status strip copy.
- Targeted and full validation run through `./run.sh`.

## HTML Diagram Addendum

Create `docs/status_bar_game_state_flows.html` as a standalone browser-openable diagram
showing the two automatic lifecycle paths:

- Game launch: app lifetime start -> `VERIFYING GAME SAVE` -> `check_game_start` ->
  restore needed/current/unknown/unable-to-sync branches.
- Game exit: app lifetime stop -> `VERIFYING GAME SAVE` -> `check_game_exit` ->
  backup needed/current/unknown/unable-to-sync branches.
