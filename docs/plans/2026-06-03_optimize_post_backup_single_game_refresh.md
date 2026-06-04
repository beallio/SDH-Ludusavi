# Plan: Optimize Post-Backup Single Game Refresh

**Revision:** v3 (handoff-hardened — all ambiguous line numbers and subclass implications resolved)
**Pyludusavi `games=` filter resolution:** Confirmed — passes names as positional CLI args. Ludusavi resolves aliases to canonical titles internally. Our `game.name` (from Ludusavi's own JSON output) is always a canonical match.

---

## 1. Problem Definition
When a game save is backed up or restored (automatically on exit via `backup_game_on_exit` or manually via QAM `force_backup` / `force_restore`), the backend updates its UI cache by calling `self.dependencies.registry.refresh_after_operation()`.

Currently, `refresh_after_operation()` calls `_refresh_statuses_unlocked()` with no filters. This forces a complete, full-library scan by running:
1. `self._client.backup(preview=True)` for all games.
2. `self._client.backups_list()` for all games.

On Steam Decks with large libraries, this introduces perceptible UI latency (the status overlay shows the old state longer than necessary). The refresh must be optimized to scan **only** the single game that was operated on and merge its updated status into the cache.

Additionally, `force_restore` currently does **not** call `refresh_after_operation` at all, leaving the cache stale after a manual restore. This plan adds the missing refresh call to `force_restore` and optimizes it identically.

---

## 2. Architecture Overview
The optimization extends three backend modules:
1. **Ludusavi Adapter** (`PyludusaviAdapter`): Accept an optional `game_names` list to restrict CLI calls.
2. **Game Registry** (`GameRegistry`): Pass an optional single game name to `refresh_after_operation`. Implement a "Targeted Merge Mode" in `_refresh_statuses_unlocked` that selectively updates the target game's status and steam ID mapping without executing a destructive `.clear()`.
3. **Lifecycle Manager** (`GameLifecycleManager`): Update all three calling sites (`backup_game_on_exit`, `force_backup`, `force_restore`) to supply the target game name.

```
[GameLifecycleManager]
      |
      +---> backup_game_on_exit(game_name)  ──┐
      +---> force_backup(game_name)          ──┤
      +---> force_restore(game_name)  [NEW]  ──┘
                  |
                  +---> executes real operation via pyludusavi
                  |
                  +---> calls registry.refresh_after_operation(game_name) [OPTIMIZED]
                              |
                              v
            [GameRegistry._refresh_statuses_unlocked(game_name)]
                  |
                  +---> calls PyludusaviAdapter.refresh_statuses(game_names=[game_name])
                  |           |
                  |           +---> runs CLI with games=[game_name] filter
                  |
                  +---> Merges updated game status into self._games dict (preserves other games)
                  +---> Skips alias rebuild when config mtime is unchanged
                  +---> Handles empty scan results with warning log
                  +---> Persists cache JSON to disk
```

---

## 3. Core Data Structures
No changes to existing structural data types. The registry dict mapping holds:
- `self._games`: `dict[str, GameStatus]` mapping the sanitized game title to its `GameStatus` object.
- `self._ids`: `dict[str, str]` mapping steam ID (as string) to the sanitized game title.

---

## 4. Public Interfaces

### 4.1 `py_modules/sdh_ludusavi/types.py` (line 8)
Update `LudusaviAdapter` protocol:
```python
def refresh_statuses(self, game_names: list[str] | None = None) -> list[dict[str, object]]: ...
```

### 4.2 `py_modules/sdh_ludusavi/ludusavi.py` (line 65)
Update `PyludusaviAdapter.refresh_statuses` signature to accept `game_names: list[str] | None = None`.
Forward `games=game_names` to both `self._client.backup(...)` and `self._client.backups_list(...)`.

### 4.3 `py_modules/sdh_ludusavi/registry.py`
- `refresh_after_operation` (line 182): add `game_name: str | None = None` parameter, forward to `_refresh_statuses_unlocked`.
- `_refresh_statuses_unlocked` (line 190): add `game_name: str | None = None` parameter.

### 4.4 `py_modules/sdh_ludusavi/lifecycle.py`
- `backup_game_on_exit` (line 272): pass `game.name` to `refresh_after_operation`.
- `force_backup` (line 306): pass `game.name` to `refresh_after_operation`.
- `force_restore` (line 332): **insert** `self.dependencies.registry.refresh_after_operation(game.name)` immediately after the `history.record_history(...)` call on line 332, before the `return` on line 333. This is currently missing entirely.

---

## 5. Dependency Requirements
- No new external dependencies required.
- `pyludusavi` 0.2.3 already supports `games=[...]` on `backup(preview=True)` and `backups_list()`. The filter passes names as positional CLI args; Ludusavi resolves aliases to canonical titles internally. Verified via `py_modules/pyludusavi/main.py:243-244,343-344`.

---

## 6. Testing Strategy & Scenarios

All new tests in `tests/test_registry.py` (registry merge behavior) and `tests/test_ludusavi.py` (adapter forwarding). Existing lifecycle tests in `tests/test_service.py` are extended for call-site assertions. One fix needed in `tests/test_history_fixes.py` (see 6.7).

### 6.1 Adapter-Level: Targeted Scan Filtering (`tests/test_ludusavi.py`)
Add a test using the existing `FakeLudusaviClient` + `PyludusaviAdapter.__new__` pattern:
1. Call `adapter.refresh_statuses(game_names=["Hades"])`.
2. Assert `client.requested_games == ["Hades"]` for both `backup` and `backups_list` calls.

### 6.2 Registry-Level: Merge Mode Assertions (`tests/test_registry.py`)
Add `test_targeted_refresh_merges_single_game`:
1. Pre-populate `registry._games` with `GameStatus("Hades", ...)` and `GameStatus("Portal", ...)`.
2. Mock `gateway.get_adapter().refresh_statuses(game_names=["Hades"])` to return `[{"name": "Hades", "has_backup": False, ...}]` (status changed).
3. Call `registry.refresh_after_operation(game_name="Hades")`.
4. Assert:
   - `"Portal"` remains in `_games` untouched.
   - `"Hades"` has `has_backup=False` (updated from mock).
   - `len(registry._games) == 2`.
   - Steam ID mapping updated correctly (old removed, new inserted).
   - `registry._save_state` was called.

### 6.3 Registry-Level: Empty Targeted Scan (`tests/test_registry.py`)
Add `test_targeted_refresh_empty_result_logs_warning`:
1. Mock `refresh_statuses(game_names=["Hades"])` to return `[]`.
2. Assert a `"warning"`-level log is emitted.
3. Assert `_games` and `_ids` are unchanged.

### 6.4 Registry-Level: Full Scan Fallback (`tests/test_registry.py`)
Add `test_refresh_after_operation_null_game_name_does_full_refresh`:
1. Call `refresh_after_operation(game_name=None)`.
2. Assert `_games.clear()` was reached (verify games are replaced, not merged).

### 6.5 Registry-Level: Aliases Not Rebuilt When Config Unchanged (`tests/test_registry.py`)
Add `test_targeted_refresh_skips_alias_rebuild_when_config_stale`:
1. Set `registry._ludusavi_config_mtime_ns = 12345`.
2. Trigger targeted merge. Assert `get_aliases()` is NOT called on the adapter.
3. Set `registry._ludusavi_config_mtime_ns = None`.
4. Trigger targeted merge. Assert `get_aliases()` IS called.

### 6.6 Lifecycle-Level: Call Site Verification (`tests/test_service.py`)
Add `test_force_restore_calls_refresh_after_operation`:
1. Mock `registry.refresh_after_operation` on the service.
2. Call `service.force_restore("Hades")`.
3. Assert `refresh_after_operation` was called with `"Hades"`.

Extend existing `test_backup_game_on_exit_performs_backup_and_refreshes_history` and `test_force_operations_work_when_auto_sync_disabled` with `assert_called_with("Hades")` on the mocked refresh.

### 6.7 Test Fakes Updated

**`tests/test_service.py:FakeAdapter.refresh_statuses` (line 57):**
Add `game_names: list[str] | None = None` parameter to match the updated protocol.

**`tests/test_history_fixes.py` — two `RefreshFailingAdapter` subclasses (lines 10 and 34):**
Both override `refresh_statuses(self)` without accepting `game_names`. When the new code calls `refresh_statuses(game_names=["Hades"])`, these overrides will `TypeError`. Fix: add `_game_names=None` (unused, just for signature compatibility) and forward it to `super().refresh_statuses(game_names=_game_names)`:
```python
def refresh_statuses(self, _game_names=None):
    self.refresh_calls += 1
    if self.refresh_calls > 1:
        raise RuntimeError("Refresh failed after backup")
    return super().refresh_statuses(game_names=_game_names)
```
This is the only test file outside `test_service.py` that needs updating because its subclasses override `refresh_statuses` and sit on the call path. Other standalone fakes in `test_backup_decision.py`, `test_issue_*.py`, etc. never receive `game_names` during their test execution and stay unchanged.

---

## 7. Detailed Implementation Steps

### Step 7.1: Modify `types.py` (line 8)
Change:
```python
def refresh_statuses(self) -> list[dict[str, object]]: ...
```
To:
```python
def refresh_statuses(self, game_names: list[str] | None = None) -> list[dict[str, object]]: ...
```

### Step 7.2: Modify `PyludusaviAdapter` in `ludusavi.py` (line 65)
Change signature:
```python
def refresh_statuses(self, game_names: list[str] | None = None) -> list[dict[str, object]]:
```
Update the `ThreadPoolExecutor` block (lines 66-69):
```python
with ThreadPoolExecutor(max_workers=2) as executor:
    preview_future = executor.submit(self._client.backup, games=game_names, preview=True)
    backups_future = executor.submit(self._client.backups_list, games=game_names)
    preview = preview_future.result().data
    backups = backups_future.result().data
```

### Step 7.3: Modify `GameRegistry` in `registry.py`

**`refresh_after_operation` (line 182):**
Change signature to `def refresh_after_operation(self, game_name: str | None = None) -> None:`.
Forward `game_name` to the internal call on line 185:
```python
self._refresh_statuses_unlocked(game_name=game_name)
```

**`_refresh_statuses_unlocked` (line 190):**
Add `game_name: str | None = None` parameter to the signature.
After the docstring/signature, insert before the adapter call (before line 195):
```python
game_names = [game_name] if game_name else None
```
Change line 195 from:
```python
raw_statuses = self._gateway.get_adapter().refresh_statuses()
```
To:
```python
raw_statuses = self._gateway.get_adapter().refresh_statuses(game_names=game_names)
```

Replace the entire `with self._state_lock:` block (lines 213-231) with:
```python
        with self._state_lock:
            if not game_name and not (
                isinstance(ludusavi_config_mtime_ns, int)
                and self._ludusavi_config_mtime_ns == ludusavi_config_mtime_ns
            ):
                adapter = self._gateway.get_adapter()
                new_aliases = getattr(adapter, "get_aliases", lambda: {})()
                self._aliases.clear()
                self._aliases.update(new_aliases)

            if game_name:
                # --- Targeted Merge Mode ---
                if not games:
                    self.log(
                        "warning",
                        f"Targeted refresh for '{game_name}' returned no results; cache unchanged",
                        "refresh",
                    )
                else:
                    for game in games:
                        # Remove old steam ID association before inserting new one
                        old_game = self._games.get(game.name)
                        if old_game and old_game.steam_id and old_game.steam_id in self._ids:
                            del self._ids[old_game.steam_id]

                        self._games[game.name] = game
                        if game.steam_id:
                            self._ids[game.steam_id] = game.name
            else:
                # --- Bulk Replacement Mode ---
                self._games.clear()
                self._games.update({game.name: game for game in games})

                self._ids.clear()
                self._ids.update({game.steam_id: game.name for game in games if game.steam_id})

                if installed_app_ids is not CACHE_MARKER_UNCHANGED:
                    self._installed_app_ids = cast(str | None, installed_app_ids)
                if ludusavi_config_mtime_ns is not CACHE_MARKER_UNCHANGED:
                    self._ludusavi_config_mtime_ns = cast(int | None, ludusavi_config_mtime_ns)
```

Design notes:
- `installed_app_ids` and `ludusavi_config_mtime_ns` are intentionally **not** updated during targeted merges. The next full poll handles that. This avoids stale markers indefinitely suppressing needed full refreshes.
- The aliases gate is explicitly skipped during targeted merges via `if not game_name and not (...)`. When `game_name` is set, the alias-rebuild block is bypassed entirely — no `get_aliases()` subprocess call is made on any targeted refresh.

### Step 7.4: Update Call Sites in `lifecycle.py`

**`backup_game_on_exit` (line 272):**
Change:
```python
self.dependencies.registry.refresh_after_operation()
```
To:
```python
self.dependencies.registry.refresh_after_operation(game.name)
```

**`force_backup` (line 306):**
Change:
```python
self.dependencies.registry.refresh_after_operation()
```
To:
```python
self.dependencies.registry.refresh_after_operation(game.name)
```

**`force_restore` (after line 332, before the `return` on line 333):**
Insert:
```python
        self.dependencies.registry.refresh_after_operation(game.name)
```
The resulting block (lines 332-333) becomes:
```python
        self.dependencies.history.record_history(game.name, "restore", "manual_restore", "restored")
        self.dependencies.registry.refresh_after_operation(game.name)
        return {"status": "restored", "game": game.name, "result": result}
```

### Step 7.5: Update Test Fakes

**`tests/test_service.py:FakeAdapter.refresh_statuses` (line 57):**
Change:
```python
def refresh_statuses(self) -> list[dict[str, object]]:
```
To:
```python
def refresh_statuses(self, game_names: list[str] | None = None) -> list[dict[str, object]]:
```

**`tests/test_history_fixes.py` — two `RefreshFailingAdapter` classes (lines 15-19 and 39-43):**
Change both overrides from:
```python
def refresh_statuses(self):
    self.refresh_calls += 1
    if self.refresh_calls > 1:
        raise RuntimeError("Refresh failed after backup")
    return super().refresh_statuses()
```
To:
```python
def refresh_statuses(self, _game_names=None):
    self.refresh_calls += 1
    if self.refresh_calls > 1:
        raise RuntimeError("Refresh failed after backup")
    return super().refresh_statuses(game_names=_game_names)
```

---

## 8. Validation Checklist
- [ ] `./run.sh uv run ruff check .` passes
- [ ] `./run.sh uv run ruff format .` passes
- [ ] `./run.sh uv run ty check py_modules/sdh_ludusavi/` passes
- [ ] `./run.sh uv run pytest` passes (all existing tests + new ones)
- [ ] No `clear()` on `self._games` or `self._ids` during targeted merge
- [ ] `get_aliases()` skipped when config mtime already cached and unchanged
- [ ] Empty targeted scan results logged as warning, cache preserved
- [ ] Pre-existing games not mutated/deleted during targeted update
- [ ] `force_restore` now calls `refresh_after_operation(game.name)`

---

## 9. Implementation Protocol

### 9.1 Use the implementer skill
The implementing agent must load and follow the **implementer** skill at `/home/beallio/Dropbox/Scripts/agent-skills/skills/implementer/SKILL.md`. All implementation work must adhere to its atomic, test-driven, and safety-guardrail workflow.

### 9.2 Branch & review-fix loop
1. Create a feature branch from `main`: `feat/single-game-refresh`.
2. After each implementation step, commit atomically with Conventional Commits.
3. At logical checkpoints (after adapter changes, after registry changes, after lifecycle changes), run:
   ```
   codex --profile deepseek-v4-pro review --base main
   ```
   This diffs the active branch against `main` and surfaces issues.
   - Note, if you encounter "ERROR codex_models_manager::manager: failed to refresh available models" at the beginning of the ouput, skip the large JSON output as this isn't part of the review.
4. Address every finding before proceeding to the next checkpoint.
5. Final review pass must be clean before handoff.
