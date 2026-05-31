# Plan: Resolve Additional Review Findings

## Problem Definition

1. **Fix 1: Add a real in-flight guard for update checks**
   - **Problem:** React component `PluginUpdateSection.tsx` only checks `isChecking` React state which isn't updated synchronously within the current render cycle. Concurrent effects can start multiple overlapping RPC checks.
   - **Resolution:** Add a `useRef<Promise<any> | null>(null)` guard named `inFlightCheck` to `PluginUpdateSection.tsx`. If it is active, return the existing promise instead of starting a new RPC call.

2. **Fix 2: Apply rate-limit cooldown to install revalidation**
   - **Problem:** `revalidate_plugin_update` in the backend skips checking/enforcing `service._update_rate_limited_until` and does not set the rate limit when it receives a 403 or 429 status code on manifest fetches.
   - **Resolution:** Route `revalidate_plugin_update` through the service and a new helper in `updater.py` which enforces the cooldown, blocks network calls, records rate limit cooldown resets, and returns `status: "failed"` with `retry_after` if rate-limited.

---

## Architecture Overview
Modifications are isolated to:
- Frontend: `src/components/PluginUpdateSection.tsx` (Promise-based in-flight guard)
- Service Wrapper: `py_modules/sdh_ludusavi/service.py` (Delegated method `revalidate_plugin_update`)
- Updater Logic: `py_modules/sdh_ludusavi/updater.py` (Rate limit cooldown check & revalidation wrapper)
- Main/RPC layer: `main.py` (Calling `self._service().revalidate_plugin_update`)

---

## Core Data Structures
No change to core structures.

---

## Public Interfaces

### Backend Service (`py_modules/sdh_ludusavi/service.py`)
```python
def revalidate_plugin_update(self, candidate: dict[str, Any]) -> dict[str, Any]:
    ...
```

### Backend Updater (`py_modules/sdh_ludusavi/updater.py`)
```python
def revalidate_plugin_update(service: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    ...
```

---

## Dependency Requirements
None.

---

## Testing Strategy
We will use TDD flow:

### TDD Phase 1: Failures (Red)
1. **Frontend in-flight guard:** Add a static / AST-based test checking for `inFlightCheck` usage, or add a frontend state check.
2. **Revalidation rate-limiting:**
   - Add a test in `tests/test_updater_service.py` asserting that calling `service.revalidate_plugin_update(candidate)` returns a failed status with `retry_after` and prevents `fetch_json` from being called if a rate-limit cooldown is active in the service.
   - Add a test in `tests/test_updater_service.py` asserting that if a revalidation receives a rate-limited response (403 or 429), it records the cooldown in the service and returns `retry_after`.

### TDD Phase 2: Implementation (Green)
1. Implement `inFlightCheck` in `PluginUpdateSection.tsx`.
2. Implement `revalidate_plugin_update` in `updater.py`, `service.py`, and `main.py`.
3. Verify all tests pass.
