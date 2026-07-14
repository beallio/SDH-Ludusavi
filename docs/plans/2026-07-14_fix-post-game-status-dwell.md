# Fix Post-Game Status Dwell

## Objective

Restore the intended 900 ms minimum display time for a successful post-game
`GAME SAVE UP TO DATE` result before the BrowserUI transitions to a Syncthing handoff
status, then publish and verify a replacement development prerelease.

## Problem Definition

Live `steamdeck` logs from `v0.3.6-dev.g0fe48e6` show a successful post-game backup
publishing `has_backup` at `11:28:27.476` and `syncthing_pending_upload` at
`11:28:27.478`. The two-millisecond transition violates the 900 ms dwell contract.

`evaluateExitBackup` currently emits a generic `publishStatus` command for
`has_backup`. That path omits both the `backed_up` result and completion lifecycle
provenance, so `autoSyncStatusSurface` cannot recognize the state as an eligible
successful post-game result.

## Scope

In scope:

- preserve successful backup provenance through the exit decision/controller boundary;
- prove the controller produces a backed-up completion that activates the existing dwell;
- preserve pending/uploading/complete handoff behavior and failure behavior;
- run the full repository validation ladder and publish a new dev prerelease.

Out of scope:

- changing the 900 ms duration;
- changing Syncthing polling or handoff state-machine behavior;
- changing BrowserView layout or copy;
- addressing Decky WSRouter pending-task messages during plugin reload.

## Architecture Overview

Keep the existing ownership boundaries. `gameLifecycleDecision.ts` decides how a
successful backup is represented. `gameLifecycleController.tsx` executes the decision
with `lifecycle_exit` provenance. `autoSyncStatusSurface.tsx` remains the only owner of
the dwell timer and deferred Syncthing status.

The minimal correction is to represent a successful exit backup as `completeStatus`
with the original `OperationResult`, rather than publishing `has_backup` directly. The
existing completion adapter then supplies `resultStatus: backed_up` and lifecycle
provenance to the status surface.

## Core Data Structures

No new structures are required. Reuse:

- `LifecycleCommand.completeStatus` with the original `OperationResult`;
- `AutoSyncStatusCompleteOptions.lifecycle` set to `lifecycle_exit`;
- `AutoSyncStatusState.resultStatus` set to `backed_up` by the completion surface.

## Public Interfaces

No RPC, persisted setting, BrowserView API, or external type changes are required. The
observable BrowserUI contract remains:

```text
BACKING UP LOCAL SAVE
GAME SAVE UP TO DATE        (visible for at least 900 ms)
SYNCTHING PREPARING|UPLOADING|COMPLETE
```

## Dependency Requirements

No dependency changes are required.

## Phases and Tasks

### 1. Regression test (RED)

- Add a focused decision/controller regression proving a successful exit backup is
  completed with the original `backed_up` result rather than published generically.
- Add or extend the integration-level fake-timer assertion proving a pending Syncthing
  handoff cannot replace `has_backup` until `HAS_BACKUP_MIN_DWELL_MS` elapses.
- Run the focused test and capture the expected failure before changing implementation.

### 2. Minimal fix (GREEN)

- Change the successful exit-backup decision to emit `completeStatus` with the original
  result while preserving `nextRpc: handoff`.
- Run the focused tests and typecheck.

### 3. Refactor and documentation

- Remove no-longer-useful controller branching only if the focused change exposes it;
  otherwise keep the patch minimal.
- Record the live-log root cause, test evidence, and results in a dated session record.

### 4. Verification and release

- Run Ruff check/format, `ty`, pytest, frontend verification, and diff integrity checks.
- Commit the plan/test/fix/session record atomically with Conventional Commits.
- Merge the passing fix into `dev`, push `dev`, request a development release for base
  version `0.3.6`, wait for GitHub Actions, and verify the versioned ZIP/checksum/manifest.

## Testing Strategy

Targeted tests must cover:

- successful exit backup carries `backed_up` completion provenance;
- the post-game pending handoff is deferred for the remaining 900 ms dwell;
- pre-game restored/current results do not gain the post-game dwell;
- unavailable/stale handoff fallback still completes with the backup result;
- existing BrowserUI status timing and handoff tests remain green.

The final validation ladder is:

```bash
./run.sh uv run ruff check .
./run.sh uv run ruff format --check .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
git diff --check dev...HEAD
```

## Commit Strategy

Use the dedicated branch `fix/post-game-status-dwell` and a Conventional Commit such as:

```text
fix(status): preserve post-game backup dwell provenance
```
