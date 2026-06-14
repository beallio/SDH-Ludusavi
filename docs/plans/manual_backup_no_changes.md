# Manual Backup and Restore No-Change Handling

## Problem Definition

Manual backup and restore currently record successful `backed_up` or `restored`
history even when Ludusavi reports the per-game change as `"Same"`. This makes
the QAM history imply that a snapshot or restore changed data when the operation
was a no-op.

Manual operations that return `"Same"` must record the existing
`skipped`/`local_current` outcome. Missing or malformed change data must retain
the current success behavior for compatibility.

## Architecture Overview

The backend lifecycle service owns manual backup and restore orchestration.
It will defensively extract the selected game's `change` value from the
Ludusavi result and choose the corresponding history and API outcome.

No frontend change is required because history already promotes a skip to
`last_operation`, and the frontend already renders `local_current`.
Point-in-time restore remains unchanged.

## Core Data Structures

- Ludusavi result: an arbitrary object that may contain
  `games[game_name].change`.
- Recognized no-op value: the exact string `"Same"`.
- Skip result:
  `{"status": "skipped", "reason": "local_current", "game": ..., "result": ...}`.
- Existing success results remain `backed_up` and `restored`.

## Public Interfaces

- `LifecycleService.force_backup(game_name)` keeps its existing result shape and
  adds the documented skipped outcome when the adapter reports `"Same"`.
- `LifecycleService.force_restore(game_name)` applies the symmetric behavior.
- No TypeScript interfaces, RPC names, or user-facing strings change.

## Dependency Requirements

No dependency changes are required. Project tooling runs through `./run.sh`
with `UV_FROZEN=1` where needed to preserve `uv.lock`.

## Testing Strategy

Follow strict RED-GREEN-REFACTOR:

1. Add integration tests for backup `"Same"`, `"Different"`, and missing
   change data.
2. Add integration tests for restore `"Same"` and `"Different"`.
3. Run the targeted `skip or no_change` selection and confirm failure before
   production edits.
4. Implement defensive result parsing and the two manual-operation branches.
5. Run Ruff check/format, `ty`, and the full pytest suite.

## Git and Review Protocol

Work occurs on `fix/manual-backup-no-changes`, created from `dev`. Commits use
Conventional Commits and the required co-author trailer. After each committed,
validated round, create
`/tmp/sdh_ludusavi/elegant-swinging-bengio_finished` and wait for reviewer-owned
notes or `docs/review/elegant-swinging-bengio/APPROVED`.
