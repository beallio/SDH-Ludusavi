# Generalize Post-Install Update Check Suppression

## Summary

The dev-to-stable version reconciliation fix did not resolve the runtime symptom. Stable-to-dev
and dev-to-dev updates can still leave the Updates panel stuck on `Checking...`, with `Check now`
disabled until `UPDATE_CHECK_UI_TIMEOUT_MS` expires and the UI shows `Check interrupted`.

The remaining bug is generic: automatic update checks can still start during the install/reload
window. Those checks should be suppressed or short-circuited while fresh pending-install metadata is
active. The pending-install freshness window is not a UI delay; it is only an expiry for trusted
pending metadata after reload.

Treat this plan as the authoritative replacement for the channel-specific dev-to-stable plan.

## Architecture Overview

- Work continues on `fix/updater-dev-to-stable-post-install-state` unless the user explicitly
  requests a different branch.
- Frontend update state lives in `src/components/PluginUpdateSection.tsx`, including
  `isChecking`, `inFlightCheck`, `activeCheckId`, `installedOverride`, `effectiveCurrentVersion`,
  pending-install hydration, automatic check effects, and the manual `Check now` button.
- Backend update checks are exposed by `main.py::Plugin.check_for_plugin_update`.
- Backend pending-install state is managed by `py_modules/sdh_ludusavi/updater.py`.

## Core Data Structures

- Keep existing `pending_update_install` fields:
  - `version`
  - `tag`
  - `channel`
  - `published_at`
  - `requested_at`
  - `handoff_confirmed_at`
  - `update_trace_id`
- Add frontend-only state or refs as needed to track that a fresh post-install guard is active.
- Do not add required public RPC fields unless a test proves the implementation needs one.
- Continue using `effective_installed_version` from `get_update_check_context`.

## Public Interfaces

Do not rename or remove these RPC methods:

- `check_for_plugin_update`
- `get_update_check_context`
- `record_update_install_requested`
- `confirm_update_install_handoff`
- `clear_pending_update_install`
- `revalidate_plugin_update`

Do not change Decky installer argument order or install type constants.

Internal frontend check options may be extended with a source field such as:

```ts
source: "automatic" | "manual"
```

This is an internal component option only, not a public RPC change.

## Implementation Plan

### Frontend Post-Install Guard

Add a shared helper in `PluginUpdateSection.tsx` that enters a current/installed post-install guard
for a target version and channel.

The helper must:

- increment `activeCheckId.current`;
- clear the check timeout;
- set `inFlightCheck.current = null`;
- set `isChecking=false`;
- set `installedOverride` to the target version/channel;
- set `pendingInstallVersion.current` to the target version;
- set `checkResult` to `current`;
- clear `candidate`;
- clear `errorMsg`.

Call this helper:

- immediately after `recordUpdateInstallRequestedCall(payload)` succeeds and before
  `invokeDeckyInstaller`;
- from `handleHandoffSuccess`;
- from pending-install hydration when
  `ctx.effective_installed_version === ctx.pending_update_install.version`.

### Automatic vs Manual Checks

Extend `checkForUpdates` with an internal source field:

- `source: "automatic"` for mount, channel, version, and toggle effects;
- `source: "manual"` for the `Check now` button.

Automatic checks must no-op while any fresh post-install guard or pending install is active.

Manual checks may run when the user presses `Check now`, but they must still respect `isInstalling`.
If a manual check occurs while a pending target is active, it must use `effectiveCurrentVersion` and
retain the existing stale-result coercion.

The automatic no-op must not set `isChecking=true`, must not assign `inFlightCheck.current`, and must
not disable `Check now`.

### Backend Pending Fast Path

In `main.py::Plugin.check_for_plugin_update`, add a fast path before 24-hour cache reuse and before
GitHub/network update checking:

- load update context from the service;
- if `pending_update_install` is fresh and
  `effective_installed_version === current_version`, return a `current` result immediately;
- do not call `check_for_update` in this fast path;
- do not resurrect cached `available` results;
- log pending version, current version, effective version, channel, and force flag.

This fast path should apply to stable-to-dev, dev-to-dev, and dev-to-stable pending installs.

### Preserve Existing Version Reconciliation

Keep the existing dev-to-stable work already on the branch:

- fresh unconfirmed pending installs can become effective;
- stable pending `X.Y.Z` can promote against loaded `X.Y.Z+metadata`;
- stable pending `X.Y.Z` does not promote against loaded `X.Y.Z-dev.*`;
- stale pending metadata expires and normal update checks resume.

## Testing Strategy

Follow strict TDD. Add failing tests before behavior-changing code.

### Frontend Static Tests

Add or update `tests/test_frontend_static.py` to prove:

- `recordUpdateInstallRequestedCall(payload)` is followed by entering the post-install guard before
  `invokeDeckyInstaller`;
- pending hydration enters the same guard and skips automatic checks;
- mount, channel, version, and automatic-toggle effects call `checkForUpdates` with
  `source: "automatic"`;
- the `Check now` button calls `checkForUpdates` with `source: "manual"`;
- automatic checks return early while the post-install guard or pending target is active;
- the automatic no-op path does not set `isChecking=true` or `inFlightCheck.current`;
- `handleHandoffSuccess` still clears active checks and preserves current installed UI state.

### Backend Tests

Add or update backend tests to prove:

- `check_for_plugin_update` returns `current` immediately when a fresh pending install is effective
  for the requested version;
- the pending fast path does not call `check_for_update`;
- the pending fast path works for stable-to-dev, dev-to-dev, and dev-to-stable versions;
- stale pending metadata falls through to normal update-check behavior;
- existing version-aware cache and stale-cache invalidation tests still pass.

### Runtime Scenarios

The fixed behavior must cover:

- stable release to dev release;
- dev release to dev release;
- dev release to stable release;
- reload after pending install metadata is saved but before handoff confirmation persists;
- manual `Check now` after pending hydration.

## Validation

Focused red/green checks:

```bash
./run.sh uv run pytest tests/test_updater_service.py tests/test_main.py tests/test_frontend_static.py
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

If `pnpm verify` fails only at network-dependent `pnpm audit`, retry with approved network access
if available; otherwise report that exact blocked gate separately.

Final review-fix loop gate:

```bash
npx @openai/codex review --base main
```

Fix all valid findings and rerun the review command until no valid blocking findings remain.

## Dependency Requirements

No new dependencies are expected.

## Commit Guidance

All implementation commits should occur on the current branch:

```text
fix/updater-dev-to-stable-post-install-state
```

Use Conventional Commits. A likely commit message is:

```text
fix(updater): suppress post-install automatic checks
```

Record a session summary in `docs/agent_conversations/` before final commit.

## Acceptance Criteria

- Stable-to-dev, dev-to-dev, and dev-to-stable installs no longer leave the Updates panel stuck on
  `Checking...`.
- `Check now` is not disabled by an automatic check during the fresh pending-install window.
- Pending install hydration shows the target version as current without starting an automatic check.
- Backend update checks return `current` immediately for fresh effective pending installs instead
  of hitting cache or GitHub.
- Failed or canceled installs stop appearing current after pending metadata expires.
- Focused and full validation gates pass, or any external-network blocker is reported precisely.
