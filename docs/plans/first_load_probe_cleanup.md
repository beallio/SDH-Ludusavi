# First-Load Probe Cleanup

## Problem Definition

The May 20 runtime log shows duplicated first-load Ludusavi probes: `--version`
appears twice and `config path` appears twice during initial QAM load. The same
log also shows expected no-context QAM selection misses as warnings, which makes
normal UI-open behavior look unhealthy.

Follow-up runtime cleanup should also reduce warmed QAM mount work: launcher
command discovery should not repeat after a successful lookup, recent plugin
logs should not be fetched until the user opens the log modal or an operation
finishes, warmed game-list refresh should be skipped when backend cache markers
are still current, and QAM scroll reset retries should avoid the immediate
duplicate plus no-op log entries.

## Architecture Overview

The frontend opens QAM and calls backend RPCs for settings, versions, command
discovery, and game refresh. The backend lazy-initializes the Ludusavi adapter
and logs diagnostics before servicing the first adapter-backed call. Diagnostics
and version lookup currently overlap in the adapter, while config marker lookup
can repeat the config path probe after diagnostics.

## Core Data Structures

- Adapter-level cached versions map for Ludusavi and pyludusavi versions.
- Adapter-level cached diagnostics map for the startup diagnostic fields.
- Existing cached config path reused by diagnostics and config marker checks.
- Service-level cached Ludusavi launch command for successful discovery.
- Backend cache-current response for installed-app and config mtime markers.
- Frontend global installed-app marker alongside the existing global game cache.

## Public Interfaces

Existing `get_versions`, `refresh_games`, `get_ludusavi_command`, and QAM
current-game behavior remain compatible. Add a lightweight
`is_game_cache_current(installed_app_ids)` RPC for warmed frontend mounts.

## Dependency Requirements

No dependency changes.

## Testing Strategy

- Add an adapter regression test proving diagnostics, versions, and config
  marker lookup reuse the same Ludusavi version and config path probes.
- Add a frontend static regression test proving no-context QAM misses log at
  debug level, while real unmatched sessions can still be warnings.
- Add backend regression tests for cached launcher command discovery and cache
  marker freshness.
- Add frontend static regression tests proving warmed loads check cache status
  before `refresh_games`, plugin logs are fetched on modal open, and QAM scroll
  retry/logging avoids no-op spam.
- Run focused tests red first, then implement the minimal cache/logging changes.
