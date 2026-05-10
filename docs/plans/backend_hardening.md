# Backend Hardening

## Problem Definition

Decky RPC methods currently call Ludusavi-backed service methods directly from async
plugin entry points. Those calls can block the Decky event loop while Ludusavi or
subprocess work is running. Runtime state is also loaded with raw JSON parsing, so an
empty, corrupt, unreadable, or non-object state file can prevent the backend from
loading. The state file path should live in Decky/plugin-owned settings space when
available, not in `/tmp`.

## Architecture Overview

`main.Plugin` remains the Decky RPC boundary. Blocking service callbacks are offloaded
to a background worker thread inside `_call`, preserving existing public RPC method
names and payloads. `SDHLudusaviService` remains the stateful backend, with a
process-local threading lock guarding the single global Ludusavi operation. State path
selection is kept in the Decky boundary because it depends on Decky runtime paths.

## Core Data Structures

- `OperationState`: unchanged public operation status payload.
- Settings JSON: unchanged persisted schema of `{"auto_sync_enabled": bool}`.
- State path: `sdh_ludusavi.json` in `DECKY_SETTINGS_DIR` when present, otherwise a
  private user config fallback under `.config/sdh-ludusavi/`.

## Public Interfaces

No frontend API names or service return payloads change. `OperationLockedError` still
maps to `{"status": "skipped", "reason": "operation_running", ...}` at the Decky
boundary, and unexpected exceptions still map to `{"status": "failed", ...}`.

## Dependency Requirements

No new runtime dependencies are required. The implementation uses Python standard
library modules only: `asyncio`, `logging`, `threading`, and `pathlib`.

## Testing Strategy

Add backend boundary tests for event-loop offloading, exception payload preservation,
Decky settings path selection, and private fallback storage. Extend service tests for
invalid state files, unchanged saved settings schema, and threaded operation locking.
Extend Ludusavi adapter tests to pin conservative recency behavior until Ludusavi output
directly proves backup data is newer than local saves.
