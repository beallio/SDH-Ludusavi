# Implementation Plan: Game Dropdown Truncation & Code Review Refinements

This plan outlines the changes required to address the latest code review findings and complete the feature implementation to prevent games dropdown expansion.

## Problem Definition
1. **Dropdown Expansion**: Dropdown button expands when a game name is long, instead of truncating.
2. **ES Module Style Element Leak/Cache**: Static stylesheet is evaluated once at module scope but removed on unmount. On subsequent mount/dismounts, the style tag is not re-appended, breaking layout.
3. **Queue Lifetime Closure Mismatch**: settings queue enqueued async tasks capture component-scoped callbacks (`applySettings` and `setBusyLabel`), creating memory leaks when `Content` unmounts.
4. **Mount Guard Cache Desync**: `lastPersisted` cache updates are guarded by `isMounted.current`, causing updates resolving after unmount to fail to save, resulting in stale settings rollbacks.
5. **Manual Refresh Failure User Feedback**: Manual refresh failures returning `RpcStatus` are logged but not shown to the user via notification toasts.

## Proposed Changes

### `src/index.tsx`
1. **Injected Stylesheet Refactor**:
   - Keep the static styles definition `dropdownStyleEl` in the module scope (or instantiating it once).
   - Inject it once into `document.head` in `definePlugin` (initialization path).
   - Remove it from `document.head` in the plugin's `onDismount` path.
   - Completely remove the programmatic DOM manipulation from `Content`'s `useEffect` hooks to prevent StrictMode concurrency layout bugs.

2. **Global Helper for Settings Updates**:
   - Extract `applySettings` out of `Content` into a module-scoped function `applySettingsGlobal(store: LudusaviStateStore, nextSettings: Settings)` that applies settings to the store and updates module-scoped `lastPersisted` cache variables.
   - This eliminates closure captures of component callbacks inside enqueued settings queue tasks.

3. **Decouple Queue Tasks from Component UI State**:
   - Remove all `setBusyLabel` and `isMounted.current` calls from enqueued async tasks inside `toggleAutoSync`, `toggleNotificationSetting`, and `onGameChange`.
   - The settings queue already publishes busy status through the `subscribeQueue` mechanism to toggle component `queueBusy` state, disabling the UI.

4. **Cache Updates Mount Guard Removal**:
   - Remove `isMounted.current` checks around the updates to `lastPersistedAutoSync`, `lastPersistedNotifications`, and `lastPersistedSelectedGame`. They are updated immediately upon RPC success regardless of component mount state.

5. **Manual Refresh Failure Notifications**:
   - Update `refreshGames` to check if `applyRefreshResult(result)` is false and `isRpcStatus(result)` is true, and display a user-facing failure toast using `notify(...)`.
   - Add a catch block handler to trigger a `notify(...)` call if the refresh promise rejects.

### `tests/test_frontend_static.py`
1. Update `test_frontend_settings_intermediate_success_updates_last_persisted` to match the sequence-unguarded cache updates.
2. Add `test_frontend_manual_refresh_failure_notification` to verify failure toasts on manual refresh errors.
3. Update `test_frontend_dropdown_truncation_styling` to match the `definePlugin` styling hook setup.

## Verification Plan

### Automated Tests
- Run backend and static validation tests:
  ```bash
  ./run.sh uv run pytest
  ```
- Run formatting and typecheck validation:
  ```bash
  ./run.sh uv run ruff check . --fix
  ./run.sh uv run ruff format .
  ./run.sh uv run ty check py_modules/sdh_ludusavi/
  pnpm run typecheck
  pnpm run build
  ```
