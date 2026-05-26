# Refactor Lifecycle Checks Under Operation Lock

## Protocol Confirmation

AGENT_PROTOCOL_HANDSHAKE

Project Root: `/home/beallio/Dropbox/Scripts/SDH-ludusavi`  
Detected Language(s): Python 3.12, TypeScript/React  
Execution Mode: Project  
Git Repository Present: Yes, clean worktree on `main`  
Cache Root: `/tmp/sdh_ludusavi`  
Protocol Version: 2  
Command Wrapper: `./run.sh`

Confirmed Policies:

- [x] Top-down planning
- [x] Bottom-up TDD
- [x] Cache isolation
- [x] Verified filesystem state
- [x] Verified dependency state
- [x] Verified run wrapper

STATUS: READY

Required confirmations: temp files/caches stay under `/tmp/sdh_ludusavi`; project commands run through `./run.sh`; `ty` is the official type checker.

## Summary

- Address the review finding in `py_modules/sdh_ludusavi/service.py` by serializing the two lifecycle preview calls that currently bypass `_run_locked`.
- Keep scope literal: only change `check_game_start` and `check_game_exit` behavior in `py_modules/sdh_ludusavi/service.py`, plus tests/docs required by repo protocol.
- Do not change public function signatures, returned payload shapes, frontend code, upstream packages, or dependencies.
- Keep `_conflict_metadata` outside this patch: it is best-effort conflict prompt metadata, catches broad failures, and falls back to empty metadata without crashing or blocking the UI.
- Before implementation, create branch `refactor-operation-lock-checks` and write this planning artifact. The slash-form branch name was avoided because this checkout could not create nested refs in `.git/refs/heads`.

## Interface And Behavior

- `check_game_start(game_name, app_id=None) -> dict[str, object]` remains unchanged externally.
- `check_game_exit(game_name, app_id=None) -> dict[str, object]` remains unchanged externally.
- Add only internal/transient operation labels:
  - `start_check` for `compare_recency(game.name)`
  - `exit_check` for `backup(game.name, preview=True)`
- Preserve existing early skip behavior for disabled auto-sync, existing active operation, unmatched game, no backup, and game error.
- Treat `_run_locked` as the authoritative guard around Ludusavi calls. If it raises `OperationLockedError`, return `_skip("start"|"exit", game.name, "operation_running")`.
- In `check_game_exit`, catch `OperationLockedError` before the existing broad preview failure handler so lock contention is not misreported as `preview_failed`.
- Preserve the existing TypeScript-facing result contracts. In particular, operation contention must return the existing `_skip(...)` structure: `{"status": "skipped", "game": ..., "reason": "operation_running"}`.
- Do not wrap `_conflict_metadata` in this action item. A race in that metadata call is acceptable for this narrow fix because `_conflict_metadata` catches exceptions and returns `None` values for `localModifiedAt`, `backupModifiedAt`, and `backupPath` when metadata cannot be collected.

## Implementation Steps

- Add tests first in `tests/test_service.py`, near the existing lifecycle and lock tests.
- Add success-path lock-observation tests:
  - `test_check_game_start_runs_recency_under_operation_lock`: make `compare_recency` record `service.get_operation_status()` during the call and assert `is_running is True`, `name == "start_check"`, `game_name == "Hades"`.
  - `test_check_game_exit_runs_preview_under_operation_lock`: make preview `backup(..., preview=True)` record the same and assert `name == "exit_check"` while still returning the existing `needed` result without appending a real backup.
- Add race/lock-contention tests:
  - `test_check_game_start_skips_if_operation_starts_after_initial_guard`: monkeypatch `_match_game` to start a background `_run_locked("refresh", None, slow_callback)` after the existing early guard but before recency comparison, then assert skipped `operation_running`.
  - `test_check_game_exit_skips_if_operation_starts_after_initial_guard`: same pattern before backup preview, asserting skipped `operation_running`.
- For the lock-contention tests, assert the full skipped payload shape rather than only the reason so frontend-facing contracts remain pinned.
- Keep existing ambiguous-recency/conflict tests intact so the `_conflict_metadata` fallback path and conflict payload shape continue to be covered without expanding this patch's lock scope.
- Run the new tests through `./run.sh uv run pytest tests/test_service.py -k "operation_lock or initial_guard or recency_under_operation_lock or preview_under_operation_lock"` and confirm they fail before production edits.
- Replace the direct `compare_recency` call with:

```python
self._run_locked("start_check", game.name, lambda: self._ludusavi().compare_recency(game.name))
```

wrapped in `except OperationLockedError`.

- Replace the direct exit preview call with:

```python
self._run_locked("exit_check", game.name, lambda: self._ludusavi().backup(game.name, preview=True))
```

inside the existing preview `try`, with `except OperationLockedError` before `except Exception`.

- Leave `_conflict_metadata`, diagnostics, version checks, and other Ludusavi adapter calls untouched because they are outside this action item's stated scope.
- Add a note to the session log that a future architectural hardening pass should evaluate serializing every Ludusavi CLI subprocess call, including conflict metadata, diagnostics, and version/config probes.

## Validation

- Red phase: run the new targeted tests before implementation and capture the expected failures.
- Green phase: run `./run.sh uv run pytest tests/test_service.py`.
- Full validation before commit:
  - `./run.sh uv run ruff check . --fix`
  - `./run.sh uv run ruff format .`
  - `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  - `./run.sh uv run pytest`
- Record `docs/agent_conversations/2026-05-26_refactor_operation_lock_checks.json`.
- Commit with `refactor(service): serialize lifecycle checks` after hooks pass.

## Assumptions

- The broader review's other Ludusavi-lock concerns are intentionally out of scope for this action item.
- `_conflict_metadata` remains an explicitly accepted edge case for this patch because its current broad fallback prevents UI crashes and lets the conflict prompt render without optional metadata.
- No README update is needed because user-facing commands, settings, and return schemas do not change.
- If the worktree becomes dirty before implementation, re-run `git status --short` and avoid formatting/staging unrelated user-owned files.
