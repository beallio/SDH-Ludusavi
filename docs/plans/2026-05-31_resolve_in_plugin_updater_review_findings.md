# Plan: Resolve In-Plugin Updater Review Findings

## Problem Definition
The in-plugin updater feature has three distinct issues identified in the code review (saved in `/tmp/sdh_ludusavi/feat_in_plugin_updater_review_findings.md`):

1. **Fix 1: Pass Decky installer arguments in the expected order**
   - **Problem:** `utilities/install_plugin` expects `artifact` (the URL string) first, and `name` (the plugin ID `"SDH-Ludusavi"`) second. The current implementation in `src/utils/deckyInstaller.ts` passes the plugin ID first and the URL second, which breaks one-click installation and prevents update tracking.
   - **Resolution:** Change both `callable` and `call` fallback invocations to pass arguments as: `url, EXPECTED_PLUGIN_NAME, version, sha256, installType`.

2. **Fix 2: Preserve pending update install metadata until next plugin load**
   - **Problem:** When `record_update_install_requested()` is called, it writes the `pending_update_install` cache and then calls `get_update_check_context()`. However, `get_update_check_context()` immediately executes `reconcile_pending_update_install()`. Since the running version does not yet match the pending update version, reconciliation clears the pending metadata immediately within the same RPC call.
   - **Resolution:** Split "read context" from "startup reconciliation". Do not call `reconcile_pending_update_install` in `record_update_install_requested()` or inside regular `get_update_check_context()` reads unless explicitly directed (e.g., only on startup/first load).

3. **Fix 3: Require release manifest asset names to match the release tag**
   - **Problem:** `validate_release_candidate()` accepts any asset ending in `.manifest.json` as the manifest, ignoring whether the prefix matches the release tag. For example, `wrong.manifest.json` would be accepted if it matches the schema.
   - **Resolution:** Validate that the manifest filename matches the expected pattern `SDH-Ludusavi-<tag>.manifest.json` (where tag format matches `vX.Y.Z`, `vX.Y.Z-dev.g<sha>`, or `vX.Y.Z-dev.<sha>`).

---

## Architecture Overview
The fixes require modifying:
- Frontend: `src/utils/deckyInstaller.ts` (argument order correction)
- Backend: `py_modules/sdh_ludusavi/updater.py` (strict manifest filename checking, reconciliation logic refinement)
- Backend: `py_modules/sdh_ludusavi/service.py` (splitting startup reconciliation from regular context checks)
- Main/RPC entry points (`main.py`)

No new dependencies are required. Caches and temp files remain under `/tmp/sdh_ludusavi`.

---

## Core Data Structures
No change to core structures. The `UpdateCandidate` and `PendingUpdateInstall` schemas remain the same.

---

## Public Interfaces

### Frontend (`src/utils/deckyInstaller.ts`)
No signature change. Inside `invokeDeckyInstaller`:
```typescript
// For callable:
const result = await decky.callable("utilities/install_plugin")(url, EXPECTED_PLUGIN_NAME, version, sha256, installType);
// For call fallback:
const result = await decky.call("utilities/install_plugin", url, EXPECTED_PLUGIN_NAME, version, sha256, installType);
```

### Python Service/Updater (`py_modules/sdh_ludusavi/service.py`)
Add an explicit startup hook or initialization sequence method `initialize_updater_on_startup(current_version: str)` to the service. Or, refine `get_update_check_context(current_version: str, reconcile_on_startup: bool = False)` so that reconciliation only runs when `reconcile_on_startup` is explicitly requested, which we will call from the frontend/backend plugin load sequence exactly once on startup/first load.

---

## Dependency Requirements
None.

---

## Testing Strategy
We will use Red-Green-Refactor TDD flow.

### TDD Phase 1: Failures (Red)
1. **Fix 3 (Manifest name check):** Add tests to `tests/test_updater.py` asserting that releases with `wrong.manifest.json` are rejected.
2. **Fix 2 (Reconciliation persistence):** Add tests to `tests/test_updater_service.py` asserting that calling `record_update_install_requested` retains the pending update in cache when calling `get_update_check_context()` afterwards, and only clears it when an explicit reconciliation/startup check runs with a mismatching version.
3. **Fix 1 (Frontend argument order):** Add static/mock tests in `tests/test_frontend_static.py` checking the mock call arguments of `utilities/install_plugin`.

### TDD Phase 2: Implementation (Green)
1. Implement manifest name validation in `updater.py`.
2. Decouple reconciliation from standard context reading in `service.py` / `main.py`.
3. Fix the frontend installer adapter call in `src/utils/deckyInstaller.ts`.

### Validation
Run the full verification suite:
- `ruff`
- `ty`
- `pytest`
- `pnpm run verify`
- `check_tdd.sh`
