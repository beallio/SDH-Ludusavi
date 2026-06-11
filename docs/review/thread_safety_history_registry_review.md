# Review: thread_safety_history_registry (branch `fix/thread-safety-history-registry`)

**Date:** 2026-06-11
**Plan:** docs/plans/thread_safety_history_registry.md
**Verdict:** PASSED REVIEW — first pass, no fixes required.

## Verified against the plan

- **Commit structure** (`bc17c8f`..`eef1a71`): plan doc, `fix(history)`, `fix(registry)`, session log — matches the planned sequence; working tree clean. (A small bonus test-hygiene commit `9117240` removed the stale `_refreshed_once` assignment flagged as optional follow-up in the previous review.)
- **history.py:** `threading.RLock` added as `self._lock`; `get_history()` returns a two-level copy (`{game: dict(history) ...}`) under the lock with the entries-replaced-wholesale justification comment; `record_history` performs all `_game_history` mutations (create-if-missing, field assignment, `_update_last_operation`) inside the lock and invokes `self._save_callback()` **after** releasing it, with the exact lock-ordering comment from the plan — the history→service / service→history ABBA deadlock is structurally prevented.
- **registry.py:** the `refresh_games` decision reads (`not self._games`, `_installed_app_ids`, `_ludusavi_config_mtime_ns`), the cache-hit payload (`_cached_games()` + `dict(self._aliases)`), the post-refresh aliases read, and the exception-fallback reads are all under `_state_lock`; the lock is released before `self._run_locked(...)` so it never nests around the coordinator's non-reentrant operation lock; `_cached_games()` now acquires `_state_lock` internally; log messages and the `# Intentionally broad` comment preserved; `refresh_after_operation` untouched as required.
- **Tests:** all five planned tests present and passing — `test_get_history_returns_isolated_copy`, `test_history_methods_acquire_lock`, `test_record_history_releases_lock_before_save_callback` (asserts `tracker.depth == 0` inside the save callback and that the callback observes the just-recorded entry), `test_refresh_games_cache_hit_reads_under_state_lock` (incl. `run_locked.assert_not_called()`), `test_refresh_games_fallback_reads_under_state_lock`. The `TrackingRLock` helper matches the planned design.
- **Consumer safety:** `grep get_history()` across `py_modules/` and `main.py` shows only read-only consumers (service.py:204 `get_game_history`, service.py:362 `_save_state`, registry `_get_history` payload assembly) — copy semantics break nothing.
- **Quality gates:** `ruff check` clean, `ruff format --check` clean (108 files), `ty check` clean, **519/519 backend tests pass** (514 prior + 5 new).
- **Session log:** `docs/agent_conversations/2026-06-11_thread_safety_history_registry.json` committed. Completion marker written; PASSED notes delivered to `/tmp/sdh_ludusavi/thread_safety_history_registry_review_notes.md`.

No outstanding items. Nothing pushed; no PR opened.
