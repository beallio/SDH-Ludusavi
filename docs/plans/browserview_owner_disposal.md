# BrowserView Owner Disposal

## Problem Definition

`destroyAutoSyncStatusBrowserView()` currently uses an exclusive destroy branch. If
the normalized nested BrowserView exposes `Destroy()`, the parent
`autoSyncStatusBrowserViewOwner` is not destroyed, which can leave native wrapper
resources allocated.

## Architecture Overview

Keep the cleanup scoped to `src/index.tsx` and the existing BrowserView lifecycle.
Capture both the normalized view and owner wrapper, hide the normalized view, then
dispose the nested view and owner wrapper when they are distinct objects. Fall back to
`SteamClient.BrowserView.Destroy(...)` when no direct `Destroy()` method is available.

## Core Data Structures

None.

## Public Interfaces

No public API, RPC, settings, or return types change.

## Dependency Requirements

None.

## Testing Strategy

Add frontend static coverage for `destroyAutoSyncStatusBrowserView()` proving:

- It captures `autoSyncStatusBrowserViewOwner`.
- It does not use an exclusive `else if` destroy chain.
- It can invoke `browserView.Destroy()` and `browserViewOwner.Destroy()` for distinct
  objects.
- It still clears `autoSyncStatusBrowserView` and `autoSyncStatusBrowserViewOwner`.
