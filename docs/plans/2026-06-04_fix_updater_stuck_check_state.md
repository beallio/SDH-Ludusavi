# Fix Updater `Checking...` Latch After Successful Dev Release Install

## Summary

The dev release install itself succeeds. The bug is that `PluginUpdateSection` can keep a
stale update-check promise alive during Decky's install handoff/reload window. That leaves
local frontend state stuck with `isChecking=true`, so the Status row shows `Checking...` and
`Check now` stays disabled until the user navigates away and the React component remounts.

Fix this as a frontend updater state-machine issue. Do not treat the install as failed, do
not alter Decky installer behavior, and do not change backend pending-install reconciliation.

## Handoff Context

Start by reading `AGENTS.md`, `.protocol`, and `run.sh`. Confirm:

- Temp/caches: `/tmp/sdh_ludusavi`
- Command wrapper: `./run.sh`
- Type checker: `ty`
- Project mode repo with Python backend, TypeScript frontend, and tests

Current relevant files:

- `src/components/PluginUpdateSection.tsx`: owns `isChecking`, `inFlightCheck`,
  `checkForUpdates`, install handoff UI, `installedOverride`, pending install hydration, and
  the `Check now` button.
- `tests/test_frontend_static.py`: primary regression fence for updater UI behavior.
- `py_modules/sdh_ludusavi/updater.py` and `main.py`: backend updater/reconciliation logic.
  These should remain behaviorally unchanged unless tests prove otherwise.

Current behavior to preserve:

- Successful handoff sets optimistic installed state via `installedOverride`.
- `effectiveCurrentVersion = installedOverride?.version ?? currentVersion`.
- Stale available candidates matching the effective/current installed version are coerced to
  current.
- Pending install metadata remains durable backend state and is reconciled on startup.
- Decky installer argument order and install type constants remain unchanged.

## Implementation Changes

Create branch `fix/updater-stuck-check-state`. Create/update this plan before code edits,
then follow strict TDD.

In `PluginUpdateSection.tsx`, add bounded update-check ownership:

- Define `const UPDATE_CHECK_UI_TIMEOUT_MS = 60000;`.
- Add refs:
  - `activeCheckId = useRef(0)` to identify the latest check attempt.
  - `checkTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)` to clear pending
    timers.
- Add helper `clearCheckTimeout()` that clears and nulls the timer.
- Add helper `finishCheck(checkId)` that only clears `isChecking` and
  `inFlightCheck.current` if `checkId === activeCheckId.current`.

Update `checkForUpdates`:

- When starting a new check, increment `activeCheckId.current` and capture `checkId`.
- Set `isChecking=true`, clear check interruption/error UI, and assign
  `inFlightCheck.current`.
- Start a UI timeout for `UPDATE_CHECK_UI_TIMEOUT_MS`.
- If the timeout fires and `checkId` is still active:
  - Set `isChecking=false`.
  - Set `inFlightCheck.current=null`.
  - Set a recoverable check message, e.g. `Update check interrupted. Check again.`
  - Set `checkResult` to a failed/interrupted result with
    `checked_at: new Date().toISOString()` and `message`.
  - Do not clear `candidate`.
  - Do not clear `installedOverride`.
  - Do not clear pending install metadata.
- When the RPC resolves/rejects later, ignore it unless `checkId` is still active. This
  prevents stale responses from overwriting newer install/hydration state.
- In `finally`, only clear timeout/checking state through the guarded helper.

Update successful install handoff handling:

- In `handleHandoffSuccess`, invalidate any active check by incrementing
  `activeCheckId.current`.
- Clear any pending check timeout.
- Set `inFlightCheck.current=null`.
- Set `isChecking=false`.
- Continue existing success behavior: confirm handoff, set `installedOverride`, set current
  `checkResult`, clear `candidate`, clear install state, clear errors, update parent version
  state, and show the existing success toast.

Update mount/context hydration:

- Ensure the initial automatic update check does not race ahead of `get_update_check_context`.
- Add local hydration completion state/ref, for example `contextHydrated`.
- `loadCache` sets hydration complete in `finally`.
- The mount/channel automatic check effect runs only after hydration completes.
- If `loadCache` sees a fresh confirmed `pending_update_install` where
  `ctx.effective_installed_version === pendingInstall.version`, hydrate the optimistic
  installed version and skip the initial automatic check for that mount. Manual `Check now`
  remains available.
- Do not skip future manual checks or channel-change forced checks.

Update display copy:

- Keep Status as `Checking...` only while `isChecking` is true.
- For a timed-out/interrupted check, show a check-specific recoverable status such as
  `Check interrupted`.
- Error/message copy must not say install failed. The install succeeded; only the check was
  interrupted.
- `Check now` must be enabled once the timeout clears `isChecking`, unless `isInstalling` is
  true.

No backend/public API changes:

- Do not change RPC names or return shapes.
- Do not change `record_update_install_requested`, `confirm_update_install_handoff`,
  `clear_pending_update_install`, or `reconcile_pending_update_install`.
- Do not change Decky installer arguments or install type constants.
- Do not add dependencies.

## Tests

Add failing assertions to `tests/test_frontend_static.py` before implementation:

- `PluginUpdateSection` defines `UPDATE_CHECK_UI_TIMEOUT_MS`.
- The component tracks active check ownership with a ref/generation counter.
- The update-check timeout clears `setIsChecking(false)`.
- The timeout clears `inFlightCheck.current = null`.
- The timeout sets check-specific interrupted/retry copy and does not use install-failure
  wording.
- Late update-check responses are guarded by the active check id before mutating UI state.
- `handleHandoffSuccess` invalidates active checks and clears `isChecking`.
- Context hydration completes before automatic checks can run.
- Pending install hydration skips the initial automatic background check while preserving
  manual `Check now`.

Keep existing updater tests passing:

- Post-install optimistic installed version.
- Stale available response coercion.
- Pending install hydration after reload.
- Parent Versions section update.
- Decky handoff timeout behavior.
- Spinner slot/button height stability.
- SHA-prefix-only logging.

## Validation

Focused red/green checks:

```bash
./run.sh uv run pytest tests/test_frontend_static.py
./run.sh pnpm run typecheck
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

If `pnpm verify` fails only at network-dependent `pnpm audit`, rerun with approved network
access if available; otherwise report that exact blocked gate separately.

## Deliverables

- Updated plan in `docs/plans/2026-06-04_fix_updater_stuck_check_state.md`.
- Frontend implementation in `src/components/PluginUpdateSection.tsx`.
- Static regression tests in `tests/test_frontend_static.py`.
- Session log under `docs/agent_conversations/`.
- Conventional Commit, likely:
  - `fix(updater): recover from interrupted update checks`

## Acceptance Criteria

- Successful dev release install is still treated as successful.
- Status no longer remains indefinitely on `Checking...`.
- `Check now` re-enables after the bounded UI timeout or successful handoff.
- Navigating away/back is no longer required to recover the Updates panel.
- Stale or late update-check responses cannot overwrite newer installed/pending state.
- Backend pending install reconciliation remains authoritative.
