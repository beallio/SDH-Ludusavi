# Frontend State Store Refactor

## Problem Definition

`src/index.tsx` keeps QAM-persistent application data in loose module-scoped variables.
Those variables preserve warmed state across Decky React view remounts, but they bypass
React's subscription model and make state ownership implicit.

## Architecture Overview

Introduce a zero-dependency React context backed by a singleton observable store. The
store is created once in `definePlugin`, provided through `LudusaviStateProvider`, and
consumed by `Content` and lifecycle helpers through `useLudusaviState` or direct store
methods.

The store owns application cache state only:

- settings and selected game
- refreshed games, aliases, history, and installed AppIDs
- versions and Ludusavi command discovery
- notification settings and auto-sync notification enablement
- tracked AppID/name indexes derived from refresh results

Lifecycle registration, process tracking, and BrowserView status-strip state remain in
their existing module-level lifecycle surface for this refactor.

## Core Data Structures

Create `LudusaviStateSnapshot` with stable fields for the warmed QAM cache. The store
exposes immutable snapshots through `useSyncExternalStore` and mutates state only through
named methods such as `applySettings`, `applyRefreshResult`, `setGameHistory`,
`setInstalledAppIds`, `setVersions`, and `setLudusaviCommand`.

## Public Interfaces

New frontend-only interfaces live in `src/state/ludusaviState.tsx`:

- `createLudusaviStateStore()`
- `LudusaviStateProvider`
- `useLudusaviState()`
- `useLudusaviStateStore()`
- `LudusaviStateStore`
- `LudusaviStateSnapshot`

No backend RPC, package metadata, or Decky plugin contract changes are required.

## Dependency Requirements

No new dependency is required. The implementation uses React primitives already present
in the project, especially `createContext`, `useContext`, and `useSyncExternalStore`.

## Testing Strategy

Follow red-green-refactor with static frontend tests first:

- assert `src/index.tsx` uses the provider and hooks
- assert the loose app-cache globals are absent
- assert warmed cache logic reads from store state
- assert notifications and history synchronization use the store
- run TypeScript typecheck/build and the Python validation suite through `./run.sh`
