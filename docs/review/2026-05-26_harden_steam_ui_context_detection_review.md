# Code Review: Harden SteamUI QAM Game Context Detection

**Date:** 2026-05-26  
**Auditor:** Principal Software Engineer & Security Auditor  
**Commit Audited:** `7214e80` (`fix(qam): harden SteamUI context detection`)

---

## 🔍 Code Review Findings

### 1. Logical Errors & Edge Cases
* **Analysis:** The resolver flow inside `getFocusedSteamGameSession` correctly manages game names and IDs. By deferring an appID-only session (e.g., when the name is not yet present in the local stores) into `appIDOnlyFallback`, it allows the candidate loop to still query React Fiber nodes for rich game names (crucial for matching non-Steam games in Ludusavi by name). If the React candidate loop finishes without resolving a name, the appID-only fallback is safely returned.
* **DOM Traversal:** The explicit DOM context lookup uses bidirectional traversal:
  ```typescript
  const appElement = element?.closest(selector) ?? element?.querySelector(selector) ?? null;
  ```
  This is extremely robust as it detects attributes when the focus is applied directly to child elements (searching upward via `closest()`) or to parent container cards (searching downward via `querySelector()`).
* **Result:** **No logical or edge-case bugs identified.**

### 2. Security Vulnerabilities
* **Analysis:** DOM selectors and route parameters are matched strictly against a clean numeric regex (`STEAM_UI_APP_ROUTE_PATTERN`). No execution of arbitrary script or unsafe HTML injections occurs.
* **Result:** **No security vulnerabilities identified.**

### 3. Error Handling
* **Analysis:** Null-safe operators (`element?.closest`, `appElement?.getAttribute`, `href.match` fallback) are correctly chained. If elements are unmounted or attributes are missing during transitions, the methods resolve to `null` safely without raising JS runtime exceptions.
* **Result:** **No error handling issues identified.**

### 4. Performance Bottlenecks
* **Analysis:** 
  * Ignored root elements (`BODY` / `HTML`) prevent walking the entire React component tree when the window loses focus.
  * `doc.querySelectorAll(":hover")` is limited to the 4 most specific elements via `.reverse().slice(0, 4)`.
  * Candidate lists are capped at 64 elements (`STEAM_UI_REACT_CANDIDATE_MAX_COUNT`).
  * Combined, these constraints keep DOM and Fiber traversal extremely light.
* **Result:** **No performance bottlenecks identified.**

### 5. Concurrency / State Issues
* **Analysis:** The React Fiber tree traversal is protected by `visitedFibers = new Set<any>()`. Cyclic loops created by custom React tree overrides will terminate immediately upon re-visiting a fiber node, preventing infinite loops.
* **Result:** **No concurrency or state issues identified.**

### 6. Code Quality & PEP 8
* **Analysis:** The added static assertion test in `tests/test_frontend_static.py` validates all aspects of the new design, including:
  * Constants presence.
  * Tag filtering (`BODY` / `HTML`).
  * Bidirectional lookup (`closest` and `querySelector`).
  * Deferred `appIDOnlyFallback` resolution order.
  * Visited-fiber cycle guards.
* **Result:** **No quality control deviations identified.**

---

## ✅ Conclusion

The changes introduced in commit `7214e80` **correctly resolve the React props scraping vulnerability** and **fully satisfy all requirements** outlined in the implementation plan. No issues were found across any of the audited dimensions.
