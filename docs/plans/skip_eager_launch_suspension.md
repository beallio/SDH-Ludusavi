# Skip Eager Launch Suspension For Untracked Apps

## User Review Required

> [!IMPORTANT]
> **Stale / Empty Cache Risk:** If the frontend cache is empty, such as during
> initial plugin loading or before refresh completes, a tracked game might launch
> without being paused.
>
> The fallback design handles this safely: if the backend later reports that a
> restore or conflict resolution is required but the process was not paused, the
> frontend already emits a notification error such as "Launch gate unavailable..."
> and aborts rather than racing the loading game. This is the preferred trade-off
> to protect local save files from concurrent overwrite risk.

## Problem Definition

`handleAppStart` currently attempts to suspend any launched application with a
numeric `instanceID > 0` before the frontend knows whether the app should be
handled by automatic Ludusavi sync. This can pause untracked applications such as
web browsers, launchers, or unrelated utilities, and it adds an unnecessary
awaited RPC round trip when auto-sync is disabled.

The desired behavior is to attempt launch suspension only when the frontend can
confirm that auto-sync is active, the application is locally tracked, and the
lifetime notification contains an eligible process instance ID.

## Architecture Overview

Keep the backend lifecycle check authoritative. The backend still decides whether
a launch is disabled, unmatched, current, restore-needed, conflict, or failed.
The frontend change only adds a conservative preflight before calling the process
suspension RPC.

The frontend launch gate should be:

```ts
const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;
const shouldPauseLaunch =
  autoSyncEnabled &&
  tracked &&
  typeof instanceID === "number" &&
  instanceID > 1;
```

`pauseGameProcessCall(instanceID)` should run only inside
`if (shouldPauseLaunch)`. The existing `paused` flag remains the only condition
that permits `resumeGameProcessCall(instanceID)` in `finally`, so the frontend
does not resume a process it did not successfully pause.

## Core Data Structures

- `LudusaviStateStore`: existing frontend store that holds the current settings,
  tracked app IDs, tracked names, aliases, and cached Ludusavi game state.
- `Settings.auto_sync_enabled`: existing persisted setting used to confirm that
  automatic sync is active.
- `tracked`: existing boolean from `isTracked(name, appID)`, based on the
  frontend's cached Ludusavi games and aliases.
- `instanceID`: existing optional Steam app lifetime notification instance ID.
  The launch gate should treat only numeric values greater than `1` as eligible
  for process suspension.
- `paused`: existing local flag in `handleAppStart`; it remains false unless
  `pauseGameProcessCall` returns a successful paused result.

## Public Interfaces

No public interfaces change.

- Do not change backend RPC names, parameters, or return shapes.
- Do not change TypeScript public types.
- Do not change `pause_game_process` or `resume_game_process`.
- Do not add third-party dependencies.
- Do not change `handleAppExit`.

## Dependency Requirements

No new dependencies are required.

Use the existing project wrapper for validation:

```bash
./run.sh <command>
```

## Proposed Changes

### Frontend Core

#### [MODIFY] [index.tsx](/home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)

- Inside `handleAppStart`, replace the unconditional `instanceID > 0` pause
  check at the current launch-gate block with the `shouldPauseLaunch` preflight.
- Insert the new `autoSyncEnabled` and `shouldPauseLaunch` constants immediately
  before the existing pause call site.
- Preserve the existing `pauseResult` handling:

```ts
if (shouldPauseLaunch) {
  const pauseResult = await pauseGameProcessCall(instanceID);
  if (!isRpcStatus(pauseResult) && pauseResult.status === "paused") {
    paused = true;
  }
}
```

- Leave `checkGameStartCall(name, appID)` after the optional pause path.
- Leave restore, conflict, status-strip, notification, catch, and finally logic
  unchanged.
- When `checkResult.status === "skipped"` with `reason` of `unmatched_game` or
  `auto_sync_disabled`, the existing silent skip path should hide the status and
  return. Since `paused` remains `false`, the `finally` block should safely omit
  `resumeGameProcessCall(instanceID)`.

### Testing Suite

#### [MODIFY] [test_frontend_static.py](/home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py)

- Update `test_frontend_launch_gate_pauses_before_start_check_and_resumes_in_finally`.
- Keep the existing string assertions for:
  - `const pauseResult = await pauseGameProcessCall(instanceID);`
  - `const checkResult = await checkGameStartCall(name, appID);`
  - `await resumeGameProcessCall(instanceID);`
- Keep the relative ordering assertion that the pause call appears before
  `checkGameStartCall`; this still passes when the pause call is nested inside
  the new conditional block.
- Add static assertions that:
  - `const autoSyncEnabled = ludusaviStore.getSnapshot().settings?.auto_sync_enabled === true;`
    exists in `handleAppStart`.
  - `const shouldPauseLaunch =` exists in `handleAppStart`.
  - `autoSyncEnabled`, `tracked`, `typeof instanceID === "number"`, and
    `instanceID > 1` all appear in the launch-gate construction.
  - `if (shouldPauseLaunch) {` appears before
    `const pauseResult = await pauseGameProcessCall(instanceID);`.
- Keep assertions that resume remains in `finally` and still depends on
  `paused`.

## Verification Plan

Follow Red-Green-Refactor.

1. Update `tests/test_frontend_static.py` first.
2. Run the targeted red test and confirm it fails before implementation.
3. Implement the scoped `src/index.tsx` change.
4. Re-run targeted validation.
5. Run required validation before commit.

### Automated Tests

Targeted red/green validation:

```bash
./run.sh uv run pytest tests/test_frontend_static.py
```

Required pre-commit validation:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

If unrelated user-owned files appear in `git status`, avoid broad formatting
that would modify them. Prefer targeted formatting only for files changed in the
session.

### Manual Verification

- Verify that launching an untracked app does not block the UI or trigger process
  suspension calls in local staging.
- Verify that launching any app while auto-sync is disabled does not block the UI
  or trigger process suspension calls.
- Verify that a tracked app with auto-sync enabled and `instanceID > 1` can still
  enter the launch gate before restore or conflict handling.
- Verify that backend skipped results for `unmatched_game` and
  `auto_sync_disabled` hide the status and do not call the resume RPC when no
  process was paused.

## Acceptance Criteria

- Untracked applications bypass `pauseGameProcessCall` entirely.
- Applications launched while auto-sync is disabled bypass
  `pauseGameProcessCall` entirely.
- `pauseGameProcessCall` runs only when auto-sync is confirmed enabled,
  `tracked` is true, and `instanceID > 1`.
- Existing restore and conflict paths still abort safely with the existing
  "Launch gate unavailable..." notification when the backend later reports a
  launch-gated operation but no process was paused.
- Static frontend tests cover the new preflight gate.
- Full required validation passes through `./run.sh`.

## Session Logging

After implementation and validation, record the session in
`docs/agent_conversations/` with:

- Date.
- Task objective.
- Files modified.
- Tests added or updated.
- Design decision to keep backend lifecycle checks authoritative.
- Validation commands and results.

## Assumptions

- `settings === null` means auto-sync is not confirmed active, so launch
  suspension is skipped until settings are loaded.
- The requested `instanceID > 1` threshold is correct unless implementation-time
  evidence shows `1` is a valid process root that must be paused.
- The existing backend skip behavior remains unchanged.
- The existing untracked review artifact is unrelated and should remain
  untouched unless explicitly requested.
