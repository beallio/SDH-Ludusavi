# Implementation Plan: Align Backend Error Responses with Frontend Type Expectations

## Problem Definition
The `Plugin._call` method in `main.py` catches exceptions (like `OperationLockedError`) and returns dictionaries such as `{"status": "skipped", "reason": "operation_running", "message": "..."}` or `{"status": "failed", "message": "..."}`.
However, the frontend `src/index.tsx` expects methods like `refresh_games` to return `RefreshResult` and `get_settings` to return `Settings`. If a backend call is blocked by the lock, the frontend receives a status dictionary instead of the typed data, bypassing TypeScript's safety and potentially causing runtime errors in the UI if it attempts to access properties that don't exist.

## Architecture Overview
The frontend needs a robust way to handle these RPC error/status dictionaries.
1. Create a generic union type `RpcResult<T>` in `src/index.tsx` (or `src/types.d.ts`).
   `type RpcResult<T> = T | { status: "skipped" | "failed"; reason?: string; message?: string; };`
2. Update the `callable` definitions in `src/index.tsx` to reflect this possibility for methods that are routed through `_call` in the backend.
   - Note: Not all methods use `_call`. For example, `get_settings` does NOT use `_call` and directly returns data. `refresh_games`, `handle_game_start`, `handle_game_exit`, `force_backup`, `force_restore`, `get_versions` DO use `_call`.
3. Update the frontend handlers (e.g., `refreshGames`, `loadInitial`) to check for the `status` property. If the result is a skipped/failed object, handle it gracefully (e.g., show a toast, or simply ignore if `skipped`) rather than treating it as a successful data payload.

## Core Data Structures
- TypeScript generic type:
  ```typescript
  type RpcResult<T> = T | { status: "skipped" | "failed"; reason?: string; message?: string; };
  ```

## Public Interfaces
- `src/index.tsx`: Update generic type arguments for `callable` declarations that rely on `_call`.

## Dependency Requirements
- None.

## Testing Strategy
- Run frontend type checking: `pnpm run typecheck`
- Verify that standard flows (loading, refreshing, launching) compile without TS errors.
- Ensure that if `refreshGamesCall` returns a `skipped` object, the UI doesn't crash trying to access `.games`.
