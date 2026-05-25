# Code Review: SDH-ludusavi
**Date:** Sunday, May 24, 2026
**Reviewer:** Gemini CLI (Advanced Engineering & Security Audit Model)

## 1. Logical Errors & Edge Cases

### [Medium] Hardcoded UID in Environment Discovery
* **File & Function/Line:** `py_modules/sdh_ludusavi/ludusavi.py:19` (`_ludusavi_env`)
* **Description:** The `XDG_RUNTIME_DIR` is hardcoded to `/run/user/1000`. While this matches the default `deck` user on SteamOS, it will fail or cause permission issues if the plugin is run under a different UID or on a standard Linux distribution.
* **Vulnerable Code:**
```python
if "XDG_RUNTIME_DIR" not in os.environ:
    env["XDG_RUNTIME_DIR"] = "/run/user/1000"
```
* **Proposed Fix:**
```python
if "XDG_RUNTIME_DIR" not in os.environ:
    env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
```

### [Low] Inconsistent Task Cancellation in `_run_blocking`
* **File & Function/Line:** `main.py:236` (`_run_blocking`)
* **Description:** The implementation uses `asyncio.shield(future)` but then immediately calls `future.cancel()` in the `except asyncio.CancelledError` block. This defeats the purpose of the shield and can lead to confusion about whether the worker is truly protected or being forcibly stopped.
* **Vulnerable Code:**
```python
try:
    return await asyncio.shield(future)
except asyncio.CancelledError:
    # ...
    future.cancel()
    raise
```
* **Proposed Fix:** If the worker must finish to ensure system state integrity (e.g. releasing locks), the `future.cancel()` should be avoided, or the code should explicitly await the worker's completion/cleanup.

---

## 2. Security Vulnerabilities

### [Medium] Potential Race Condition in `chmod`
* **File & Function/Line:** `main.py:194` (`_ensure_private_directory`)
* **Description:** Calling `chmod` after `mkdir` on a potentially attacker-controlled path (like `/tmp`) can be vulnerable to symlink attacks where an attacker replaces the directory with a symlink between the two calls, causing the `chmod` to apply to an unintended target.
* **Vulnerable Code:**
```python
path.mkdir(parents=True, mode=0o700, exist_ok=True)
path.chmod(0o700)
```
* **Proposed Fix:** Ensure the path is created with the correct mode initially and avoid redundant `chmod` calls, or verify the file type before applying permissions.

---

## 3. Performance Bottlenecks

### [Medium] Inefficient Process Tree Discovery
* **File & Function/Line:** `py_modules/sdh_ludusavi/service.py:1645` (`_process_tree`)
* **Description:** The process tree discovery iterates over the entire `/proc` directory and opens `/proc/<pid>/status` for every process on the system every time a game starts or exits. This O(N) operation can introduce latency during the time-sensitive "launch gate" phase.
* **Vulnerable Code:**
```python
for entry in entries:
    if not entry.isdigit():
        continue
    ppid = _read_ppid(entry)
```
* **Proposed Fix:** Consider using more targeted process discovery or caching the tree structure if the operations occur in rapid succession.

---

## 4. Concurrency & State Issues

### [High] Global Mutable State in Frontend
* **File & Function/Line:** `src/index.tsx:180-190`
* **Description:** Critical UI-related objects like `autoSyncStatusBrowserView` are stored as module-level globals. This can cause stale references or resource leaks if the plugin is re-initialized by Decky without a clean process exit.
* **Vulnerable Code:**
```typescript
let autoSyncStatusBrowserView: AutoSyncStatusBrowserView | null = null;
let autoSyncStatusBrowserViewOwner: AutoSyncStatusBrowserViewOwner | null = null;
```
* **Proposed Fix:** Encapsulate these resources within the `LudusaviStateStore` or a dedicated manager class tied to the plugin's lifecycle.

---

## 5. Code Quality & Best Practices

### [Best Practice] Fragile Steam UI Interop
* **File & Function/Line:** `src/index.tsx:327` (`ensureAutoSyncStatusBrowserView`)
* **Description:** The code relies heavily on internal Steam UI property names and structures which are not officially documented and subject to change without notice.
* **Proposed Fix:** Centralize all "Steam Internals" access into a single utility module with robust error handling and fallback paths to minimize the impact of Steam client updates.
