# Fix Updater Post-Install Stale Check State

## Problem Definition

The updater panel can still show stale post-install state after a successful GitHub/Decky
install. The existing frontend fix prevents a stale in-flight check promise from leaving
the panel indefinitely on `Checking...`, but backend update-check caching can still return
a 24-hour `last_result` that was computed for the pre-install version.

The expected behavior is that a successful install handoff immediately moves the Updates
section to an installed/current state, and that backend cache reuse cannot resurrect an
`Update available` result for the version that was just installed.

## Architecture Overview

- Frontend state lives in `src/components/PluginUpdateSection.tsx`, including
  `isChecking`, `candidate`, `installedOverride`, `effectiveCurrentVersion`,
  pending-install hydration, and check ownership guards.
- Backend update checks are exposed by `main.py::Plugin.check_for_plugin_update`.
  The current non-forced cache path reuses `service._update_check_cache["last_result"]`
  based on age and channel, but not the installed version the result was computed for.
- Durable updater metadata is managed by `py_modules/sdh_ludusavi/updater.py`, including
  pending install requests, handoff confirmation, startup reconciliation, and update-check
  cache fields.

The fix should keep backend pending-install reconciliation as the authoritative durable
source of truth while making update-check cache reuse version-aware and clearing stale
availability data when install state changes.

## Core Data Structures

- Add or use a cache field named `last_checked_version` in
  `service._update_check_cache`.
- `last_checked_version` must represent the installed/effective version used for the
  update-check comparison that produced `last_result`.
- Existing fields to preserve:
  - `last_result`
  - `last_checked_at`
  - `last_checked_channel`
  - `last_available_tag`
  - `pending_update_install`
  - `installed_release_tag`
  - `installed_release_published_at`

## Public Interfaces

Do not change public RPC names or the frontend candidate wire shape.

No changes are expected to these RPC method names:

- `check_for_plugin_update`
- `get_update_check_context`
- `record_update_install_requested`
- `confirm_update_install_handoff`
- `clear_pending_update_install`
- `revalidate_plugin_update`

If `get_update_check_context` is extended with extra diagnostic fields, keep all existing
fields and ensure older frontend code would continue to function.

## Implementation Plan

### Backend Cache Reuse

In `main.py::Plugin.check_for_plugin_update`:

- Keep the existing 24-hour non-forced cache behavior only when all of these match:
  - cached `last_checked_at` is within 24 hours;
  - cached `last_checked_channel == service._update_channel`;
  - cached `last_checked_version == current_version`.
- If `last_checked_version` is missing or differs from `current_version`, bypass
  `last_result` and run a live update check.
- When a live check returns `available` or `current`, persist `last_result`,
  `last_checked_at`, `last_checked_channel`, and `last_checked_version`.
- Log cache hits and cache bypasses with enough context to diagnose stale state without
  exposing full SHA-256 values.

### Backend Cache Invalidation

In `py_modules/sdh_ludusavi/updater.py`, add a small helper such as
`clear_stale_update_check_cache(service)` that removes stale availability/check result
fields:

- `last_result`
- `last_available_tag`
- `last_checked_version`

Use that helper when install state changes:

- `record_update_install_requested`
- `confirm_update_install_handoff`
- `clear_pending_update_install`
- `reconcile_pending_update_install` when a pending install is promoted
- `reconcile_pending_update_install` when stale/mismatched pending metadata is cleared

Do not clear rate-limit state. Do not remove `last_checked_at` or `last_checked_channel`
unless tests show that retaining them causes misleading UI; the critical stale fields are
the cached result, available tag, and checked version.

### Frontend State Guard

In `src/components/PluginUpdateSection.tsx`:

- Keep the existing `activeCheckId`, timeout, `installedOverride`,
  `effectiveCurrentVersion`, pending-install hydration, and stale-result coercion logic.
- Change `checkForUpdates` early guard to use `effectiveCurrentVersion`, not only raw
  `currentVersion`, so pending-install hydration can drive checks while the parent version
  prop is stale.
- Continue calling `checkForPluginUpdateCall(effectiveCurrentVersion, opts.force)`.
- When `handleHandoffSuccess` runs, keep clearing active check state, setting the installed
  override, clearing candidate/error state, setting `checkResult` to current, and calling
  `onInstallVersionConfirmed(version)`.
- Do not immediately trigger a non-forced cached check after successful handoff.
- During `loadCache`, if backend context reports a fresh confirmed `pending_update_install`
  where `effective_installed_version` equals the pending version, hydrate the installed
  override, clear candidate/error state, set status current, update the parent Versions
  state, and skip the initial automatic background check for that mount.

If a post-install check is needed for diagnostics or channel changes, it must be a forced
check and must happen only after the UI has already moved to current/installed state.

## Testing Strategy

Follow strict TDD. Add failing tests before implementation.

### Backend Tests

Add or extend tests in `tests/test_updater_service.py` or the nearest existing updater
RPC test file:

- Non-forced update checks reuse `last_result` only when `last_checked_version` matches
  the requested version.
- A cached `available` result computed for `0.2.3` is not reused when
  `check_for_plugin_update("0.2.4", force=False)` is called.
- A successful live check stores `last_checked_version`.
- `record_update_install_requested` clears stale `last_result`, `last_available_tag`, and
  `last_checked_version`.
- `confirm_update_install_handoff` clears stale `last_result`, `last_available_tag`, and
  `last_checked_version`.
- `reconcile_pending_update_install` promotion clears stale availability cache and records
  installed release metadata.
- Fresh confirmed pending install still reports `effective_installed_version` during the
  reload grace window.

### Frontend Static Tests

Extend `tests/test_frontend_static.py`:

- `checkForUpdates` early return guard uses `effectiveCurrentVersion`.
- `checkForPluginUpdateCall` uses `effectiveCurrentVersion`.
- Pending-install hydration skips the initial automatic non-forced check.
- Successful handoff leaves `candidate`, `errorMsg`, `isChecking`, and
  `inFlightCheck.current` cleared.
- Stale available responses matching `pendingInstallVersion`, `installedOverride.version`,
  or `effectiveCurrentVersion` are coerced to current.

## Validation

Focused red/green checks:

```bash
./run.sh uv run pytest tests/test_updater_service.py tests/test_frontend_static.py
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

If `pnpm verify` fails only at network-dependent `pnpm audit`, rerun with approved
network access if available; otherwise report that exact blocked gate separately.

As a final review-fix loop gate, run:

```bash
npx @openai/codex review --base main
```

Fix all valid findings, rerun focused/full validation as appropriate, then rerun the
review command until no valid blocking findings remain.

## Dependency Requirements

No new dependencies are expected.

Do not change Decky installer argument order, install type constants, release manifest
validation, or public RPC names.

## Commit Guidance

All commits for this work must be made on the current branch,
`fix/updater-stuck-check-state`, because this fix is still ongoing.

Use Conventional Commits. A likely commit message is:

```text
fix(updater): invalidate stale post-install check cache
```

## Acceptance Criteria

- Successful GitHub/Decky install is still treated as successful.
- The Updates panel does not remain indefinitely on `Checking...`.
- The panel does not re-show `Update available` or an install button for the version that
  was just installed.
- `Check now` re-enables after bounded timeout or successful handoff.
- Backend non-forced cache hits are version-aware.
- Pending-install reconciliation remains authoritative.
- Existing updater, frontend static, backend, type, and formatting gates pass or have
  explicitly reported external-network blockers.
