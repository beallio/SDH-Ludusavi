# Review — autosync-handoff-and-logging (round 01)

Branch: `feat/autosync-handoff-and-logging`
Reviewed against: `docs/plans/2026-06-18_autosync-handoff-and-logging.md`

## Verdict

Workstreams A and B are correct and match the plan. Workstream C is functionally complete
and well-structured, but the `debug_logging` setting defaults to **OFF** everywhere, which
contradicts the plan's explicit requirement (default ON) and the confirmed product decision
("Config toggle, default ON"). There is also a spurious, unused `LudusaviSettings` interface
left in `src/types/index.ts`. Both must be fixed before approval.

What is correct (no action needed):
- **A** (`src/surfaces/autoSyncStatusSurface.tsx`): `HAS_BACKUP_MIN_DWELL_MS = 900`, single
  coalescing timer (last-write-wins) including `syncthing_complete`, `autoSyncStatusShownAt`
  set on every visible apply path, deferral cleared on `hide`/`dispose`. Tests cover dwell,
  coalescing, immediate non-syncthing apply, and hide-cancels-deferral.
- **B** (`src/controllers/syncthingMonitorMachine.ts`): `mutationObserved` added and
  initialized; completion armed from `mutationObserved && settled` (×3); the
  `pending_activity_timeout` `!activityObserved` guard correctly dropped so the timeout is a
  universal `has_backup` backstop. Post-game-only by construction.
- RPC/registration (`main.py`, `ludusaviRpc.ts`), settings persistence (`constants.py`,
  `service.py` `get_settings`/`_save_state`), the UI toggle, hydration, README, and the
  logging level routing (`log_buffer.py`: debug→`logger.debug`; `setup_logging` raising
  `decky.logger` to DEBUG; `service._apply_log_level`) are all correct.

## Gate status

Pre-commit hooks ran the full quality gates on each commit and passed (backend ruff/ty/pytest,
frontend supply-chain/build/test:unit/typecheck, packaging). No gate concerns. The required
changes below must re-pass all gates.

## Required changes

### 1. `debug_logging` must default to ON (True), not OFF

Change every default for `debug_logging` from `False`/`false` to `True`/`true`:

Backend:
- `main.py` `DeckySettingsStore.read()`: `self._manager.getSetting("debug_logging", False)` →
  `..., True)`.
- `py_modules/sdh_ludusavi/service.py` `__init__`: `self._debug_logging = False` → `True`.
- `py_modules/sdh_ludusavi/service.py` `_load_state`:
  `bool(settings.get("debug_logging", False))` → `..., True))`.

Frontend:
- `src/state/ludusaviState.tsx` `defaultSettings()`: `debug_logging: false` → `true`.
- `src/state/ludusaviState.tsx` `normalizeSettings()`: the
  `typeof settings.debug_logging === "boolean" ? settings.debug_logging : false` fallback →
  `: true`.
- `src/settings/settingsMutationRuntime.ts` `toggleDebugLogging`:
  `fallbackValue: lastPersistedDebugLogging ?? false` → `?? true`.

Tests (update fixtures/expectations to the new default so they assert ON, not OFF):
- `tests/test_service.py`: `expected_settings(..., debug_logging: bool = False)` →
  default `True`; and the two literal persisted-settings dicts that hard-code
  `"debug_logging": False` → `True`. Verify `test_settings_do_not_initialize_ludusavi_adapter`
  still holds with the new default.
- `src/runtime/startupHydration.test.ts`: the `SETTINGS` fixture `debug_logging: false` →
  `true` (or keep a non-default value only if the test specifically exercises a persisted
  override — but the default-state fixtures must reflect ON).

Confirm after the change: a fresh install with no persisted setting yields `debug_logging:
true`, `get_settings()` returns it `true`, and `_apply_log_level()` sets `decky.logger` to
DEBUG on load (consistent with `setup_logging` already defaulting to DEBUG at startup).

### 2. Remove the unused `LudusaviSettings` interface

`src/types/index.ts` adds an `export interface LudusaviSettings { ... };` that is referenced
nowhere (confirmed: the only occurrence is its own declaration) and duplicates the `Settings`
type. Remove the entire interface. The canonical `debug_logging` addition to the `Settings`
type is correct and stays.

## Notes (non-blocking, do not require a fix)

- In `syncthingMonitorMachine.ts` the new `postGameMutation` expression is identical to the
  pre-game branch of `hasActivity`. Leaving the duplication is acceptable; only consider
  extracting a shared helper if it reads cleaner to you. Not required.

STATUS: CHANGES_REQUESTED
