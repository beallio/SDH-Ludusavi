# Thread-Safety: HistoryManager Lock + Registry Lock Coverage

> **Plan name:** `thread_safety_history_registry`
> **Completion marker:** create empty file `/tmp/sdh_ludusavi/thread_safety_history_registry_finished`, then enter the **review-notes loop** (final section — REQUIRED).
> **Implementation agent MUST use the `implementer` skill** (invoke `Skill: implementer` before starting work). All project commands run through `./run.sh`. Suite green at every commit, Conventional Commits.

## Context

Backend RPCs run on per-call daemon worker threads (`main.py` `_run_blocking`, lines ~450-545), so service code is genuinely multi-threaded. Two confirmed race conditions:

**Race 1 — HistoryManager has no lock.** `py_modules/sdh_ludusavi/history.py` (142 lines) contains zero synchronization. `record_history` (lines 37-81) mutates `self._game_history` from lifecycle worker threads (13 call sites in `lifecycle.py`, plus `service.py` `_skip`). Meanwhile `service._save_state` (service.py:349-369) — holding the **service's** `_state_lock`, a different lock — calls `self._history.get_history()` (history.py:33-35), which returns the **live dict reference**, and hands it to `json.dumps` inside `persistence.save_cache` (persistence.py:144-145). A mutation mid-serialization raises `RuntimeError: dictionary changed size during iteration`; the atomic tmp+`os.replace` write means no file corruption, but that save is silently lost.

**Race 2 — registry.refresh_games reads shared state outside `_state_lock`.** `py_modules/sdh_ludusavi/registry.py` has `_state_lock = threading.RLock()` (line 45) and uses it correctly in `load_cache`, `cache_payload`, `is_game_cache_current`, `match_game`, and the mutation phase of `_refresh_statuses_unlocked` (lines 218-257, which clears and repopulates `_games`/`_ids`/`_aliases`). But `refresh_games` (lines 109-165) performs these reads with **no lock**: `not self._games` (115), `self._installed_app_ids` (118), `self._ludusavi_config_mtime_ns` (129), `self._cached_games()` + `dict(self._aliases)` on the cache-hit path (136-137), `dict(self._aliases)` post-refresh (154), and `self._cached_games()` + `dict(self._aliases)` in the exception fallback (161-162). `_cached_games` (lines 275-276) iterates `self._games.values()` unlocked. A reader iterating while `_refresh_statuses_unlocked` repopulates under the lock can hit the same `RuntimeError`.

These races are not deterministically reproducible as failures; per the request, fix with locks plus deterministic structural tests (lock-instrumentation and copy-semantics tests — no flaky stress tests).

### Corrections/additions to the original writeup (verified against code)

- "give HistoryManager its own RLock, take it in record_history/get_history/load" — there is no `load` method; initial-history validation happens in `__init__` (lines 20-31), which runs before the object is shared across threads and builds fresh dicts via `_coerce_history_entry`, so it needs no lock.
- **The writeup misses a deadlock hazard:** `record_history` ends by calling `self._save_callback()` (history.py:81) = `service._save_state`, which acquires `service._state_lock` and then calls `history.get_history()`. If `record_history` held the new history lock **across** the callback, the lock order would be `history → service` on that path but `service → history` on the `_save_state` path — a classic ABBA deadlock between two threads. The fix MUST release the history lock **before** invoking `_save_callback()`. This is the most important detail in this plan.
- "two levels deep is enough" — confirmed: entry dicts are built fresh by `_coerce_history_entry` and **replaced wholesale**, never mutated in place (`history[field] = entry`, `history["last_operation"] = valid_entries[0]`), so `{game: dict(per_game)}` copies are sufficient for serialization safety.
- The writeup lists `_games`/`_installed_app_ids` reads; the same fix must also cover the unlocked `self._aliases` reads (lines 137, 154, 162) and `_cached_games()`.
- Out of scope (flag only, do not change): `refresh_after_operation` (registry.py:183-189) calls `_refresh_statuses_unlocked` without the coordinator's operation lock. Its internal mutations are still under `_state_lock`, so state stays consistent; wrapping it in `run_locked` could deadlock because callers may already be inside a `run_locked` callback and `coordinator._operation_lock` is a non-reentrant `threading.Lock` (coordinator.py:38).

## Prerequisites / protocol (before any code change)

1. Output the `AGENT_PROTOCOL_HANDSHAKE` block per CLAUDE.md §1 after read-only verification (`pwd`, `ls`, `git status`, inspect `pyproject.toml`/`run.sh`).
2. `git status --short` must be clean (CLAUDE.md §18); if not, report and stop.
3. Branch from `dev`: `git checkout dev && git checkout -b fix/thread-safety-history-registry`.
4. **Commit 0:** copy this plan into `docs/plans/thread_safety_history_registry.md`; commit `docs(plans): add history and registry thread-safety plan`.

## Validation — run for EVERY commit, in this order

```
./run.sh uv run pytest tests/test_history.py tests/test_registry.py -q   # targeted first
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest                                                   # full suite (~514 backend tests)
```

TDD (CLAUDE.md §9): for each commit below, write the new tests FIRST, run them to confirm they FAIL (red), then implement, confirm green, and commit tests+implementation together so every commit is green.

## Commit 1 — `fix(history): synchronize history state and return defensive copies`

### Red tests first — add to `tests/test_history.py` (follow its existing style: `DummyService`, `MagicMock` save_callback)

Add a small helper class at module level:

```python
class TrackingRLock:
    """RLock wrapper that records acquisition depth for lock-coverage tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.depth = 0
        self.acquisitions = 0

    def __enter__(self) -> "TrackingRLock":
        self._lock.acquire()
        self.depth += 1
        self.acquisitions += 1
        return self

    def __exit__(self, *exc: object) -> None:
        self.depth -= 1
        self._lock.release()
```

(needs `import threading` at top of the test file)

1. `test_get_history_returns_isolated_copy` — construct `HistoryManager(DummyService(), initial_history={}, save_callback=MagicMock())`; `record_history("Hades", "backup", "manual_backup", "backed_up")`; then:
   - `assert hm.get_history() is not hm._game_history`
   - take `snapshot = hm.get_history()`; mutate it: `snapshot["Hades"]["last_backup"] = None` and `snapshot["Other"] = {}`;
   - assert internal state unaffected: `hm.get_history()["Hades"]["last_backup"]["status"] == "backed_up"` and `"Other" not in hm.get_history()`.
   **RED today** (get_history returns the live reference).
2. `test_history_methods_acquire_lock` — construct manager, replace `hm._lock = TrackingRLock()`, call `record_history(...)` then `get_history()`, assert `hm._lock.acquisitions >= 2`. **RED today** (`_lock` does not exist → the production code never touches the tracker, acquisitions stays 0; the test must set the attribute then assert the count, so it fails on the count, not AttributeError).
3. `test_record_history_releases_lock_before_save_callback` — replace `hm._lock` with a `TrackingRLock`; pass a `save_callback` that records `hm._lock.depth` and calls `hm.get_history()` (mimicking `_save_state`); after `record_history(...)`, assert the recorded depth was `0` (lock fully released when the callback ran) and the callback saw the just-recorded entry. This pins the deadlock-avoidance contract deterministically.

### Implementation — `py_modules/sdh_ludusavi/history.py`

- `import threading`.
- In `__init__`, add `self._lock = threading.RLock()` (before the validation loop; the loop itself needs no lock — the object is not yet shared).
- `get_history` returns a two-level copy under the lock:

```python
def get_history(self) -> dict[str, dict[str, Any]]:
    """Return a copy of the complete validated game operation history."""
    # Entries are replaced wholesale (never mutated in place), so copying
    # the outer and per-game dicts is sufficient for a consistent snapshot.
    with self._lock:
        return {game: dict(history) for game, history in self._game_history.items()}
```

- `record_history`: keep entry construction (lines 47-58) outside the lock; wrap the mutation block (current lines 60-80: the `if game_name not in ...` creation, field selection, `history[field] = entry`, `_update_last_operation(history)`) in `with self._lock:`; call `self._save_callback()` **after** the `with` block, with this comment above the call:

```python
# Lock-ordering note: _save_callback (service._save_state) acquires the
# service _state_lock and re-enters get_history(). Invoke it only after
# releasing self._lock so the lock order is never history -> service,
# which would deadlock against _save_state's service -> history order.
```

### Post-implementation checks for this commit

- `grep -rn "get_history()" py_modules/ main.py` and confirm every consumer treats the result as read-only (known consumers: service.py:204 `get_game_history`, service.py:362 `_save_state`, registry's `_get_history` payload callback). None may rely on mutating the returned dict — if one does, stop and report instead of proceeding.
- Run the full suite; `tests/test_history.py`, `test_history_fixes.py`, `test_history_integration.py` must stay green (they read via `get_history()`; copies preserve content equality).

## Commit 2 — `fix(registry): cover refresh decision and cached reads with state lock`

### Red tests first — add to `tests/test_registry.py` (reuse its MagicMock construction pattern, see `test_registry_load_cache_and_payload`)

Reuse the same `TrackingRLock` helper (duplicate the small class in this test file with `import threading`; do not create a shared test util module unless one already exists).

1. `test_refresh_games_cache_hit_reads_under_state_lock` — build `GameRegistry(gateway, run_locked, log, save, get_history)` with MagicMocks (`get_history` returning `{}`); `gateway.current_config_mtime_ns.return_value = 12345`; `registry.load_cache({...})` with one game, `"installed_app_ids": "300,413150"`, `"ludusavi_config_mtime_ns": 12345` (copy the cache dict from `test_registry_load_cache_and_payload`); **then** swap `registry._state_lock = TrackingRLock()`; call `result = registry.refresh_games(force=False, installed_app_ids="300,413150")`; assert `result["dependency_error"] is None`, `len(result["games"]) == 1` (cache hit — `run_locked` not called: `run_locked.assert_not_called()`), and `registry._state_lock.acquisitions >= 1`. **RED today** (the cache-hit path never touches the lock).
2. `test_refresh_games_fallback_reads_under_state_lock` — same setup but `run_locked.side_effect = RuntimeError("boom")`; swap in `TrackingRLock`; call `refresh_games(force=True)`; assert `result["dependency_error"]` contains `"boom"`, `len(result["games"]) == 1` (served from cache), and `registry._state_lock.acquisitions >= 1`. **RED today.**

### Implementation — `py_modules/sdh_ludusavi/registry.py`

Restructure `refresh_games` (lines 109-165). Gateway I/O and normalization stay outside the lock; all reads of `_games`/`_installed_app_ids`/`_ludusavi_config_mtime_ns`/`_aliases` move under it. **Never hold `_state_lock` across the `self._run_locked(...)` call** — the decision block releases before delegating. Target shape:

```python
def refresh_games(self, force: bool = False, installed_app_ids: str | None = None) -> dict[str, object]:
    """Refresh statuses from the gateway if needed or requested."""
    normalized_installed_app_ids = _normalize_installed_app_ids(installed_app_ids)
    config_mtime_ns = self._gateway.current_config_mtime_ns()

    if config_mtime_ns is CONFIG_MARKER_READ_FAILED:
        committed_config_mtime_ns = None
    else:
        committed_config_mtime_ns = cast(int | None, config_mtime_ns)

    # Lock-ordering note: the decision reads and cached-payload reads must
    # hold _state_lock because _refresh_statuses_unlocked repopulates these
    # structures under it from coordinator-locked worker threads. The lock
    # is released before _run_locked so it never nests around the
    # coordinator's operation lock.
    with self._state_lock:
        needs_refresh = force or not self._games
        if not force and normalized_installed_app_ids is not None:
            if self._installed_app_ids != normalized_installed_app_ids:
                needs_refresh = True
                self.log("debug", "installed_app_ids changed, forcing refresh", "refresh")
        if config_mtime_ns is CONFIG_MARKER_READ_FAILED:
            needs_refresh = True
            self.log("debug", "Ludusavi config marker unavailable, forcing refresh", "refresh")
        if not force and self._ludusavi_config_mtime_ns != committed_config_mtime_ns:
            needs_refresh = True
            self.log("debug", "Ludusavi config changed, forcing refresh", "refresh")
        if not needs_refresh:
            cached_games = self._cached_games()
            cached_aliases = dict(self._aliases)

    if not needs_refresh:
        self.log("debug", "Returning cached game list", "refresh")
        return {
            "games": cached_games,
            "aliases": cached_aliases,
            "history": self._get_history(),
            "dependency_error": None,
        }

    self.log("debug", f"Forcing refresh_games (force={force})", "refresh")
    try:
        games = self._run_locked(
            "refresh", None,
            lambda: self._refresh_statuses_unlocked(
                normalized_installed_app_ids, committed_config_mtime_ns,
            ),
        )
        with self._state_lock:
            aliases = dict(self._aliases)
        return {
            "games": [game.to_dict() for game in games],
            "aliases": aliases,
            "history": self._get_history(),
            "dependency_error": None,
        }
    # Intentionally broad: fallback to cached statuses if refresh fails
    except Exception as exc:
        with self._state_lock:
            fallback_games = self._cached_games()
            fallback_aliases = dict(self._aliases)
        return {
            "games": fallback_games,
            "aliases": fallback_aliases,
            "history": self._get_history(),
            "dependency_error": str(exc),
        }
```

Notes for the implementer:
- Preserve the existing log messages and the `# Intentionally broad` comment exactly; only the locking structure changes. Behavior (return payloads, log text) must be identical.
- `self._get_history()` stays OUTSIDE `_state_lock` deliberately — it calls into HistoryManager (its own lock after Commit 1); keep the two locks un-nested.
- `_cached_games` acquires the lock itself so every caller is safe (RLock makes the nested acquisition from the cache-hit path above harmless):

```python
def _cached_games(self) -> list[dict[str, object]]:
    with self._state_lock:
        return [game.to_dict() for game in self._games.values()]
```

- Do NOT change `refresh_after_operation` (see Context). Do not add any new public accessors.

## Final steps (after Commit 2 is green)

1. Full validation suite one last time (all four gates + full pytest).
2. Session log `docs/agent_conversations/<today>_thread_safety_history_registry.json` (date, objective, files modified, tests added, design decisions — include the lock-ordering rationale — results); commit `docs: agent session log for history and registry thread safety`.
3. Do NOT push, tag, or open a PR (CLAUDE.md §14).
4. **Write the completion marker — REQUIRED:** `touch /tmp/sdh_ludusavi/thread_safety_history_registry_finished`
5. **Enter the review-notes loop — REQUIRED** (see next section).

## Review-notes loop (after the completion marker)

A reviewer will inspect the branch and leave notes at `/tmp/sdh_ludusavi/thread_safety_history_registry_review_notes.md`. After touching the finished marker:

1. Poll for that file (case-insensitive name match on `thread_safety_history_registry_review_notes*` in `/tmp/sdh_ludusavi/`), checking every ~30 seconds. Suggested per-iteration command (repeat the whole command while it prints `NOT_YET`, up to ~60 minutes total):

```bash
for i in $(seq 1 18); do if ls /tmp/sdh_ludusavi/ 2>/dev/null | grep -qi 'thread_safety_history_registry_review_notes'; then echo FOUND; exit 0; fi; sleep 30; done; echo NOT_YET
```

2. When found, read the notes file.
   - If it states **PASSED REVIEW** (and lists no required fixes): you are done — report completion and stop.
   - Otherwise: implement every item marked required (same validation gates per commit, Conventional Commits), then delete the consumed notes file (`rm /tmp/sdh_ludusavi/thread_safety_history_registry_review_notes.md`), touch `/tmp/sdh_ludusavi/thread_safety_history_registry_fixes_finished`, and **go back to step 1** to wait for the next round of notes.
3. If no notes appear within ~60 minutes of polling, stop and report that implementation is complete and review is pending.

## Risks / edge cases

- **Deadlock (the big one):** never call `self._save_callback()` while holding `history._lock`, and never hold `registry._state_lock` across `self._run_locked(...)`. Both constraints are encoded in the code sketches and pinned by tests (`test_record_history_releases_lock_before_save_callback`).
- `get_history()` now returns copies: any caller mutating the returned dict would silently lose writes — the Commit 1 grep check guards this (current consumers are read-only).
- Two concurrent `record_history` calls may each trigger a save; each save serializes a consistent snapshot under the new lock — duplicate saves are harmless (idempotent atomic writes).
- Architecture guard: `test_architecture.py` caps the `SDHLudusaviService` class span (<420); this plan does not touch service.py at all, so no risk — do not "improve" service.py while in there.
- `ruff format` may rewrap the sketched code — let it; only structure matters.

## Critical files

- `py_modules/sdh_ludusavi/history.py` (add lock + copy semantics)
- `py_modules/sdh_ludusavi/registry.py` (`refresh_games`, `_cached_games`)
- `tests/test_history.py`, `tests/test_registry.py` (new red tests; follow existing MagicMock construction patterns in each)
- Read-only reference: `py_modules/sdh_ludusavi/service.py:349-369` (`_save_state`), `main.py:450-545` (`_run_blocking` threading), `py_modules/sdh_ludusavi/coordinator.py` (non-reentrant operation lock), `py_modules/sdh_ludusavi/syncthing/watcher.py:406-409` (lock-note comment convention)
