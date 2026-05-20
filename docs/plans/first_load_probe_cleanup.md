# First-Load Probe Cleanup

## Problem Definition

The May 20 runtime log shows duplicated first-load Ludusavi probes: `--version`
appears twice and `config path` appears twice during initial QAM load. The same
log also shows expected no-context QAM selection misses as warnings, which makes
normal UI-open behavior look unhealthy.

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

## Public Interfaces

No public RPC contract changes are planned. Existing `get_versions`,
`refresh_games`, `get_ludusavi_command`, and QAM current-game behavior remain
the same.

## Dependency Requirements

No dependency changes.

## Testing Strategy

- Add an adapter regression test proving diagnostics, versions, and config
  marker lookup reuse the same Ludusavi version and config path probes.
- Add a frontend static regression test proving no-context QAM misses log at
  debug level, while real unmatched sessions can still be warnings.
- Run focused tests red first, then implement the minimal cache/logging changes.
