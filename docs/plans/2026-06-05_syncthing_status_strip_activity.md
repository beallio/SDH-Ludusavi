# Add Syncthing Activity To Autosync BrowserView Status Strip

## Problem Definition

The existing autosync BrowserView status strip shows SDH-Ludusavi lifecycle states such
as verifying, restoring, backing up, complete, conflict, and error. It does not show
whether Syncthing is actively syncing the Ludusavi backup folder after a pre-game
restore or post-game backup.

Add Syncthing activity visibility to the same BrowserView strip:

- cloud with down arrow for download/local-pull activity;
- cloud with up arrow for upload/remote-pull activity;
- cloud with checkmark when Syncthing activity is complete.

This is a display-only v1 feature. It must not block game launch, game exit, restore,
backup, or conflict handling.

Use these reference files for Syncthing behavior and JSON field semantics:

- `/tmp/sdh_ludusavi/syncthing_folder_watcher.md`
- `/tmp/sdh_ludusavi/syncthing_folder_activity.py`

Do not depend on `/tmp` at runtime. Adapt the required logic into the project.

## Branch And Execution Requirements

- Create a new branch from `main` before implementation:

  ```bash
  git switch main
  git switch -c feat/syncthing-status-strip-activity
  ```

- Follow `AGENTS.md` and `.protocol`.
- Use `./run.sh` for project tooling.
- Keep caches and temporary files under `/tmp/sdh_ludusavi`.
- Follow strict TDD: add failing tests before behavior-changing code.
- Preserve unrelated user work.
- Use Conventional Commits and keep commits atomic.

## Architecture Overview

Current relevant ownership:

- `src/surfaces/autoSyncStatusSurface.tsx` owns BrowserView creation, HTML rendering,
  status text/icons, timers, and teardown/reset behavior.
- `src/controllers/gameLifecycleController.tsx` owns app start/exit lifecycle flow and
  publishes autosync strip states around pre-game and post-game RPCs.
- `src/api/ludusaviRpc.ts` owns frontend RPC callables.
- `src/types/index.ts` owns frontend wire/result types.
- `main.py::Plugin` exposes async RPC wrappers.
- `py_modules/sdh_ludusavi/service.py::SDHLudusaviService` is the backend facade.
- `py_modules/sdh_ludusavi/gateway.py` exposes Ludusavi diagnostics, including
  `backupPath`.
- `py_modules/sdh_ludusavi/ludusavi.py::PyludusaviAdapter.get_diagnostics()` already
  reads Ludusavi's configured backup path.

New ownership:

- Add backend Syncthing config/API/activity code in
  `py_modules/sdh_ludusavi/syncthing.py`.
- Add a backend watch manager in that module or a small adjacent module if separation
  is clearer.
- Add service facade methods in `SDHLudusaviService`.
- Add RPC wrappers in `main.py`.
- Add frontend polling/strip publication in `createGameLifecycleController`.

## Core Data Structures

### Backend Watch Start Result

Return one of these shapes:

```python
{"status": "watching", "watch_id": str, "folder_id": str, "label": str, "path": str}
{"status": "skipped", "reason": str, "message": str}
{"status": "failed", "reason": str, "message": str}
```

Allowed skipped reasons:

- `syncthing_not_running`
- `backup_path_unavailable`
- `folder_not_found`
- `api_unavailable`
- `config_unavailable`

### Backend Poll Result

Return one of these shapes:

```python
{
  "status": "activity",
  "watch_id": str,
  "sample": {
    "status": str,
    "folder_id": str,
    "label": str,
    "folder_state": str,
    "active_transfer": bool,
    "update_in_progress": bool,
    "settled": bool,
    "downloading": bool,
    "uploading": bool,
    "receive_needed": bool,
    "need_bytes": int,
    "need_items": int,
    "need_deletes": int,
    "sequence": int,
    "pending_remote_ack": bool,
    "lagging_remote_devices": int,
    "timestamp_unix": float
  }
}
{"status": "stopped", "watch_id": str}
{"status": "skipped", "reason": str, "message": str}
{"status": "failed", "reason": str, "message": str}
```

Do not include API keys, config file contents, or full Syncthing device IDs in frontend
results.

### Frontend Status Kinds

Extend `AutoSyncStatusKind` with:

- `syncthing_downloading`
- `syncthing_uploading`
- `syncthing_complete`

Add status text:

- `SYNCTHING DOWNLOADING`
- `SYNCTHING UPLOADING`
- `SYNCTHING COMPLETE`

## Backend Implementation Plan

### Syncthing Config And API

Port/adapt from `/tmp/sdh_ludusavi/syncthing_folder_activity.py`:

- Syncthing config discovery for native and Flatpak config paths.
- GUI/API URL resolution from config `<gui>` address and TLS flag.
- API key resolution from config or environment.
- Standard-library HTTP client using `urllib`.
- Self-signed local HTTPS behavior: default to skipping TLS verification for local
  Syncthing, matching the reference script.

Rules:

- Treat API key as secret.
- Do not log API key.
- Do not expose API key through RPCs.
- Do not add dependencies.
- If Syncthing is unavailable, return `skipped`, not an unhandled exception.

### Folder Resolution

Resolve the Syncthing folder from Ludusavi `backupPath`.

Required behavior:

1. Call `service._gateway.get_diagnostics()` or an equivalent public helper.
2. Read `backupPath`.
3. If `backupPath` is missing, empty, or `"unknown"`, return
   `backup_path_unavailable`.
4. Fetch Syncthing `/rest/config/folders`.
5. Normalize paths with `expanduser`, `abspath`, `realpath`, and case normalization.
6. Select the deepest configured Syncthing folder whose path contains the Ludusavi
   backup path.
7. If no folder contains the backup path, return `folder_not_found`.

Do not add a user-facing Syncthing folder setting for v1.

### Activity Computation

Adapt the reference script's folder-level activity semantics:

- `downloading=true`: local Syncthing is pulling/applying data for the watched folder.
- `uploading=true`: a remote device is downloading from this local Syncthing instance.
- `update_in_progress=true`: scanning, preparing, local indexing, need counters,
  sequence changes, or active transfer.
- `settled=true`: local folder is idle with no folder-specific active/update signal.
- `pending_remote_ack=true`: diagnostic only; do not keep the UI active forever on
  this field.

Do not use aggregate connection byte rates as primary activity unless preserving the
reference module's diagnostic fields. Aggregate traffic is not folder-specific.

### Watch Manager

Implement backend-owned watcher management:

- Watch identity:
  - generated `watch_id`;
  - `phase: "pre_game" | "post_game"`;
  - optional `game_name`;
  - optional `app_id`;
  - resolved folder metadata;
  - latest sample;
  - `started_at`;
  - stop event.

- Starting a watch:
  - stop any existing watch for the same `phase + game_name + app_id`;
  - resolve Syncthing and folder;
  - start a daemon thread only if Syncthing is available;
  - return `watching` with metadata.

- Polling a watch:
  - return the latest sample without blocking the UI thread;
  - return `stopped` if the watch no longer exists.

- Stopping a watch:
  - set the stop event;
  - remove the watch from the manager;
  - best-effort join with a short timeout if needed.

- Service cleanup:
  - `SDHLudusaviService.stop()` must stop all Syncthing watchers before or along with
    the existing watchdog cleanup.
  - Plugin unload must continue to call backend stop/cleanup.

## Frontend Implementation Plan

### RPC Bindings

Add typed callables in `src/api/ludusaviRpc.ts`:

- `startSyncthingActivityWatchCall`
- `getSyncthingActivityCall`
- `stopSyncthingActivityWatchCall`

Add frontend result/sample types in `src/types/index.ts`.

### Lifecycle Integration

In `createGameLifecycleController`:

- Inject the new Syncthing RPCs through `LifecycleRpc`.
- Start a Syncthing watch only when:
  - autosync is enabled;
  - the game is tracked;
  - the lifecycle path is automatic pre-game or post-game.

Start timing:

- Pre-game: start immediately before `checkGameStartCall`.
- Post-game: start immediately before `checkGameExitCall`.

The user's "If possible this start watching when we activate the Ludusavi process" maps
to starting before the first lifecycle RPC that may touch Ludusavi, because that is the
earliest reliable frontend-owned activation point in the current architecture.

Polling:

- Poll every 1000 ms.
- Maximum watch duration: 120 seconds.
- Track whether any activity has been seen:
  - `downloading`
  - `uploading`
  - `update_in_progress`
  - non-idle active `status`
- After activity has been seen, publish complete only after 3 consecutive samples with
  `settled=true`.

Stop conditions:

- 3 consecutive settled samples after observed activity;
- lifecycle skipped for silent reasons;
- conflict state;
- failure/error;
- lifecycle handler exits;
- controller dispose;
- 120 second max duration.

Status mapping:

- If `sample.downloading`, publish `syncthing_downloading`.
- Else if `sample.uploading`, publish `syncthing_uploading`.
- Else if `sample.update_in_progress`, publish:
  - `syncthing_downloading` for `pre_game`;
  - `syncthing_uploading` for `post_game`.
- Else if activity was previously seen and `sample.settled` has been true for 3
  consecutive samples, publish `syncthing_complete`, then stop.

Precedence:

- Do not override `conflict`.
- Do not override `error`.
- Do not hide a failure toast.
- Syncthing complete may follow `has_backup`, `restored`, or `backed_up` success states.

### BrowserView Rendering

In `src/surfaces/autoSyncStatusSurface.tsx`:

- Add text labels for the three new statuses.
- Add inline SVGs:
  - cloud + down arrow;
  - cloud + up arrow;
  - cloud + checkmark.
- Keep existing BrowserView geometry, data URL rendering, delayed reveal, hide timers,
  reset behavior, and owner destruction semantics.
- Keep no external image/icon dependencies.

## Testing Strategy

Follow strict TDD.

### Backend Tests

Add focused backend tests, likely in a new `tests/test_syncthing.py` plus service/main
coverage where needed:

- Config discovery:
  - native config path candidate is parsed;
  - Flatpak config path candidate is parsed;
  - API URL is derived from GUI address;
  - API key never appears in logs or returned dicts.

- Folder resolution:
  - valid Ludusavi `backupPath` resolves to the deepest containing Syncthing folder;
  - `backupPath == "unknown"` returns `backup_path_unavailable`;
  - no containing folder returns `folder_not_found`;
  - unreachable API returns `syncthing_not_running` or `api_unavailable`.

- Activity computation:
  - local download maps to `downloading=true`;
  - remote download progress maps to `uploading=true`;
  - scan/index/sequence/need counters map to `update_in_progress=true`;
  - idle folder maps to `settled=true`;
  - pending remote ack alone does not prevent settled behavior.

- Watch manager:
  - start returns `watching`;
  - poll returns latest sample;
  - stop removes the watch;
  - duplicate same phase/game/app replaces prior watch;
  - `stop_all` stops all active watches.

- Service/main:
  - `SDHLudusaviService` exposes start/poll/stop methods;
  - `Plugin` exposes RPC wrappers and delegates through `_call`;
  - `SDHLudusaviService.stop()` stops Syncthing watchers.

### Frontend Static Tests

Extend `tests/test_frontend_static.py`:

- Syncthing RPC callables exist in `src/api/ludusaviRpc.ts`.
- Syncthing types exist in `src/types/index.ts`.
- `createGameLifecycleController` receives Syncthing RPCs in `LifecycleRpc`.
- Pre-game lifecycle starts watch before `checkGameStartCall`.
- Post-game lifecycle starts watch before `checkGameExitCall`.
- Polling interval is cleared on completion, failure, skipped silent reasons, timeout,
  and controller dispose.
- Status mapping publishes:
  - `syncthing_downloading`;
  - `syncthing_uploading`;
  - `syncthing_complete`.
- BrowserView surface contains:
  - `SYNCTHING DOWNLOADING`;
  - `SYNCTHING UPLOADING`;
  - `SYNCTHING COMPLETE`;
  - cloud-down SVG;
  - cloud-up SVG;
  - cloud-check SVG.
- Existing BrowserView normalization, timers, reset, and destroy tests still pass.

## Validation

Focused checks:

```bash
./run.sh uv run pytest tests/test_syncthing.py tests/test_service.py tests/test_main.py tests/test_frontend_static.py
./run.sh pnpm run typecheck
./run.sh pnpm run build
```

Full validation before commit:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh bash scripts/check_tdd.sh
./run.sh pnpm run verify
git diff --check
```

If `pnpm verify` fails only at network-dependent `pnpm audit`, retry with approved
network access if available. If it remains blocked, report that exact gate separately
and do not claim the full suite is green.

Final review-fix loop gate:

```bash
npx @openai/codex review --base main
```

Fix every valid finding, rerun relevant validation, and repeat the review command until
there are no valid blocking findings.

## Documentation Requirements

Update docs if implementation changes user-visible behavior:

- `README.md`: mention that the status strip can show Syncthing activity when Syncthing
  is running and its folder contains Ludusavi's backup path.
- `docs/specs/custom_status_bar_ui.md`: add Syncthing statuses, icons, and display-only
  semantics.
- `docs/specs/sdh_ludusavi_sync.md`: document that Syncthing activity is advisory UI
  status and does not block autosync.
- `docs/agent_conversations/`: record implementation summary, files modified, tests
  added, decisions, and validation results.

## Explicit Non-Goals

- Do not block game launch or exit waiting for Syncthing.
- Do not add user-facing Syncthing settings.
- Do not monitor manual force backup/restore in v1.
- Do not expose Syncthing API keys.
- Do not add third-party dependencies.
- Do not use `/tmp/sdh_ludusavi/syncthing_folder_activity.py` as a packaged runtime file.
- Do not replace the BrowserView status strip with a separate UI surface.

## Acceptance Criteria

- During automatic pre-game and post-game lifecycle flow, if Syncthing is running and
  the Ludusavi backup path belongs to a Syncthing folder, the status strip reflects
  folder activity.
- Download/local-pull activity shows a cloud-down status.
- Upload/remote-pull activity shows a cloud-up status.
- Settled-after-activity shows a cloud-check status.
- If Syncthing is absent or unavailable, autosync behavior remains unchanged.
- Conflict and error states still take precedence over Syncthing states.
- BrowserView teardown remains idempotent on plugin unload.
- All required focused/full validation gates pass, or external-network blockers are
  reported precisely.
