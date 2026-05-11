# Runtime Ludusavi Integration Fix

## Problem Definition

The Decky panel loads, but runtime calls do not appear to interface with Ludusavi and
the UI log panel does not show useful diagnostics. The backend currently initializes
the real Ludusavi adapter during service startup and the frontend fetches logs in
parallel with refresh, so dependency failures can happen before the service can expose
diagnostic log entries to the panel.

## Architecture Overview

The Python service remains the backend boundary for Ludusavi operations. Runtime
settings and status calls should work even when Ludusavi or Flatpak is unavailable.
The real Ludusavi adapter should be created lazily inside locked Ludusavi operations,
where failures can be returned as `dependency_error` and stored in recent logs. The
Decky plugin should run as the Decky user so the Ludusavi Flatpak sees the user's
Ludusavi configuration and backups.

## Core Data Structures

- `OperationState`: unchanged public status payload.
- `LogEntry`: continues to carry dependency and operation diagnostics.
- Settings JSON: unchanged `{"auto_sync_enabled": bool}`.
- `LudusaviAdapter` factory: internal service dependency used to delay real adapter
  construction until an operation needs it.

## Public Interfaces

No frontend callable names change. `refresh_games()` still returns
`{"games": list, "dependency_error": str | null}`. Manual operations and version lookup
keep their existing result payloads.

## Dependency Requirements

No new dependencies are required. Ludusavi still runs through the Flatpak ID
`com.github.mtkennerly.ludusavi`.

## Testing Strategy

Add tests proving settings access does not initialize Ludusavi, refresh reports adapter
initialization failures as dependency errors with log entries, package metadata no
longer requests root, and the frontend fetches recent logs after refresh during initial
load.
