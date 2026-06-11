# Diagnostic Logging Improvements

## Problem Definition

Users (and the maintainer) cannot reliably answer "why did the plugin do X?" from the
logs. An audit found several silent decision points:

Status bar (frontend):
1. `completeAutoSyncStatus` silently drops the final operation result when the status
   bar already auto-hid via the 10s running-status timeout (`autoSyncStatusTimedOut`),
   so a backup can succeed with no visible/logged final status.
2. `completeAutoSyncStatus` silently falls through when the result status is not one of
   the handled values — nothing is published and nothing is logged.
3. The epoch-guarded surface in `gameLifecycleController` silently drops stale
   publish/complete/hide calls when a newer lifecycle event superseded them.
4. When the pre-RPC "VERIFYING GAME SAVE" bar is not shown, the controller never logs
   why (untracked game vs. status notifications disabled vs. empty tracking cache).
5. The auto-hide scheduling (2s result / 10s running) is invisible in logs; when the
   10s running timeout fires, the user sees the bar vanish with no explanation that the
   final result will be suppressed.

Backend:
6. `LudusaviAdapter.compare_recency` — the core restore/skip/conflict verdict — never
   logs what the restore preview reported or which verdict it returned.
7. `check_game_start` records ambiguous-recency conflicts in history but never logs
   that it is prompting the user, nor the timestamps the direction decision used.
8. `check_game_exit` skips or proceeds based on preview `decision`/`change`/file
   counts that are never logged.

## Architecture Overview

No structural changes. Add log statements at existing decision points using the
existing logging channels:

- Backend: module `LOGGER` (routed into `DiagnosticLogBuffer` + decky logger by
  `DeckyLogHandler`) and the injected `dependencies.log` callable in
  `GameLifecycleManager`.
- Frontend: existing `log()` util in `src/utils/logging.ts` (console + backend RPC),
  with operation tag `autosync_status` for surface logs and `lifecycle` for controller
  logs.

Log levels: `info` for decisions that change visible behavior (verdicts, suppressed
final status, timeout-hide of a running status); `debug` for mechanical detail
(auto-hide scheduling, stale-epoch drops, preview summaries beyond the skip reason).

## Core Data Structures

None added. `AutoSyncStatusPublishOptions` and `LifecycleDependencies` are unchanged.

## Public Interfaces

No interface changes. All edits are additive log statements inside existing function
bodies:

- `py_modules/sdh_ludusavi/ludusavi.py::compare_recency`
- `py_modules/sdh_ludusavi/lifecycle.py::check_game_start`, `check_game_exit`
- `src/surfaces/autoSyncStatusSurface.tsx::completeAutoSyncStatus`,
  `scheduleAutoSyncStatusHide`
- `src/controllers/gameLifecycleController.tsx::createEpochGuardedSurface`,
  `handleAppStart`, `handleAppExit`

## Dependency Requirements

None. Uses existing `logging` (Python) and `src/utils/logging.ts` (TypeScript).

## Testing Strategy

Red-Green per change:

Backend (`tests/test_decision_logging.py`, pytest + caplog/MagicMock):
- `compare_recency` logs the preview `change` value and the returned verdict for the
  no-backup, Same, New, Different, and ambiguous paths.
- `check_game_start` logs the conflict prompt (with local/backup timestamps) when
  recency is ambiguous.
- `check_game_exit` logs a preview summary including decision, change, and file and
  registry entry counts.

Frontend (vitest):
- `autoSyncStatusSurface.suppression.test.ts`: publishing `backing_up`, advancing past
  the 10s timeout, then completing with `backed_up` logs an info suppression message
  and does not publish `has_backup`; the timeout-hide itself logs that the final
  result will be suppressed; auto-hide scheduling logs at debug.
- `gameLifecycleController.test.ts` additions: when
  `shouldPublishAutoSyncStatusBeforeRpc` is false, the controller logs the gating
  inputs (tracked, autoSyncNotificationsEnabled, tracking cache sizes); when a stale
  epoch drops a status publish, a debug log records it.

Quality gates: `./run.sh uv run ruff check . --fix`, `ruff format .`,
`ty check py_modules/sdh_ludusavi/`, `pytest`, plus `pnpm test` (vitest + tsc).
