# Auto-Sync Status Handoff and Debug Logging Fixes

## Plan Metadata

```text
TITLE=Auto-Sync Status Handoff and Debug Logging Fixes
SLUG=autosync-handoff-and-logging
PLAN_PATH=docs/plans/2026-06-18_autosync-handoff-and-logging.md
BRANCH=feat/autosync-handoff-and-logging
```

---

## Context

An on-device log review (`/tmp/sdh_ludusavi/steamdeck-logs/2026-06-18 10.36.00.log`) surfaced
three independent issues in the auto-sync status surface and logging. None is a data-integrity
bug; all three are UX/diagnostics correctness problems.

1. **`has_backup` flashes for ~1 ms.** On game exit the "GAME SAVE UP TO DATE" status is
   published, then overwritten by a Syncthing status within 1 ms (log `11:01:16,318` →
   `,319`), so the intended beat is never visible and a BrowserView render + auto-hide timer
   are wasted. The desired visible exit progression is
   `BACKING UP LOCAL SAVE → GAME SAVE UP TO DATE → SYNCTHING PREPARING → (SYNCTHING UPLOADING) → SYNCTHING COMPLETE`.

2. **Post-game Syncthing stalls at PREPARING then times out.** The watch state machine only
   treats a sample as activity when `sample.uploading` is true, and only counts `settled`
   samples toward completion after activity was observed. A small save (~197 KB) syncs in a
   sub-second burst that produces no qualifying `uploading` sample, so the machine sits in
   `syncthing_pending_upload` for the full 30 s detection grace and times out to `has_backup`,
   never showing `COMPLETE`.

3. **Debug logs are indistinguishable from info, with no verbosity control.** Debug records
   are routed through `logger.info` (so everything shows as `[INFO]`), and `decky.logger` sits
   at INFO so switching to `logger.debug` would suppress them. There is no runtime toggle.

Intended outcome: a visible `GAME SAVE UP TO DATE` beat; reliable `PREPARING → COMPLETE` for
small saves; real `[DEBUG]` tags with a persisted, default-ON `debug_logging` toggle.

---

## Execution Rules (read first)

- Use the `implementer` skill for all implementation.
- Develop on branch `feat/autosync-handoff-and-logging`, created off `dev`. Do not commit to
  `dev` directly until finalization.
- This plan is your only instruction source. Do not write your own review. Do not create or
  delete files under `docs/review/`.
- Follow the repo protocol in `CLAUDE.md`: strict TDD (failing test first for each
  behavior change), conventional commits, caches under `/tmp/sdh_ludusavi`, all project
  commands through `./run.sh`.
- Record a session log under `docs/agent_conversations/` after implementation.
- Steam Deck / user testing is deferred until after the dev push to GitHub.

### Combine vs. separate (commit boundaries)

The three workstreams are independent and must be **separate commits**, implemented in order
A → B → C. Within each workstream, combine the test + implementation + any doc update into
that workstream's single logical change (still TDD: commit only after the gate passes).

- **A** touches only `src/surfaces/autoSyncStatusSurface.tsx` (+ its tests). Self-contained.
- **B** touches only `src/controllers/syncthingMonitorMachine.ts` (+ machine/monitor tests).
  Self-contained. Do **not** entangle B with A — they touch different files and have
  independent tests.
- **C** spans backend + frontend, but it is one coherent feature (configurable debug logging)
  and must land as **one commit** because the backend RPC, settings key, and frontend toggle
  are useless individually. Do not split C across commits.

Commit messages:
1. `fix(autosync): give has_backup a minimum visible dwell before syncthing handoff`
2. `fix(syncthing): complete post-game watch via settle-after-mutation`
3. `feat(logging): real debug level tags + configurable debug_logging toggle`

---

## Workstream A — `has_backup` minimum dwell (surface-owned)

### Files
- Modify: `src/surfaces/autoSyncStatusSurface.tsx`
- Tests: `src/surfaces/autoSyncStatusSurface.test.ts` (add cases)

### Why the surface, not the controller
`createAutoSyncStatusSurface` owns `currentAutoSyncStatusState` and is the single point that
applies status to the BrowserView. The machine (Workstream B) publishes `syncthing_*` statuses
asynchronously via `publishAutoSyncStatus`. If the dwell were enforced in
`gameLifecycleController.tsx`, an early machine-published `syncthing_uploading` could be
downgraded back to `syncthing_pending_upload` by a late controller publish. Enforcing the
dwell in the surface lets it **coalesce** all `syncthing_*` publishes that arrive during the
dwell and apply only the most recent one when the dwell elapses.

### Behavior to implement
Add `export const HAS_BACKUP_MIN_DWELL_MS = 900;` near
`RESULT_HIDE_DELAY_MS` (currently `autoSyncStatusSurface.tsx:16`).

Add surface-local state inside `createAutoSyncStatusSurface`:
- `let autoSyncStatusShownAt: number | null = null;` — set to `Date.now()` whenever a
  **visible** status is actually applied to the view (in the `publish` apply path and in the
  deferred-apply path).
- `let deferredAutoSyncStatusState: AutoSyncStatusState | null = null;`
- `let deferredAutoSyncStatusTimeoutID: number | null = null;`
- A `clearDeferredAutoSyncStatus()` helper that clears the timeout and nulls both.

Define a predicate for the statuses that must wait behind a fresh `has_backup`:
```ts
function isSyncthingStatus(status: AutoSyncStatusKind): boolean {
  return status === "syncthing_pending_upload"
    || status === "syncthing_uploading"
    || status === "syncthing_downloading"
    || status === "syncthing_complete";
}
```
(There is already `isSyncthingActiveStatus` in `autoSyncStatusRenderer.tsx` but it excludes
`syncthing_complete`; do not reuse it here — completion must also wait behind the dwell. Add
the local predicate above, or export a new shared one if cleaner.)

In `api.publish(status, options)` (currently `autoSyncStatusSurface.tsx:126`), before the
existing apply logic:
- If `isSyncthingStatus(status)` AND `currentAutoSyncStatusState.status === "has_backup"` AND
  `currentAutoSyncStatusState.visible` AND `autoSyncStatusShownAt !== null` AND
  `Date.now() - autoSyncStatusShownAt < HAS_BACKUP_MIN_DWELL_MS`:
  - Build the new state object (same shape the normal path builds) and store it in
    `deferredAutoSyncStatusState` (overwriting any previous deferred state — last wins).
  - If no `deferredAutoSyncStatusTimeoutID` is pending, schedule one for the remaining time
    `HAS_BACKUP_MIN_DWELL_MS - (Date.now() - autoSyncStatusShownAt)`. On fire: apply
    `deferredAutoSyncStatusState` (set `currentAutoSyncStatusState`, `setContext`, log via
    `logAutoSyncStatusChange`, `statusView.sync`, `scheduleAutoSyncStatusHide`, set
    `autoSyncStatusShownAt = Date.now()`), then clear deferred state/timer. Do **not**
    reschedule per publish; keep the single timer and just update the deferred target.
  - Return early (do not apply immediately).
- Otherwise (non-syncthing status, or `has_backup` already dwelled, or current status is not
  `has_backup`): call `clearDeferredAutoSyncStatus()` and proceed with the existing apply
  logic. Set `autoSyncStatusShownAt = Date.now()` when a visible status is applied.

In `api.hide(...)` (currently `:157`) and `api.dispose()` (`:252`): call
`clearDeferredAutoSyncStatus()` so a pending deferral never applies after hide/teardown.

Preserve the existing `shouldResetSurface` / deferred-sync (`syncAutoSyncStatusBrowserViewDeferred`)
behavior — the new dwell deferral is a separate mechanism layered before it.

### Tests (write first, must fail before implementation)
In `src/surfaces/autoSyncStatusSurface.test.ts` use vitest fake timers (`vi.useFakeTimers()`):
1. Publish `has_backup` (visible), then publish `syncthing_pending_upload`: assert the view's
   synced status is still `has_backup` immediately after; advance timers by
   `HAS_BACKUP_MIN_DWELL_MS`; assert `syncthing_pending_upload` is now synced.
2. During the dwell, publish `syncthing_pending_upload` then `syncthing_uploading`; advance to
   dwell end; assert only `syncthing_uploading` was applied (coalescing — `syncthing_pending_upload`
   never synced to the view).
3. During the dwell, publish `error`; assert it applies immediately and the deferral is
   cancelled (advancing timers does not later apply a stale syncthing status).
4. `hide()` during a pending deferral: advance timers; assert no late apply occurs.
5. Regression: `has_backup` published with no following `syncthing_*` syncs immediately and
   auto-hides after `RESULT_HIDE_DELAY_MS` (existing behavior intact). Confirm
   `autoSyncStatusSurface.suppression.test.ts` still passes unchanged.

### Verification
`pnpm run test:unit` (or `npx vitest run src/surfaces/autoSyncStatusSurface`) green;
`pnpm run typecheck` clean.

### Risks
- Coalescing means very fast `pending → uploading → complete` within 900 ms collapses to the
  final status (the intermediates are too brief to see anyway) — acceptable and intended.
- Ensure the deferred timer is cleared on `hide`/`dispose` to avoid applying a status after the
  strip is hidden. Covered by tests 3–4.

---

## Workstream B — post-game completion via settle-after-mutation

### Files
- Modify: `src/controllers/syncthingMonitorMachine.ts`
- Tests: `src/controllers/syncthingMonitorMachine.test.ts` (add cases); confirm
  `src/controllers/syncthingMonitor.activity.test.ts`,
  `syncthingMonitor.failures.test.ts`, `syncthingMonitor.initialization.test.ts`,
  `syncthingMonitor.handoffCleanup.test.ts` stay green.

### State change
Add `mutationObserved: boolean` to `WatchMachineState` (`syncthingMonitorMachine.ts:7`) and
initialize `mutationObserved: false` in `createInitialWatchState` (`:57`).

### Transition changes (all inside the `"sample"` case, `:133`, and `"pending_activity_timeout"`, `:289`)
Keep `activityObserved` meaning a real observed `uploading` sample (still drives the
`SYNCTHING UPLOADING` display and the `syncthingMonitor.ts:441` "upload activity observed" log).

1. Compute a post-game mutation signal and set the new flag:
```ts
const postGameMutation =
  sample.uploading ||
  sample.update_in_progress ||
  sample.status === "ACTIVE_TRANSFER" ||
  sample.status === "SCANNING" ||
  sample.status === "UPDATE_NEEDED" ||
  sample.status === "PREPARING" ||
  sample.status === "INDEXING_OR_SEQUENCE_UPDATE";
if (state.phase === "post_game" && postGameMutation && !state.mutationObserved) {
  nextState.mutationObserved = true;
}
```
   Place this after the existing `hasActivity` computation and the
   `lastProcessedTimestamp`/dedupe guard (`:154-159`), so only fresh samples set it.

2. Arm completion from `mutationObserved` instead of `activityObserved`. Change the settle
   branch (currently `:187` `else if (nextState.activityObserved && sample.settled)`) to:
```ts
} else if (nextState.mutationObserved && sample.settled) {
  nextState.settledCount++;
  if (nextState.settledCount >= 3) {
    newStatus = "complete";
    nextState.completionObserved = true;
    nextState.step = "complete";
  }
}
```
   Leave the `sample.uploading` and `downloading` branches above it unchanged so a real
   transfer still maps to `uploading`/`downloading` first.

3. Universal timeout backstop. In the `"pending_activity_timeout"` case (`:289`) drop the
   `!state.activityObserved` condition so it fires whenever the watch is neither complete nor
   cancelled:
```ts
case "pending_activity_timeout": {
  if (state.publicationEnabled && state.initialized && state.step !== "cancelled") {
    nextState.step = "cancelled";
    nextState.publicationEnabled = false;
    effects = { ...effects, publish: { status: "has_backup", source: "timeout" }, stopWatch: true };
  }
  break;
}
```
   (Keep `state.initialized` so a never-initialized watch still no-ops.) This means a
   "mutation observed but never settled to complete within the grace" case resolves to
   `has_backup` at the 30 s deadline instead of running to the 120 s
   `MAX_WATCH_DURATION_MS` and surfacing `syncthing_unavailable`.

4. Do **not** clear the pending timer on mere `mutationObserved`. The existing
   `clearPendingTimer` on `uploading`/`complete` (`:214-216`) stays as-is. The 30 s grace
   remains armed as the backstop for the non-uploading path; reaching `complete` clears it via
   the existing `:214` path.

Do not alter pre-game (`phase !== "post_game"`) branches; `mutationObserved` is only read in
post-game logic. The pending timer is only ever scheduled in the post-game handoff path
(`handoff_confirmed`, `:278`), so the timeout change is post-game-only by construction.

### Resulting post-game outcomes (assert these intentions)
- Small save synced fast (scanning/indexing then settle, no `uploading` caught): `PREPARING` →
  `COMPLETE`.
- Real sustained upload caught: `PREPARING` → `UPLOADING` → `COMPLETE`.
- Nothing to sync / detection fully missed: `PREPARING` → (grace) → `UP TO DATE`.
- Peer offline / API failure: existing `poll_failed` actionable terminals (unchanged).

### Tests (write first, must fail before implementation)
In `src/controllers/syncthingMonitorMachine.test.ts`:
1. Post-game watch_allocated → handoff_confirmed (outcome pending) → samples
   `{status:"SCANNING", settled:false, uploading:false}` then three
   `{status:"IDLE", settled:true}` samples (distinct `timestamp_unix` each): assert final
   `step === "complete"`, `completionObserved === true`, and a `syncthing_complete` publish
   with `stopWatch` effect.
2. Post-game: a single `{uploading:true}` sample sets `activityObserved`, publishes
   `syncthing_uploading`, and yields `clearPendingTimer` (existing behavior preserved).
3. Post-game `pending_activity_timeout` after `mutationObserved` (scanning seen) but no settle:
   publishes `{status:"has_backup", source:"timeout"}` with `stopWatch`. Also assert the
   no-mutation case still publishes `has_backup` on timeout.
4. Baseline before any mutation: `{status:"IDLE", settled:true}` samples at watch start do
   **not** increment `settledCount` toward completion (no false completion).
5. Pre-game regression: existing pre-game tests in the machine and monitor suites pass
   unchanged.

### Verification
`npx vitest run src/controllers/syncthingMonitorMachine src/controllers/syncthingMonitor` green;
`pnpm run typecheck` clean.

### Risks
- Setting `mutationObserved` from broad signals could in theory arm completion from unrelated
  folder scans; acceptable because this only runs post-game immediately after our own backup,
  and completion still requires the folder to reach `settled` ×3. Test 4 guards the baseline.
- `SyncthingActivitySample` must expose the fields referenced (`status`, `update_in_progress`,
  `settled`, `uploading`, `downloading`, `timestamp_unix`). Confirm against the type in
  `src/types/index.ts` and `_serialize_sample` in
  `py_modules/sdh_ludusavi/syncthing/activity.py:168` — they already match; do not change the
  serialized shape.

---

## Workstream C — real debug tags + configurable `debug_logging` (one commit)

### Backend files
- `py_modules/sdh_ludusavi/log_buffer.py`
- `py_modules/sdh_ludusavi/constants.py`
- `py_modules/sdh_ludusavi/service.py`
- Tests: `tests/` (add/extend; match existing test module naming for log_buffer/service)

### Frontend files
- `src/api/ludusaviRpc.ts`
- `src/types/index.ts`
- `src/state/ludusaviState.tsx`
- `src/settings/settingsMutationRuntime.ts`
- A settings UI section (see below)
- `src/runtime/startupHydration.ts` (optional log field only)
- Tests: extend the existing settings-mutation / hydration / store test suites.

### Backend changes
1. `log_buffer.py` `_decky_log_fallback` (`:60`): change the level map so debug emits a real
   debug record:
```python
logger_level_map = {
    "warning": getattr(logger, "warning", logger.info),
    "error": getattr(logger, "error", getattr(logger, "exception", logger.info)),
    "debug": getattr(logger, "debug", logger.info),
    "info": getattr(logger, "info", None),
}
```
2. `log_buffer.py` `setup_logging` (`:119`): after configuring the stdlib loggers, raise the
   decky logger level so debug records are not filtered:
```python
try:
    import decky
    decky_logger = getattr(decky, "logger", None)
    if decky_logger is not None:
        decky_logger.setLevel(logging.DEBUG)
except ImportError:
    pass
```
   This runs at `init` before settings hydrate, so it is the startup default (matches
   `debug_logging` default ON). Keep the `push_log_record` ring buffer storing the true level
   (unchanged) so the in-plugin Log modal is unaffected.
3. `constants.py`: add `"debug_logging"` to `SETTINGS_KEYS` (`:12`).
4. `service.py`:
   - Add `self._debug_logging = True` in `__init__` near the other settings defaults (`:41`).
   - In `_load_state` (`:327`): `self._debug_logging = bool(settings.get("debug_logging", True))`
     and apply it once (see helper below) at the end of load.
   - In `get_settings` (`:189`): add `"debug_logging": self._debug_logging`.
   - In `_save_state` settings payload (`:354`): add `"debug_logging": self._debug_logging`.
   - Add `set_debug_logging(self, enabled: bool) -> dict[str, Any]` mirroring
     `set_auto_sync_enabled` (`:202`): set the field, `self._save_state()`, apply the level,
     log at info, return `self.get_settings()`.
   - Add a private helper `_apply_log_level(self) -> None` that imports `decky`, gets
     `decky.logger`, and calls `setLevel(logging.DEBUG if self._debug_logging else logging.INFO)`
     (guard `ImportError`/missing logger). Call it from `_load_state` and `set_debug_logging`.
   - Ensure `set_debug_logging` is registered the same way other RPC methods are exposed to the
     frontend (confirm how `set_auto_sync_enabled` is wired into the decky plugin entry —
     check the `Plugin`/`main.py` RPC surface and mirror it).

### Frontend changes (mirror `automatic_update_checks` exactly)
1. `src/types/index.ts`: add `debug_logging: boolean;` to the `Settings` type (`:43`) and to
   the hydrated settings type around `:252` if it is a separate shape.
2. `src/api/ludusaviRpc.ts`: add
   `export const setDebugLogging = callable<[enabled: boolean], RpcResult<Settings>>("set_debug_logging");`
   (mirror `setAutoSyncEnabled` at `:28`).
3. `src/state/ludusaviState.tsx`: add `setDebugLogging(enabled: boolean)` setter mirroring
   `setAutomaticUpdateChecks` (`:180`); ensure `applySettings` (`:125`) carries `debug_logging`.
4. `src/settings/settingsMutationRuntime.ts`: add a `toggleDebugLogging(enabled)` using
   `mutateSetting` exactly like `toggleAutomaticUpdateChecks` (`:314`): `settingKey:
   "debug_logging"`, `rpcCall: () => setDebugLogging(enabled)`,
   `optimisticUpdate`/`rollbackUpdate` via the new store setter, `getPersistedValue: (res) =>
   res.debug_logging`, with its own sequence counter and `lastPersistedDebugLogging` fallback
   (default `true`). Export it the same way the other toggles are exposed.
5. Settings UI: add a "Verbose (debug) logging" `ToggleField` with a short description
   (e.g. "Records detailed [DEBUG] diagnostics in the Decky log."). Render it in the GLOBAL
   panel by extending `src/components/qam/AutoSyncSettingsSection.tsx` (add an
   `onToggleDebugLogging` prop + `debug_logging` from `settings`), and wire the handler through
   `src/components/qam/LudusaviContent.tsx` where the other toggles are connected to
   `settingsMutationRuntime`. (If the update toggles live in `PluginUpdateSection.tsx` and that
   reads cleaner, placing it there is acceptable — pick one, keep it consistent.)
6. `src/runtime/startupHydration.ts`: hydration already calls `deps.applySettings(settings)`
   (`:50`), so `debug_logging` flows through once it is in `Settings`. Optionally add
   `debug_logging: settings.debug_logging` to the `startup_settings_hydrated` log fields
   (`:54`).

### Tests (write first, must fail before implementation)
Backend (`./run.sh uv run pytest`):
- `_decky_log_fallback` routes a `"debug"` level to `logger.debug` (not `logger.info`); other
  levels unchanged. (Use a fake/stub logger object capturing calls.)
- `setup_logging` calls `decky.logger.setLevel(logging.DEBUG)` when decky is importable
  (inject/stub the decky logger).
- `service.set_debug_logging(False)` persists `debug_logging=False`, reflects it in
  `get_settings()`, and applies INFO via `_apply_log_level`; default `_load_state` yields
  `True` and applies DEBUG.

Frontend (`pnpm run test:unit`):
- Hydration/store test: `applySettings` carries `debug_logging`; `getSnapshot().settings.debug_logging`
  reflects it.
- Settings-mutation test: `toggleDebugLogging(false)` performs optimistic update + RPC and
  applies the returned settings, mirroring the `toggleAutomaticUpdateChecks` test.

### Verification
Backend gates green (below). `pnpm run test:unit` and `pnpm run typecheck` green. On a manual
read, `get_settings()` includes `debug_logging`, the toggle renders, and flipping it OFF would
call `set_debug_logging(false)`.

### Risks
- Early-init logs (before hydration) always use the startup default (DEBUG). This is intended;
  document it in the toggle description if helpful.
- The `debug` flag in `plugin.json` is unrelated (Decky hot-reload, stripped from release by
  `scripts/package_plugin.py`). Do not touch it.
- Confirm the RPC registration mechanism for `set_debug_logging` matches how existing setters
  are exposed; an unregistered callable will fail silently from the frontend.

---

## Quality Gates (run for every round, via `./run.sh`)

Backend:
```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```
Frontend:
```bash
pnpm run test:unit
pnpm run typecheck
```
All must pass. Keep caches under `/tmp/sdh_ludusavi`. Do not run broad formatting that touches
unrelated modified files (see `CLAUDE.md` §18).

Update `README.md` for the new settings toggle (usage change, Workstream C). Record a session
log in `docs/agent_conversations/` (date, objective, files modified, tests added, design
decisions, results).

---

## Orchestration Contract

Plan path:
```text
docs/plans/2026-06-18_autosync-handoff-and-logging.md
```
Implementation branch:
```text
feat/autosync-handoff-and-logging
```
Round-complete marker:
```text
/tmp/sdh_ludusavi/autosync-handoff-and-logging_finished
```
Finalized marker:
```text
/tmp/sdh_ludusavi/autosync-handoff-and-logging_finalized
```
Review notes:
```text
docs/review/autosync-handoff-and-logging-review-*.md
```
Each review note ends with exactly one of `STATUS: CHANGES_REQUESTED` or `STATUS: APPROVED`.

### On completing an implementation/review round
1. Run the quality gates.
2. Ensure the working tree is clean.
3. Commit all relevant changes.
4. Write the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished autosync-handoff-and-logging
   ```
Then either keep polling `docs/review/autosync-handoff-and-logging-review-*.md` or exit
cleanly. On every resume, scan existing review notes **before** waiting for new file events.

### When a review note has `STATUS: CHANGES_REQUESTED`
1. Clear the marker: `scripts/orchestration/clear-finished autosync-handoff-and-logging`
2. Read the review note.
3. Implement every requested change.
4. Run quality gates.
5. Commit the fixes.
6. Commit the review note if not already committed.
7. Recreate the marker: `scripts/orchestration/mark-finished autosync-handoff-and-logging`
8. Continue polling or exit cleanly.

### When a review note has `STATUS: APPROVED`
1. Confirm all review notes are committed.
2. Confirm the working tree is clean.
3. Finalize: `scripts/orchestration/finalize autosync-handoff-and-logging`
4. Confirm `/tmp/sdh_ludusavi/autosync-handoff-and-logging_finalized` exists.
5. Stop polling and exit cleanly.

Finalization includes: commit any uncommitted review note; merge the working branch into
`dev`; clean up the working branch; push `dev` to GitHub; request/push a new dev release via
the project release script (`./scripts/request_dev_release.sh`). Steam Deck/user testing is
deferred until after the dev push.

> Review notes are durable audit records and must be committed. The implementer must not write
> its own review and must not create or delete files under `docs/review/`.
