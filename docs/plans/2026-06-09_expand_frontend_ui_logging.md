# Expand Frontend UI Logging

## Problem Definition

Frontend diagnostics are inconsistent. The updater and lifecycle paths expose useful
stage logs, while QAM visibility, initial loading, cache decisions, settings changes,
manual operations, log viewing, and launcher actions can be difficult to reconstruct
from the plugin log.

## Architecture Overview

Extend `src/utils/logging.ts` with a structured UI-event helper that formats stable
`event: key=value` messages and continues routing through the existing backend `log`
RPC. Instrument controller and component boundaries where a user action starts,
completes, is skipped, or fails. Avoid render-time logging and raw object dumps.

## Core Data Structures

- `LogLevel`: supported frontend/backend log levels.
- `LogFieldValue`: string, number, boolean, null, or undefined.
- `LogFields`: named diagnostic fields rendered in sorted order.

## Public Interfaces

- `log(level, message, operation?, gameName?)`: existing free-form logging API.
- `logUiEvent(event, fields?, level?, operation?, gameName?)`: structured UI event API.

No backend RPC or persisted-data schema changes are required.

## Dependency Requirements

No new dependencies. The implementation uses the existing Decky `callable("log")`
RPC and browser console.

## Testing Strategy

1. Add frontend unit tests for deterministic field formatting, omitted undefined
   fields, level routing, and backend logging failures.
2. Run the frontend unit suite to confirm the tests fail before implementation.
3. Instrument QAM, settings, launcher, and lifecycle-source boundaries.
4. Run frontend unit tests, type checking, build, Python quality checks, and the full
   Python test suite through `./run.sh`.

## Scope

In scope:

- Plugin/QAM mount, visibility, initialization, metadata, and cache-path decisions.
- Manual refresh, backup, restore, log-modal, game-selection, and settings events.
- Ludusavi launcher and Steam lifecycle-source outcomes.
- Logging transport resilience.

Out of scope:

- Backend logging policy changes.
- Per-render or per-poll debug noise.
- Logging sensitive environment data, full checksums, or complete settings payloads.
