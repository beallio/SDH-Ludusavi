# Plan: Close SRP Review Fixes

## Problem Definition
Address six specific review findings concerning manager wiring, watchdog correctness, exception-boundary enforcement, and documentation hygiene in `feat/srp-decomposition`.

## Architecture Overview
1. **Ruff/Type checks and Test Validation**:
   - Handle repeated logger setups in `log_buffer.py` by removing prior stale `DeckyLogHandler` instances.
   - Return `failed` status in `ProcessWatchdog.resume()` and keep tracking the PID if `SIGCONT` signaling fails.
   - Extend `test_exception_boundaries` to scan all first-party python files in `py_modules/sdh_ludusavi/` (including `_version.py`).
   - Validate that `LudusaviGateway.get_adapter()` checks for `None` from factory before attempting diagnostics.
   - Refactor `LudusaviGateway` constructor to accept explicit keyword dependencies rather than introspecting a service facade instance.
   - Clean up plan markdown trailing whitespace.

## Core Data Structures
No changes to core data structures.

## Public Interfaces
Public interfaces of `SDHLudusaviService` remain completely unchanged.

## Dependency Requirements
No new dependencies.

## Testing Strategy
Add/update targeted unit tests in:
- `tests/test_log_buffer.py`
- `tests/test_watchdog.py`
- `tests/test_exception_boundaries.py`
- `tests/test_gateway.py`
- `tests/test_architecture.py`
and verify all 361+ tests pass.
