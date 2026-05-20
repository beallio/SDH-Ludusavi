# Launch-Gated Backup Conflict Resolution

## Problem Definition

Game-start restore currently runs after Steam reports the app as running. That
means a game can begin reading local save files while SDH-ludusavi is restoring a
newer Ludusavi backup. Ambiguous recency is also skipped without giving the user a
choice. The plugin needs a launch gate that pauses the started game process,
resolves the backup decision, and always resumes the process.

## Architecture Overview

- Use `RegisterForAppLifetimeNotifications` as the lifecycle trigger and treat
  `nInstanceID` as the game process PID, following Decky Cloud Save and
  SDH-GameSync.
- Add backend RPCs to send `SIGSTOP` and `SIGCONT` recursively to the process
  tree.
- Keep Ludusavi orchestration in `SDHLudusaviService`; do not modify upstream
  `pyludusavi`.
- Add conflict metadata to the start check and a dedicated resolution RPC.
- Update user-facing copy to say "Backup Save" instead of "Cloud Save".

## Core Data Structures

- `LifecycleCheckResult.status` adds `conflict`.
- Conflict payload includes `game`, `reason`, `localModifiedAt`,
  `backupModifiedAt`, `localLabel`, and `backupLabel`.
- Conflict resolution accepts `keep_local` or `restore_backup`.
- Versions payload adds `decky`.

## Public Interfaces

- `pause_game_process(pid: int) -> dict[str, object]`
- `resume_game_process(pid: int) -> dict[str, object]`
- `resolve_game_start_conflict(game_name: str, app_id: str | None, resolution: str)`
- `get_versions()` includes `decky`.

## Dependency Requirements

No new dependencies. Process signaling uses Python standard library modules:
`os`, `signal`, and `subprocess`.

## Testing Strategy

- Backend tests cover recursive pause/resume, unload resume, conflict metadata,
  resolution behavior, diagnostics logging, and Decky version.
- Main RPC tests cover new RPC exposure and unload safety.
- Frontend static tests cover PID-aware lifecycle start, pause before checks,
  resume in `finally`, conflict modal copy, and absence of "Cloud Save".
- Diagram tests cover the standalone launch gate flow HTML.
- Full validation runs through `./run.sh`.
