# Suppress Syncthing Monitoring Without Connected Peers

## Summary

The plugin must detect whether the Syncthing folder has any **connected configured
peers**, rather than testing general internet access. Syncthing may work over LAN
without internet, while internet access does not guarantee that a relevant peer is
reachable.

After a successful backup with no connected peers, immediately show:

`LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE`

The backup remains successful. Do not show a failure toast or claim that Ludusavi
failed.

## Current State And Gaps

Current behavior:

- The local Syncthing API is discovered and queried.
- `/rest/system/connections` is already called, but only aggregate byte totals are used.
- Configured device IDs and per-device `connected` states are ignored.
- A post-game watch starts whenever Syncthing and the backup folder are available.
- With no peers online, the UI may remain on `SYNCTHING PREPARING` for the 30-120
  second detection period before falling back to normal local-backup status.
- Existing classifications already cover:
  - Syncthing not configured: silent local result.
  - Local API unavailable: `SYNCTHING UNAVAILABLE`.
  - Backup path outside a Syncthing folder: `PATH NOT SHARED`.
- Syncthing monitoring is advisory and never invalidates a successful local backup.

Gaps addressed:

- Avoid unnecessary watcher threads and polling when synchronization cannot currently
  occur.
- Distinguish "Syncthing API unavailable" from "Syncthing is running but no relevant
  peers are connected."
- Eliminate the misleading preparation delay after an offline backup.
- Preserve accurate wording: the local backup succeeded, but remote propagation was
  not observed.

## Architecture Overview

The backend remains the sole owner of Syncthing configuration, device IDs, connection
state, and watcher allocation. It classifies relevant peer availability before starting
a watcher and while polling an active watcher.

The existing RPC status contract carries terminal reason codes to the frontend. The
frontend maps those reasons to user-facing status-strip states while preserving the
existing generation, cancellation, and successful-backup invariants.

No general internet probe is introduced.

## Core Data Structures

- Extend `FolderSelection` with a deduplicated immutable collection of configured
  remote device IDs.
- Add an internal connection snapshot containing:
  - aggregate input and output byte totals;
  - the set of device IDs whose Syncthing `connected` field is `true`.
- Add the RPC reason `no_connected_peers`.
- Add the RPC reason `folder_not_shared`.
- Add `syncthing_no_peers` to `AutoSyncStatusKind`.

Device IDs remain backend-only and must never be logged or returned through RPC.

## Public Interfaces

### Backend Detection

- Extend folder resolution to retain the configured remote device IDs for the matched
  folder.
- Add a structured connection snapshot parser for `/rest/system/connections`.
- Preserve `get_connection_totals()` as a compatibility wrapper around the new parser.
- Determine availability by intersecting the matched folder's configured devices with
  currently connected devices:
  - No configured devices: return `folder_not_shared`.
  - Configured devices but none connected: return `no_connected_peers`.
  - At least one relevant peer connected: start the existing watch.
  - Connected devices unrelated to the matched folder do not count.
  - Connection endpoint failure remains `api_unavailable`.
- Pass the initial connection snapshot into `SyncthingWatch` and re-evaluate relevant
  peer connectivity during polling.
- If all relevant peers disconnect, publish a terminal `no_connected_peers` result and
  stop the watcher.
- Use device membership only for connectivity. Do not restore sequence comparison or
  claim remote acknowledgement or completion.

### Frontend Behavior

- Add a shared reason-to-status mapper used by the lifecycle controller and monitor:
  - `no_connected_peers` -> `syncthing_no_peers`.
  - `folder_not_found` or `folder_not_shared` -> `syncthing_folder_not_found`.
  - `api_unavailable` and unexpected failures -> `syncthing_unavailable`.
  - `not_configured` -> no Syncthing status.
- Preserve actionable failure reasons from both watch allocation and later poll
  failures.
- Post-game behavior:
  - Continue the Ludusavi backup normally.
  - If no peers are connected, stop monitoring and immediately publish the new
    terminal warning.
  - Auto-hide it using the existing result-status timeout.
  - Do not emit a failure toast.
- Pre-game behavior:
  - Skip Syncthing monitoring silently when no peers are connected.
  - Continue existing restore and conflict checks without blocking game launch.
- Render `syncthing_no_peers` as
  `LOCAL BACKUP SAVED - NO SYNCTHING PEERS ONLINE`.
- Use the existing amber warning style and fallback icon treatment. Add no new visual
  dependency.

## Dependency Requirements

No new dependencies, external connectivity probes, settings, RPC endpoints, or
persistence migrations are required. Continue using the existing local Syncthing REST
API client.

## Logging And Documentation

- Document that peer connectivity, not internet connectivity, controls this behavior.
- Update the README status list and durable sync specification with the new message.
- Log reason, phase, and configured/connected peer counts only.
- Never log device IDs, API keys, or Syncthing configuration.
- Record the implementation in `docs/agent_conversations/`.

## Testing Strategy

Follow strict Red-Green-Refactor.

Backend tests:

- Parse configured folder device IDs with deterministic deduplication.
- Parse connected devices and aggregate totals from a valid connection response.
- Reject malformed connection responses as API failures.
- Return `folder_not_shared` when the folder has no configured devices.
- Return `no_connected_peers` when all relevant peers are disconnected.
- Ignore connected devices not assigned to the matched folder.
- Start the watcher when at least one relevant peer is connected.
- Stop an active watcher if its final relevant peer disconnects.
- Preserve the existing narrow activity-sample schema and
  `get_connection_totals()` behavior.

Frontend tests:

- Preserve `no_connected_peers` through allocation and polling failures.
- Successful backup plus no peers publishes `syncthing_no_peers`, not a failed
  operation.
- Pre-game no-peer detection produces no warning.
- The new status has the exact selected text, amber styling, and terminal auto-hide
  behavior.
- Existing `not_configured`, `api_unavailable`, and path-not-shared behavior remains
  unchanged.
- Connected-peer upload, completion, cancellation, and generation-race tests remain
  green.

Validation:

- Run targeted Python and Vitest tests first.
- Run tracked-file Ruff formatting and checks, `ty`, full `pytest`,
  `./run.sh pnpm run test`, `./run.sh pnpm run build`, and
  `./run.sh pnpm run verify`.
- Preserve the unrelated untracked `split_syncthing_tests.py`.
- Commit as `feat(syncthing): skip monitoring without connected peers`.

## Assumptions

- One connected device assigned to the matched folder is sufficient to retain
  monitoring.
- Brief disconnections produce the immediate warning by design; no reconnection grace
  period is added.
- Syncthing may synchronize later after a peer reconnects, but this completed UI
  session will not resume monitoring.
- A folder with zero configured remote devices uses the existing `PATH NOT SHARED`
  warning.
- No new setting, RPC endpoint, persistence migration, or external connectivity probe
  is required.
