# Critical Code Review Findings - 2026-05-17

## Scope
- **Commit:** `0bd7370965a67d13c3408645f95e60356369703a`
- **Subject:** Fast QAM Open and Ludusavi Config Cache Markers
- **Reviewer:** Principal Software Engineer (Gemini CLI)

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'fix: Synchronize Ludusavi adapter initialization and pending markers'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "The current implementation of `refresh_games` has two race conditions. First, `_ludusavi()` lazily initializes the adapter without a lock, and it is called by `_current_ludusavi_config_mtime_ns()` before the operation lock is acquired. Second, the `_pending_installed_app_ids` and `_pending_ludusavi_config_mtime_ns` markers are set outside the lock. Concurrent RPC calls can overwrite these pending markers before the first thread enters the lock, leading to inconsistent cache metadata being persisted after the refresh completes."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/service.py`
- **Function/Class/Lines:** `SDHLudusaviService.refresh_games`, `SDHLudusaviService._ludusavi`

## 🛠️ Requested Change
- Wrap the lazy initialization of `self._adapter` in `_ludusavi()` with a lock (either the existing `_operation_lock` or a new dedicated initialization lock).
- Move the assignment of `_pending_installed_app_ids` and `_pending_ludusavi_config_mtime_ns` inside the `_run_locked` context or pass them as arguments to `_refresh_statuses_unlocked` to ensure they are bound to the specific refresh operation that triggered them.

## ✅ Acceptance Criteria
- [ ] Adapter initialization is thread-safe.
- [ ] Pending cache markers are set and committed atomically relative to the refresh operation.
- [ ] Existing unit tests still pass.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified functions.
- Do not change the public API or return types.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Sanitize and limit installed_app_ids at the service boundary'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "The backend accepts an arbitrary `installed_app_ids` string from the frontend and persists it directly to `state.json`. This lacks sanitization and bounding. A large or malformed string can cause disk/memory bloat. This issue was previously identified in an internal review document added in the same commit but was not addressed in the implementation."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/service.py`
- **Function/Class/Lines:** `SDHLudusaviService.refresh_games`

## 🛠️ Requested Change
- Implement a maximum length check for the `installed_app_ids` string.
- Normalize the string in the backend (e.g., parse into a sorted list of integers and re-join, or hash the result) before comparison and persistence.
- Gracefully handle or reject malformed strings that do not look like a comma-separated list of integers.

## ✅ Acceptance Criteria
- [ ] `installed_app_ids` is validated/normalized before being used or stored.
- [ ] A test case exists for an oversized `installed_app_ids` input.
- [ ] A test case exists for malformed/non-numeric input.

## 🚫 AI Constraints & Scope Limits
- Do not change the frontend's responsibility for gathering the IDs; keep the sanitization in the backend.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'fix: Robust error handling for Ludusavi config mtime check'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "If `get_config_mtime_ns()` fails (e.g., config file missing or permission denied), `_current_ludusavi_config_mtime_ns` returns the previously cached marker. If this happens on the first run where no marker exists, it returns `None`, which might prevent a necessary refresh if `installed_app_ids` also happens to match. The failure to read the marker should ideally bias toward a refresh to ensure consistency."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/service.py`
- **Function/Class/Lines:** `SDHLudusaviService._current_ludusavi_config_mtime_ns`

## 🛠️ Requested Change
- Modify `_current_ludusavi_config_mtime_ns` or the logic in `refresh_games` to ensure that a failure to read the current config state triggers a refresh (or at least doesn't return a value that matches the 'stale' cached marker).
- Consider using a sentinel value or raising a specific exception that `refresh_games` can catch to force `needs_refresh = True`.

## ✅ Acceptance Criteria
- [ ] A missing or unreadable Ludusavi config file does not result in a false "cache hit".
- [ ] Regression test covers the case where `get_config_mtime_ns` raises an exception.

## 🚫 AI Constraints & Scope Limits
- Do not modify `pyludusavi` library; keep changes within the adapter or service.

---
