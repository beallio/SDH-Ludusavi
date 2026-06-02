# Fix Updater Version Reconciliation

## Problem Definition

After a successful Decky installer handoff, the Updates panel and shared Versions section can continue to show the previously loaded SDH-Ludusavi version until the user exits and reopens QAM. The prior frontend-only optimistic update handles the immediate success callback, but it does not cover reload/startup paths where the old backend version is still loaded and pending install metadata is the only durable signal.

## Architecture Overview

The updater already persists `pending_update_install` before invoking the Decky installer. Startup reconciliation should not discard that metadata during the short window where Decky has not yet loaded the new plugin version. The frontend should also hydrate its local optimistic installed version from pending install metadata returned by `get_update_check_context`, so the Updates panel and shared Versions section reflect the requested installed version immediately after reload.

## Core Data Structures

- `pending_update_install`: persisted update metadata with `version`, `tag`, `channel`, `published_at`, `requested_at`, and trace fields.
- `effective_installed_version`: update-check context value representing the pending installed target when a fresh confirmed pending install exists, otherwise the resolved backend version.
- `InstalledOverride`: frontend local optimistic version state for display and update checks.

## Public Interfaces

- `get_update_check_context()` continues to return existing fields and adds `effective_installed_version`.
- `confirm_update_install_handoff(version)` marks matching pending install metadata as confirmed after the Decky installer handoff resolves.
- `clear_pending_update_install(version)` removes matching pending metadata after installer failure.
- `reconcile_pending_update_install(current_version)` keeps fresh confirmed mismatched pending installs during the reload grace window measured from handoff confirmation, promotes exact matches, and still clears stale or unconfirmed mismatches.
- `PluginUpdateSection` hydrates `InstalledOverride` from `pending_update_install` or `effective_installed_version` and calls `onInstallVersionConfirmed`.

## Dependency Requirements

No new runtime or development dependencies are required.

## Testing Strategy

- Add backend tests proving fresh confirmed mismatched pending installs survive startup reconciliation while stale or unconfirmed mismatches still clear.
- Add backend tests proving update-check context exposes the pending effective installed version only after handoff confirmation.
- Add frontend static tests proving pending install metadata seeds `installedOverride` and shared version state after reload.
- Run focused tests first for red/green, then the project validation gates through `./run.sh`.
