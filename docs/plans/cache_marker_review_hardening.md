# Cache Marker Review Hardening

## Problem Definition

The cache marker implementation needs follow-up hardening from review:

- Lazy Ludusavi adapter initialization is not synchronized.
- Cache marker values are staged in mutable pending fields before the refresh lock is
  acquired.
- `installed_app_ids` is accepted from the frontend as an unbounded raw string.
- Failure to read the Ludusavi config marker can match a stale cached marker and return
  cached data.

## Architecture Overview

Keep the public `refresh_games(force=False, installed_app_ids=None)` RPC unchanged.
Normalize the frontend app marker immediately at the service boundary, compute the
config marker, and pass both markers into the refresh callback that runs under the
existing operation lock.

Add a dedicated adapter initialization lock so `_ludusavi()` remains safe when multiple
RPCs first touch the service concurrently.

## Core Data Structures

- `MAX_INSTALLED_APP_IDS_BYTES`: maximum raw frontend marker size accepted.
- `_CONFIG_MARKER_READ_FAILED`: private sentinel used to force refresh on marker read
  failure.
- `_installed_app_ids`: persisted normalized app marker.
- `_ludusavi_config_mtime_ns`: persisted Ludusavi config marker.

## Public Interfaces

No public API changes.

## Dependency Requirements

No dependency changes.

## Testing Strategy

Add backend tests for:

- Oversized `installed_app_ids` input is not persisted.
- Malformed `installed_app_ids` input is not persisted.
- Unsorted/duplicate installed app IDs normalize before comparison and persistence.
- Concurrent adapter initialization calls the factory only once.
- Concurrent refreshes cannot overwrite each other's cache markers before the lock.
- Config marker read failures trigger refresh instead of a false cache hit.
