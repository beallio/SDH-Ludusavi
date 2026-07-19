# Plan: Disabled Notice On Exit

## Problem Definition

The per-game disabled notice (`game_sync_disabled`) is currently start-only: on
exit, `autoSyncStatusSurface.complete()` hides the strip instead of publishing.
That was a deliberate earlier decision, now reversed — the notice should also
appear when exiting a game whose sync is disabled, confirming that no backup ran.

## Architecture Overview

Both `check_game_start` and `check_game_exit` already return the same
`game_sync_disabled` skip reason, and `evaluateExitCheck` already forwards
non-silent skipped results to `completeStatus`. The only change needed is in the
surface's `complete()` mapping: publish for both lifecycles rather than
publishing on start and hiding on exit.

The exit handler's suppression of the pre-check `checking` publish
(`gameLifecycleController.tsx`) is retained. Nothing is meaningfully being
checked for a disabled game, so the strip should show the disabled notice
directly rather than flashing `VERIFYING GAME SAVE` first.

## Core Data Structures

None. No new status kind, skip reason, setting, or persisted state.

## Public Interfaces

Unchanged. `complete()` keeps its signature; only which branch it takes for
`lifecycle_exit` differs.

## Dependency Requirements

None.

## Testing Strategy

`src/surfaces/autoSyncStatusSurface.test.ts` currently asserts the exit path
calls hide (`visible: false, source: "hide"`). That assertion is inverted to
expect a published `game_sync_disabled` status, which is the requested behavior
change rather than a test edited to mask a failure. Red is confirmed first.

Retain coverage that the notice still auto-hides afterwards, so the exit strip
does not linger — the lingering-strip failure mode this plan's predecessor fixed
must not regress.
