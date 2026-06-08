# Hydrate Lifecycle Settings Before Syncthing Decisions

## Problem Definition

The lifecycle controller starts when the plugin module loads, but persisted settings are
currently loaded only when the QAM React content mounts. If a game exits before that
mount, `store.getSnapshot().settings` is `null`, so the controller treats automatic sync
as disabled and never starts the post-game Syncthing watch.

## Architecture Overview

- Start one settings-hydration promise from the plugin composition root immediately
  after creating the shared state store.
- Apply successful settings results to that store through the existing
  `applySettingsGlobal` helper.
- Pass an `ensureStateReady` callback to the lifecycle controller.
- Await that callback at the start of app-start and app-exit handling before reading
  persisted settings or making Syncthing watch decisions.
- Keep lifecycle registration immediate so Steam events that occur during hydration are
  captured and processed after hydration resolves.
- Leave game-list hydration in the QAM path. Post-game Syncthing watch creation already
  tolerates an empty or stale tracking cache.

## Core Data Structures

- A shared `Promise<void>` owns startup settings hydration.
- `GameLifecycleControllerDependencies` gains an optional
  `ensureStateReady: () => Promise<void>` callback that defaults to an already-ready
  no-op for isolated callers and tests.
- The existing `LudusaviStateStore` remains the single settings source of truth.

## Public Interfaces

- No backend RPC or user-facing API changes.
- The internal lifecycle-controller dependency contract gains `ensureStateReady`.

## Dependency Requirements

No new dependencies.

## Testing Strategy

1. Add a failing controller test where the store begins with `settings=null`, an exit
   event arrives, and `ensureStateReady` later hydrates `auto_sync_enabled=true`.
2. Assert the post-game Syncthing watch starts after hydration and the backup handoff
   reaches the pending Syncthing status.
3. Keep existing controller tests on the default ready behavior and inject a deferred
   readiness callback only in the cold-start regression test.
4. Add static coverage proving startup settings hydration is created before
   `lifecycleController.start()`.
5. Run frontend unit tests, typecheck, build, and the full Python validation suite.
