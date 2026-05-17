# Dev vs Current Code Review

Scope reviewed:

- Base commit: `66615b0ab6c6a865de571c94cef86b6cf166bba0`
- Current branch: `main` at `1effc24dbdf1a2eda5204d86c8944c4ec13af69d`
- Requested comparison: `dev` branch vs current branch
- Checkout note: no local or remote `dev` ref is present in this checkout, so this review covers commits reachable from `HEAD` after the base commit.

Commits reviewed:

- `23888a3` `fix(notifications): use app lifetime events`
- `cffe820` `docs(plan): add fast qam open caching strategy`
- `2fc6fd4` `feat(cache): implement app ID based cache invalidation`
- `8fe7ad2` `docs(session): record fast qam open caching implementation`
- `1effc24` `fix(rpc): update refresh_games signature in Plugin wrapper`

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Document or augment cache invalidation for Ludusavi config changes'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "The new startup fast path uses Steam installed app IDs to decide whether a cached Ludusavi game/status list is still valid. That is acceptable for ignoring games outside Steam/Game Mode scope, but it does not account for Steam-scoped Ludusavi configuration that can change while the Steam app/shortcut list remains unchanged. Examples include adding or removing an existing Steam game or Steam shortcut from Ludusavi's config, alias changes, custom-game changes, or ignore/configuration eligibility changes. In those cases `refresh_games(force=False, installed_app_ids=...)` can return stale `state.json` metadata indefinitely until a manual force refresh."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/service.py`, `src/index.tsx`
- **Function/Class/Lines:** `SDHLudusaviService.refresh_games` lines 302-327; `getInstalledAppIdsString` lines 121-141; `loadInitialData` lines 323-326

## 🛠️ Requested Change
- Add a backend-owned Ludusavi config modification marker, based on the active config file's `st_mtime_ns`, to augment the fast path.
- Keep the QAM fast path and Steam/Game Mode scope; do not expand the plugin into system-wide install discovery.
- Do not treat external backup-status changes as cache invalidators; backup and restore operation paths are expected to validate live Ludusavi state before acting.
- Add a regression test where the Steam installed app ID string is unchanged but the Ludusavi config marker changes, and verify the backend refreshes instead of returning stale cached game metadata.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add a backend test proving unchanged Steam app IDs do not permanently mask changed Ludusavi config metadata.
- [ ] Add or update a frontend/static test documenting the cache-token contract passed to `refresh_games`.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Validate and bound installed_app_ids before persisting cache metadata'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`installed_app_ids` crosses the frontend/backend RPC boundary as an arbitrary optional string and is persisted directly to `state.json`. Even if Decky RPCs are local, this is still untrusted input at the service boundary. A malformed or very large value can force needless refreshes, bloat persistent state, and degrade startup. The backend should own normalization and limits for cache metadata instead of trusting frontend formatting."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/service.py`, `src/index.tsx`
- **Function/Class/Lines:** `SDHLudusaviService.refresh_games` lines 302-327; `_save_state` lines 623-633; `getInstalledAppIdsString` lines 121-141

## 🛠️ Requested Change
- Parse and normalize the optional installed-app cache marker in the backend before comparison or persistence.
- Reject, truncate, or ignore malformed and oversized values rather than saving them verbatim.
- Prefer a compact deterministic representation, such as a sorted unique integer list hash, if the marker stays based on app IDs.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add tests for malformed input, duplicate IDs, non-numeric tokens, and an oversized cache marker.
- [ ] Confirm `state.json` never stores an unbounded raw frontend string for this field.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.

---
name: Code Review Action Item
about: Address feedback from a code review or tackle technical debt
title: 'refactor: Clear pending cache marker after failed refresh'
labels: 'tech-debt, code-review'
assignees: ''
---

## 🔍 The Review Finding
**Reviewer Comment / Rationale:**
> "`refresh_games` stores `_pending_installed_app_ids` before invoking the locked Ludusavi refresh, but the pending value is only cleared inside `_refresh_statuses_unlocked` after a successful refresh. If Ludusavi refresh fails, the stale pending value remains in memory. A later successful refresh that does not supply `installed_app_ids` can still persist that old value, corrupting the cache marker and making future cache decisions inconsistent."

## 📍 Exact Location
- **Original PR (if applicable):** #
- **File(s):** `py_modules/sdh_ludusavi/service.py`
- **Function/Class/Lines:** `SDHLudusaviService.refresh_games` lines 325-340; `_refresh_statuses_unlocked` lines 679-681

## 🛠️ Requested Change
- Clear `_pending_installed_app_ids` on every refresh completion path, including exceptions.
- Only commit a pending cache marker when it belongs to the refresh that actually succeeded.
- Add a regression test that triggers a failed refresh with a new marker, then a successful refresh without a marker, and verifies the failed marker is not persisted.

## ✅ Acceptance Criteria
- [ ] The code implements the requested change.
- [ ] Existing unit tests still pass (no regressions).
- [ ] Add a regression test covering failed refresh followed by successful refresh.

## 🚫 AI Constraints & Scope Limits
- Do not refactor code outside of the specified function/file.
- Do not change the public API or return types of the affected functions.
- Do not add new third-party libraries.
