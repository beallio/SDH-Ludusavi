Problem Definition
==================

After installing SDH-Ludusavi v0.2.2 from the in-plugin updater, the Updates section shows the installed target version immediately, but the Versions section continues to show the pre-install `SDH-Ludusavi` version until the Quick Access Menu is closed and reopened.

Architecture Overview
=====================

`PluginUpdateSection` owns the optimistic post-install version override used by its own Installed Version row. `VersionsSection` renders `versions.sdh_ludusavi` from `LudusaviStateStore`, so it does not see the updater's local override.

The fix is to let `PluginUpdateSection` notify its parent when Decky installer handoff succeeds. `LudusaviContent` will update the shared `versions.sdh_ludusavi` value while preserving the other loaded version fields. The backend remains the durable source of truth after plugin reload.

Core Data Structures
====================

- `Versions`: existing frontend metadata object containing `sdh_ludusavi`, `ludusavi`, `pyludusavi`, `decky`, and optional `message`.
- `InstalledOverride`: existing updater-local state for optimistic installed version display.

Public Interfaces
=================

- Add optional `onInstallVersionConfirmed?: (version: string) => void` to `PluginUpdateSectionProps`.
- Pass a callback from `LudusaviContent` that updates `ludusaviStore.setVersions(...)`.

Dependency Requirements
=======================

No new dependencies.

Testing Strategy
================

- Add a static frontend regression test that requires:
  - `PluginUpdateSection` exposes an install-success callback prop.
  - `handleHandoffSuccess` invokes the callback with the installed version.
  - `LudusaviContent` passes the callback and updates `versions.sdh_ludusavi` in the shared store.
- Run the focused failing test before implementation.
- Run frontend static tests and relevant validation after implementation.
