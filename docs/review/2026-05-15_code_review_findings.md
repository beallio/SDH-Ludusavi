# Code Review Findings - 2026-05-15

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: replace busy-wait in _run_blocking with asyncio.Future'
labels: 'tech-debt, performance'
assignees: 'beallio'
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> The current `_run_blocking` implementation in `main.py` uses a busy-wait loop (`while True: await asyncio.sleep(0.05)`) to check for results from a background thread. This is CPU-inefficient and non-idiomatic. It should use `asyncio.to_thread` (if on Python 3.9+) or a `Future` combined with `loop.call_soon_threadsafe`.

## 📍 Exact Location
- **File(s):** `main.py`
- **Function/Class/Lines:** `_run_blocking`

## 🛠️ Requested Change
- Refactor `_run_blocking` to use `asyncio.to_thread` if available, or a thread-safe `asyncio.Future` to signal completion without polling.

## ✅ Acceptance Criteria
- [ ] No more `while True` or `asyncio.sleep` in `_run_blocking`.
- [ ] Operations still complete successfully and return results to the frontend.
- [ ] Unit tests for blocking calls (e.g., `test_concurrent_operations_are_rejected_by_thread_safe_lock`) still pass.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'fix: align backend error responses with frontend type expectations'
labels: 'bug, tech-debt'
assignees: 'beallio'
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> The `_call` wrapper in `main.py` returns a dictionary with `{"status": "skipped", "reason": "..."}` when an `OperationLockedError` occurs. However, the frontend `RefreshResult` and `Settings` types do not account for this structure. This leads to TypeScript being bypassed at runtime and potential UI crashes or unexpected states if a refresh is blocked by an auto-sync.

## 📍 Exact Location
- **File(s):** `main.py`, `src/index.tsx`
- **Function/Class/Lines:** `Plugin._call` and various `callable` definitions.

## 🛠️ Requested Change
- Update `_call` to return a consistent error structure that the frontend can handle, or update frontend types and logic to explicitly check for the `skipped` or `failed` status before processing results.

## ✅ Acceptance Criteria
- [ ] Frontend handles "skipped" operations (due to lock) without breaking the game list or settings state.
- [ ] TypeScript definitions for RPC results reflect the possibility of an error/skipped response.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'perf: parallelize artwork application for Ludusavi shortcut'
labels: 'tech-debt, performance'
assignees: 'beallio'
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> `applyLudusaviArtworkToShortcut` in `shortcutArtwork.ts` uses a `for...of` loop with `await` on every asset application. This results in sequential network/disk requests and SteamClient calls. Since these are independent, they should be parallelized to speed up the launch process.

## 📍 Exact Location
- **File(s):** `src/shortcutArtwork.ts`
- **Function/Class/Lines:** `applyLudusaviArtworkToShortcut`

## 🛠️ Requested Change
- Use `Promise.all` to apply all artwork assets in parallel.

## ✅ Acceptance Criteria
- [ ] All four artwork types (grid_p, grid_l, hero, logo) are still applied.
- [ ] Launch process remains stable.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: remove redundant imports in logging hot-path'
labels: 'tech-debt, performance'
assignees: 'beallio'
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> `_decky_log` in `service.py` performs a `try: import decky` on every single log call. While Python caches imports, this is still unnecessary overhead and unconventional in a hot path (especially during operations with many log entries).

## 📍 Exact Location
- **File(s):** `py_modules/sdh_ludusavi/service.py`
- **Function/Class/Lines:** `_decky_log`

## 🛠️ Requested Change
- Move the `decky` import to the top of the file or use a module-level cached variable to store the result of the import attempt.

## ✅ Acceptance Criteria
- [ ] `decky.logger` is still used when available.
- [ ] Import only happens once or is significantly more efficient.
