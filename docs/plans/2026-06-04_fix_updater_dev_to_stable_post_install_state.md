# Fix Dev-to-Stable Post-Install Updater State

## Problem Definition

When installing from a development release to a stable release, the Updates panel can
return to a stale available/update state after Decky reloads the plugin. Dev-to-dev
updates appear fixed because the existing optimistic frontend override and confirmed
pending-install hydration cover that path, but dev-to-stable can still regress when the
loaded version, pending target version, and stable/local metadata are compared too
strictly or when the frontend derives status copy from the raw pre-install dev version.

The expected behavior is immediate UI movement to the target stable release after a
successful installer handoff, followed by durable reload recovery that continues to treat
the pending stable target as the effective installed version until startup reconciliation
either proves the install succeeded or expires the pending metadata.

The pending-install freshness window is not a UI delay. It is only a safety expiry for
trusted pending metadata after reload so failed or canceled installs cannot look current
forever.

## Architecture Overview

- Work must be performed on a new branch named
  `fix/updater-dev-to-stable-post-install-state`.
- Frontend update state lives in `src/components/PluginUpdateSection.tsx`, including
  `installedOverride`, `effectiveCurrentVersion`, pending-install hydration,
  stale-result coercion, status copy, and install handoff success handling.
- Backend update context and reconciliation live in `py_modules/sdh_ludusavi/updater.py`,
  including `pending_update_install`, `effective_installed_version`,
  `record_update_install_requested`, `confirm_update_install_handoff`,
  `clear_pending_update_install`, and `reconcile_pending_update_install`.
- Candidate selection already supports `update`, `move_to_stable`, and
  `downgrade_to_stable`; the fix should preserve those public actions and make
  post-install state handling stable-aware.

## Core Data Structures

- Continue using `pending_update_install` with existing fields:
  - `version`
  - `tag`
  - `channel`
  - `published_at`
  - `requested_at`
  - `handoff_confirmed_at`
  - `update_trace_id`
- Add no new required public RPC fields unless needed for diagnostics.
- Keep `effective_installed_version` in `get_update_check_context`; extend its meaning so
  a fresh unconfirmed pending install can be effective during the reload recovery window.
- Use the existing pending-install freshness duration for expiration, or define a named
  constant equivalent to 180 seconds if the current constant is not already that value.

## Public Interfaces

Do not rename or remove these RPCs:

- `check_for_plugin_update`
- `get_update_check_context`
- `record_update_install_requested`
- `confirm_update_install_handoff`
- `clear_pending_update_install`
- `revalidate_plugin_update`

Do not change the public candidate action names:

- `update`
- `move_to_stable`
- `downgrade_to_stable`

If `get_update_check_context` adds diagnostic fields, all existing fields must remain
compatible with the current frontend.

## Implementation Plan

### Backend Pending Effective Version

- Change `_effective_pending_install_version` so a fresh pending install can become the
  effective installed version even before `handoff_confirmed_at` exists.
- The freshness source should remain:
  - `handoff_confirmed_at` for confirmed pending installs;
  - `requested_at` for unconfirmed pending installs.
- Keep freshness bounded by the existing grace/TTL constant.
- This should make `record_update_install_requested(candidate)` return a context whose
  `effective_installed_version` is the pending candidate version immediately after the
  pending record is saved.

### Backend Stable-Equivalent Reconciliation

- Add a helper for pending-install promotion, for example
  `_pending_install_matches_loaded_version(pending_version, current_version)`.
- The helper must promote when:
  - `pending_version == current_version`;
  - pending version is stable `X.Y.Z` and current version is stable/local
    `X.Y.Z+metadata`.
- The helper must not promote when:
  - current version is development `X.Y.Z-dev.*`;
  - the semantic base version differs;
  - either version cannot be parsed.
- Use the helper inside `reconcile_pending_update_install`.
- On promotion, keep existing behavior that writes `installed_release_tag` and
  `installed_release_published_at`, clears `pending_update_install`, clears stale
  update-check cache fields, saves state, and logs promotion.
- On mismatch:
  - retain fresh pending metadata during the TTL;
  - clear stale pending metadata after the TTL expires.

### Frontend Dev-to-Stable State

- Preserve existing immediate success behavior in `handleHandoffSuccess`:
  - increment `activeCheckId`;
  - clear check timeout;
  - set `isChecking` false;
  - clear `inFlightCheck`;
  - call `confirm_update_install_handoff`;
  - set `installedOverride`;
  - set `checkResult` to current;
  - clear `candidate` and `errorMsg`;
  - clear install/handoff pending flags;
  - call `onInstallVersionConfirmed`.
- Ensure reload hydration treats a pending stable install as current whenever
  `ctx.effective_installed_version === ctx.pending_update_install.version`.
- Ensure pending hydration skips the initial automatic non-forced check for that mount.
- Replace status text logic that depends on raw `currentVersion.includes("dev")`.
  Status should be derived from `effectiveCurrentVersion`, candidate action/channel, and
  pending install state so a dev-to-stable install does not keep showing development-copy
  or a stale stable install button.

### Cache and Branch Safety

- Keep the existing version-aware update-check cache behavior.
- Do not reintroduce non-forced cache reuse for a result computed against the
  pre-install dev version.
- Before implementation, create or switch to
  `fix/updater-dev-to-stable-post-install-state`.
- Do not commit on `main`.

## Testing Strategy

Follow strict TDD: add failing tests before implementation.

### Backend Tests

Add or update tests in `tests/test_updater_service.py` and, if needed,
`tests/test_updater.py`:

- `record_update_install_requested` returns `effective_installed_version` equal to the
  pending candidate version immediately after saving a fresh pending install.
- A fresh unconfirmed pending install is exposed as effective during the TTL.
- A stale unconfirmed pending install expires and no longer overrides the actual installed
  version.
- A pending stable `0.2.3` promotes when the loaded version is `0.2.3`.
- A pending stable `0.2.3` promotes when the loaded version is `0.2.3+metadata`.
- A pending stable `0.2.3` does not promote when the loaded version is
  `0.2.3-dev.gabcdef`.
- `move_to_stable` from a same-base dev release keeps the panel current after pending
  hydration.
- `downgrade_to_stable` from a higher-base dev release keeps the panel current after
  pending hydration.
- Existing stale-cache invalidation tests still pass.

### Frontend Static Tests

Add or update tests in `tests/test_frontend_static.py`:

- Pending-install hydration accepts backend `effective_installed_version` for a stable
  pending install.
- Pending-install hydration clears candidate/error state, sets current check result, and
  skips the initial automatic check.
- Stale available responses matching `pendingInstallVersion`, `installedOverride.version`,
  or `effectiveCurrentVersion` are coerced to current.
- Status copy does not use raw `currentVersion.includes("dev")` to decide whether a
  development build is latest.
- Dev-to-stable candidate actions still render correct stable install/downgrade labels.

## Validation

Focused red/green checks:

```bash
./run.sh uv run pytest tests/test_updater_service.py tests/test_updater.py tests/test_frontend_static.py
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

Final review-fix loop gate:

```bash
npx @openai/codex review --base main
```

Fix all valid findings and rerun the review command until no valid blocking findings
remain.

## Dependency Requirements

No new dependencies are expected.

Do not change Decky installer argument order, install type constants, release manifest
validation, package metadata, or public RPC names.

## Commit Guidance

All implementation commits must be made on
`fix/updater-dev-to-stable-post-install-state`.

Use Conventional Commits. A likely commit message is:

```text
fix(updater): preserve dev-to-stable post-install state
```

Record an implementation session summary in `docs/agent_conversations/` before final
commit.

## Acceptance Criteria

- Dev-to-dev install behavior remains fixed.
- Dev-to-stable install immediately moves the Updates panel to current/installed state
  after installer handoff succeeds.
- Dev-to-stable install remains current after Decky/plugin reload when pending install
  metadata is fresh.
- Stable pending `X.Y.Z` can promote against loaded stable-local `X.Y.Z+metadata`.
- Stable pending `X.Y.Z` does not promote against loaded dev `X.Y.Z-dev.*`.
- Failed or canceled installs stop appearing current after pending metadata expires.
- The Updates panel does not resurrect an install button for the stable version that was
  just installed.
- Focused and full validation gates pass, or any external-network blocker is reported
  precisely.
