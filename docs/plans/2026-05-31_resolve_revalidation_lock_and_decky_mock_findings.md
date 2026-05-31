# Plan: Resolve Revalidation Lock and Decky Mock Findings

## Problem Definition
We need to address two specific findings from the recent review:

1. **Do not hold state lock during GitHub revalidation fetch:**
   - **Problem:** Currently, in `py_modules/sdh_ludusavi/updater.py` (specifically inside `revalidate_plugin_update`), the service's `_state_lock` is held for the duration of the entire revalidation process. This includes blocking network/HTTP operations via `fetch_json(url)` and release validation. Since network calls can be slow or hang, this locks the updater's settings and cache operations unnecessarily.
   - **Resolution:** Split `revalidate_plugin_update` into locked and unlocked phases. Specifically:
     - Acquire `_state_lock` to check if `_update_rate_limited_until` is active. If active, immediately return the rate-limited response (blocking the network call).
     - Release/exit the `_state_lock` before executing the network requests or validations.
     - If the network call completes or encounters a rate-limiting response (403/429), reacquire `_state_lock` to update `_update_rate_limited_until` and serialize the state.

2. **Make updater service tests independent of global decky import state:**
   - **Problem:** `tests/test_updater_service.py` has tests like `test_decky_settings_store_defaults` that import classes from `main` (which expects the `decky` module to be loaded at import-time). If run in isolation, this fails with `ModuleNotFoundError: No module named 'decky'` because `decky` is a mock that only gets injected into `sys.modules` if `test_main.py` is imported first.
   - **Resolution:** Import and use the existing fake decky module utility/mock mechanism within `tests/test_updater_service.py` so that it can run successfully in isolation.

---

## Architecture Overview
- We will modify `py_modules/sdh_ludusavi/updater.py` to ensure `revalidate_plugin_update` does not hold `_state_lock` during the network call.
- We will modify `tests/test_updater_service.py` to inject the fake `decky` module on import/startup, or mock it appropriately to avoid `ModuleNotFoundError` when run in isolation.

---

## Core Data Structures
No new data structures are introduced.

---

## Public Interfaces
No changes to public API or return signatures.

---

## Dependency Requirements
None.

---

## Testing Strategy
We will use the strict TDD mandate:
1. Write a failing test in `tests/test_updater_service.py` verifying that:
   - Run `pytest tests/test_updater_service.py` in isolation from a clean Python process without failures due to missing `decky`.
   - The state lock is NOT held during the network fetch phase of `revalidate_plugin_update`. We can mock `fetch_json` to inspect or assert if `service._state_lock.locked()` is `False` during the network call.
2. Implement the changes to make the tests pass.
3. Validate all checks (`ruff`, `ty`, `pytest`, `pnpm run verify`, etc.).
