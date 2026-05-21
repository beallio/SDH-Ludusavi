# Defer BrowserView Recreation

## Problem Definition

Lifecycle verification can reset the status strip BrowserView before publishing a new
`checking` status. The current publish path destroys the existing BrowserView and then
immediately recreates it in the same JavaScript execution tick. Steam tears down
BrowserView resources asynchronously, so same-tick recreation can collide with pending
native destruction.

## Architecture Overview

Keep the reset decision in `publishAutoSyncStatus`, but split the reset path into two
tasks:

1. Destroy the existing BrowserView surface before publishing lifecycle verification.
2. Publish the new status state immediately, then schedule BrowserView synchronization
   with a zero-delay timeout so native teardown has a chance to advance before
   recreation.

The non-reset publish path keeps the existing immediate synchronization behavior.

## Core Data Structures

- `currentAutoSyncStatusState`: remains the source of truth for the latest status strip
  state.
- Deferred sync timeout ID: tracks the pending zero-delay BrowserView synchronization so
  stale callbacks can be cancelled when the strip is hidden or destroyed.

## Public Interfaces

No public API, RPC, or exported type changes are required. `publishAutoSyncStatus` keeps
its synchronous return type.

## Dependency Requirements

No dependency changes are required. The implementation uses `window.setTimeout`.

## Testing Strategy

Update static frontend tests to assert that lifecycle reset recreation is scheduled via
a deferred helper, that the helper yields with `setTimeout(..., 0)`, and that cleanup
paths clear pending deferred synchronization before the BrowserView can be recreated.
