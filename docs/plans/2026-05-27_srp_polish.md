# Plan: Polish Remaining SRP Cleanup

## Problem Definition
Tighten the boundaries of the decomposed managers of `SDHLudusaviService` by removing surprising compatibility overrides (like the lambda-based monkeypatching redirection) and ensuring that logging in `LudusaviGateway` is purely callback-based rather than reaching back into the facade.

## Architecture Overview
1. Remove the lambda redirection of `self._registry.match_game` from the service facade constructor.
2. Direct `gateway.py` to use `self._log` callback instead of calling `self._service.log(...)` inside `current_config_mtime_ns()`.
3. Clean stale dynamic lookup comments in `log_buffer.py`.
4. Update unit tests in `test_service.py` to target `service._registry.match_game` instead of `service._match_game` when simulating operation contention.

## Core Data Structures
No changes to core data structures.

## Public Interfaces
Public interfaces of `SDHLudusaviService` remain completely unchanged.

## Dependency Requirements
No new dependencies.

## Testing Strategy
1. Modify architecture tests to:
   - Verify `_registry_match_game` is not present in `service.py`.
   - Verify `self._registry.match_game` is not rebound in `service.py`.
   - Verify `self._service.log` is not used in `gateway.py`.
2. Add a gateway unit test verifying that `current_config_mtime_ns()` logs via callback on read failure.
3. Update operation contention tests in `test_service.py` to monkeypatch `service._registry.match_game`.
4. Run all tests via `./run.sh uv run pytest` and verify quality checks pass.
