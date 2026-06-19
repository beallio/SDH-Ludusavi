# Thermo-Nuclear Code Quality Review: `dev` vs `main`

**Branch:** `dev` (7422ea8)
**Base:** `main`
**Scope:** 59 code files changed, +1219/-1087 lines (code only, excludes docs/scripts)
**Reviewed:** Full diff, all changed files read in current state, deleted file content recovered from `main`

---

## Executive Summary

The `dev` branch contains persistence extraction, autoSyncStatus refactoring, debug logging feature, log-accuracy fixes, and settings mutation cleanup. The overall direction is **sound** — the persistence split, surface/renderer decomposition, and `contentLoadCoordinator` simplification are all genuine improvements. No file crossed the 1k-line threshold. No egregious spaghetti was added.

The main concerns are: **gutted architectural guard tests** that enforced layering and size constraints, a **copy-paste logging path bug** in the new persistence layer, and a handful of type-boundary regressions.

---

## 🔴 Structural Issues (High Priority)

### 1. Architectural guard tests gutted without replacement

Three test files were deleted and one was heavily trimmed:

| File | Before | After | What It Enforced |
|---|---|---|---|
| `test_architecture.py` | 126 lines | 33 lines | Service class size budget, no cross-layer imports, no duplicate sanitizers, updater state ownership, gateway isolation |
| `test_module_size_budgets.py` | 22 lines | **deleted** | Per-file LOC budgets for key frontend modules |
| `test_status_flow_diagram.py` | 81 lines | **deleted** | HTML flow diagram integrity |
| `test_architectural_constraints.py` | 22 lines | 35 lines | Trimmed but still exists |

The deleted content from `test_architecture.py` enforced critical invariants:

- `SDHLudusaviService` class span < 420 lines ([test_service_facade_class_size](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_architecture.py))
- Decomposed modules can't import from `service.py`
- Gateway can't reference `self._service`
- No `service: Any` in updater modules
- No raw updater state fields on service
- No duplicate `sanitize_game_name` definitions

`test_module_size_budgets.py` enforced per-file line budgets on the most complexity-prone frontend files (`autoSyncStatusSurface.tsx: 350`, `gameLifecycleController.tsx: 550`, etc.).

**These tests are exactly the kind of automated guardrails that prevent architectural drift.** If individual assertions became stale, the correct fix is to update the budgets — not delete the enforcement. The codebase now has no automated check preventing any module from growing unbounded.

> **Recommendation:** Restore deleted tests with updated assertions. Adjust size budgets to current reality + modest buffer. This is the cheapest and most effective architecture enforcement available.

---

### 2. `_warn_load` logs the wrong file path for settings errors

[persistence.py L203-205](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/persistence.py#L203-L205):

```python
def _warn_load(self, reason: str) -> None:
    state_file_path = self._cache_path  # ← always cache path
    LOGGER.warning("Ignoring SDH-ludusavi state at %s: %s", state_file_path, reason)
```

This is called from both the settings read path ([L161-162](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/persistence.py#L161-L162)) and the cache read path ([L169-179](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/persistence.py#L169-L179)). When a settings read fails, the warning misleadingly points to the cache file path. This is a copy-paste residue from the single-file era.

> **Fix:** Accept a `source: str` parameter or just drop the path from the message since the `reason` string already contains context.

---

## 🟡 Medium Priority

### 3. `settingsMutationRuntime.ts` — `MutateOptions` generic has 5 `any` fields

[settingsMutationRuntime.ts L158-177](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/settings/settingsMutationRuntime.ts#L158-L177):

```typescript
type MutateOptions<T, V> = {
  settingValue?: any;           // ← should be V
  settingPreviousValue?: any;   // ← should be V
  logFallbackValue?: any;       // ← should be V
  getPersistedValue: (res: T) => any;  // ← should return V
  // ...
};
```

The `T` and `V` type parameters create the *illusion* of type safety without actually constraining the data-flow. Every caller could pass mismatched types without a compile error.

Additionally, each of the 6 call sites passes ~6 near-identical log message strings ("`Executing toggle X to Y`", "`Late resolution of setX succeeded`", etc.) that follow a formula derivable from `settingKey`. This is boilerplate that a table-driven approach would eliminate.

**The code-judo move:** Replace `MutateOptions` with a small `MUTATION_TABLE` keyed by setting name, declaring `{ rpcCall, storeGetter, storeSetter, defaultFallback }` per entry. The `mutateSetting` function derives log messages from `settingKey`. Each setting mutation becomes a ~3-line table entry instead of a ~20-line options block. File shrinks from 443 to ~250-300 lines.

> **Not a blocker** — the current refactor is directionally correct and a genuine improvement over `main`. But it stopped halfway to the clean version.

### 4. Dead parameters in `SettingsMutationControllerOptions`

[settingsMutationRuntime.ts L28-29](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/settings/settingsMutationRuntime.ts#L28-L29):

```typescript
type SettingsMutationControllerOptions = {
  isMounted?: MountedRef;      // ← never read
  setBusyLabel?: (label: string | null) => void;  // ← never called
  // ...
};
```

Both `isMounted` and `setBusyLabel` are accepted but never used inside `createController()`. Tests even explicitly assert `setBusyLabel` is never called. This is dead code from a previous design.

> **Fix:** Remove both from the type.

### 5. Duplicated atomic-write-via-temp pattern in persistence.py

[JsonSettingsStore.write() L103-114](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/persistence.py#L103-L114) and [PersistenceManager.save_cache() L188-201](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/persistence.py#L188-L201) are nearly identical:

```python
# Both do:
temp_path = path.with_name(f".{path.name}.tmp")
temp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
os.replace(temp_path, path)
# with identical cleanup in except
```

> **Fix:** Extract `_atomic_json_write(path: Path, data: dict) -> None` and call from both.

### 6. Duplicated `isSyncthingStatus()` logic across surface and renderer

[autoSyncStatusSurface.tsx L48-53](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/surfaces/autoSyncStatusSurface.tsx#L48-L53) defines a private `isSyncthingStatus()` checking 4 statuses (including `syncthing_complete`). [autoSyncStatusRenderer.tsx L23-29](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/surfaces/autoSyncStatusRenderer.tsx#L23-L29) exports `isSyncthingActiveStatus()` checking only 3 (excluding `syncthing_complete`). The surface imports and re-exports `isSyncthingActiveStatus` but also has its own private version with different semantics.

The naming difference (`active` vs no qualifier) is the only hint. A new syncthing status would need to be added to both, and a developer would likely only find one.

> **Fix:** Consolidate into the renderer (or a shared util) with clear names: `isSyncthingActiveStatus` (3 statuses) and `isSyncthingStatus` (4 statuses, adds `complete`).

### 7. Duplicated `silentReasons` array in gameLifecycleController

[gameLifecycleController.tsx L255](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L255) and [L420](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx#L420) both define the identical array:

```typescript
const silentReasons = ["auto_sync_disabled", "operation_running", "unmatched_game", "not_processed"];
```

> **Fix:** Extract to a module-level constant.

### 8. Dead `service: Any` parameters in coordinator.py and log_buffer.py

Both [coordinator.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/coordinator.py) and [log_buffer.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/log_buffer.py) accept `service: Any` in their constructors and store it, but **never use the stored reference**. These are dead back-references from pre-decomposition.

> **Fix:** Remove the unused parameter and stored attribute from both.

---

## 🟢 Positive Changes

| Change | Verdict |
|---|---|
| **Persistence split** ([PersistenceManager](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/persistence.py#L117-L206)) | ✅ Settings and cache have different lifecycles — separating them with an inter-process lock is well-designed |
| **`contentLoadCoordinator.ts` simplification** ([11 lines](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/runtime/contentLoadCoordinator.ts)) | ✅ Purest "code judo" — complex coordinator reduced to a ready-flag |
| **autoSyncStatus surface/renderer split** | ✅ Surface owns state logic, renderer owns presentation. Independently testable |
| **Debug logging feature** | ✅ Clean layer-by-layer implementation: types → RPC → state → service → UI |
| **Log accuracy fixes** | ✅ Small, targeted, no branching added |
| **Test quality** | ✅ New tests verify actual behavior (log levels, surface resolution, state transitions), not coverage theater |

---

## ⚠️ Pre-Existing Issue (Not Introduced by This Branch)

### `main.py` `BaseException` catch swallows `SystemExit`

[main.py L443-445](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/main.py#L443-L445):

```python
except BaseException as exc:
    decky.logger.exception("%s failed", operation)
    return {"status": "failed", "message": str(exc)}
```

This catches `SystemExit` and `KeyboardInterrupt`, converting them to status dicts instead of propagating. This exists on `main` too, so it's not a regression — but it should be fixed (re-raise `SystemExit` and `KeyboardInterrupt`).

---

## 📊 File Size Check

No file crossed the 1000-line threshold. Size budgets are no longer enforced by tests (see Finding #1).

| File | Lines | Status |
|---|---|---|
| [LudusaviContent.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/components/qam/LudusaviContent.tsx) | 858 | ⚠️ Watch — approaching 1k |
| [gameLifecycleController.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/gameLifecycleController.tsx) | 560 | ✅ |
| [service.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/service.py) | 506 | ✅ |
| [syncthingMonitor.ts](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/controllers/syncthingMonitor.ts) | 491 | ✅ |
| [main.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/main.py) | 493 | ✅ |
| [settingsMutationRuntime.ts](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/settings/settingsMutationRuntime.ts) | 443 | ✅ |

---

## Approval Assessment

| Criterion | Status |
|---|---|
| No structural regression | 🔴 Gutted architectural guard tests |
| No missed dramatic simplification | 🟡 `settingsMutationRuntime` table-driven opportunity (directionally correct but halfway) |
| No unjustified file-size explosion | ✅ |
| No spaghetti growth | ✅ |
| No hacky/magical abstractions | ✅ |
| No unnecessary wrapper/cast churn | 🟡 5 `any` fields in `MutateOptions`, dead `service: Any` params |
| No boundary leaks | ✅ |
| No missed decomposition | ✅ |

### Verdict: **Conditional approval — two blockers**

1. **Restore architectural guard tests** — The deleted/gutted tests in `test_architecture.py` and `test_module_size_budgets.py` are a structural regression. Update the assertions, don't delete the enforcement.
2. **Fix `_warn_load` path bug** — [persistence.py L204](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/py_modules/sdh_ludusavi/persistence.py#L204) always logs the cache path even for settings errors. This is a correctness bug in a new file.

### Prioritized action items:

| Priority | Item | Effort |
|---|---|---|
| 🔴 **Blocker** | Restore `test_architecture.py` deleted assertions and `test_module_size_budgets.py` with updated thresholds | ~30 min |
| 🔴 **Blocker** | Fix `_warn_load` to log the correct source path | ~5 min |
| 🟡 **Should fix** | Extract `_atomic_json_write` helper in persistence.py | ~10 min |
| 🟡 **Should fix** | Remove dead `isMounted`/`setBusyLabel` from `SettingsMutationControllerOptions` | ~5 min |
| 🟡 **Should fix** | Remove dead `service: Any` from `coordinator.py` and `log_buffer.py` | ~10 min |
| 🟡 **Should fix** | Consolidate `isSyncthingStatus` / `isSyncthingActiveStatus` duplication | ~10 min |
| 🟡 **Should fix** | Extract `silentReasons` constant in `gameLifecycleController.tsx` | ~2 min |
| 🟢 **Future PR** | Table-driven `settingsMutationRuntime` to replace `MutateOptions` boilerplate | ~2 hrs |
| 🟢 **Future PR** | Fix pre-existing `BaseException` catch in `main.py` | ~10 min |
| 🟢 **Future PR** | Type `MutateOptions.settingValue` etc. as `V` instead of `any` | ~15 min |
