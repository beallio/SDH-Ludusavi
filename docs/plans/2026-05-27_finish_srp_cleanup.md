# Plan: Finish SRP Cleanup for `SDHLudusaviService`

## Problem Definition
`SDHLudusaviService` remains too large (~380 lines class size, but the file size is ~720 lines) and still owns game-registry state, refresh orchestration, lifecycle business logic, adapter diagnostics, and log routing internals. Sub-modules also contain circular imports or reach into service internals using `sys.modules` or `self._service._...`.

## Architecture Overview
We will refactor `SDHLudusaviService` into a clean facade:
1. Extract `GameRegistry` to own game state and refresh/matching logic.
2. Decouple `GameLifecycleManager` from `service` via a clean dependency interface.
3. Move diagnostics logging to `gateway.py` and log routing to `log_buffer.py`.
4. Remove circular imports and broad service private-state proxies.

## Core Data Structures
- `GameRegistry`:
  - `_games`: dict[str, GameStatus]
  - `_aliases`: dict[str, str]
  - `_ids`: dict[str, str]
  - `_installed_app_ids`: str | None
  - `_ludusavi_config_mtime_ns`: int | None
- `LifecycleDependencies`: dataclass representing registry, gateway, history, and callbacks.

## Public Interfaces
The public facade API of `SDHLudusaviService` remains unchanged for `main.py` and RPC.
Decomposed manager interfaces:
- `GameRegistry`
- `LifecycleDependencies`

## Dependency Requirements
- `pyludusavi`
- standard Python libraries (`threading`, `logging`, `pathlib`)

## Testing Strategy
- `tests/test_registry.py` for testing cache payload, matching, and status refresh/gating logic.
- `tests/test_lifecycle.py` for testing lifecycle flows with mock dependencies.
- Static checks to verify no imports from `.service` in managers, and facade class size < 400 lines.
