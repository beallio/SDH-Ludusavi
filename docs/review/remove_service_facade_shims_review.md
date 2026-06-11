# Review: remove_service_facade_shims (branch `refactor/remove-service-facade-shims`)

**Date:** 2026-06-11
**Plan:** docs/plans/remove_service_facade_shims.md
**Verdict:** PARTIAL PASS — 1 required fix. Commits 0–9 and the `service.py` half of Commit 10 fully meet the plan. The `tests/test_compatibility.py` rewrite specified in Commit 10 was **not done**, even though commit `3678c95` ("align compatibility contract") claims it.

## What passed (verified, no action needed)

- Commit structure matches the plan exactly: plan doc (`d26ae0d`), Commits 1–10 (`52479d6`..`3678c95`), session log (`4804380`). Working tree clean.
- `service.py`: all shims deleted — re-exports, marker aliases, all 10 property proxies (lines formerly 355-373), `_normalize`/`_fuzzy_match_allowed`/`_normalize_installed_app_ids` wrappers, and the dead `_DECKY_LOGGER`/`_decky_log` block. Zero hits for `backward compat` / `noqa: F401` / `property(lambda`.
- Keep-list intact: `resolve_version`, `SettingsStore`, `PersistenceManager`, `OperationLockedError`, `OperationCoordinator`, `DEFAULT_NOTIFICATION_SETTINGS`, `GameStatus`, `_conflict_metadata`, `_skip`, `_coerce_notification_settings` all still present and used.
- `__all__ = ["SDHLudusaviService", "OperationLockedError", "DEFAULT_NOTIFICATION_SETTINGS"]` added (service.py:18).
- All test retargets done: watchdog helpers/patches → `sdh_ludusavi.watchdog`; watchdog state → `service._watchdog.*`; operation state → `service._coordinator._operation`; registry state → `service._registry.*`; `_logs` → `get_recent_logs()` dict payloads; `_normalize` → `GameRegistryMatcher().normalize`; `JsonSettingsStore` → `sdh_ludusavi.persistence` (4 files); `GameStatus` → `sdh_ludusavi.types` (2 files). Grep for every old façade-path form returns nothing in `tests/`.
- AST-guard test `test_decky_log_uses_cached_module_level_logger` deleted alongside its dead code.
- Quality gates all green: `ruff check` clean, `ruff format --check` clean (108 files), `ty check` clean, **513 tests pass**.
- Session log `docs/agent_conversations/2026-06-11_remove_service_facade_shims.json` committed. Completion marker `/tmp/sdh_ludusavi/remove_service_facade_shims_finished` written.

## REQUIRED FIX: rewrite tests/test_compatibility.py

Commit `3678c95` only added `__all__` to service.py and fixed two `GameStatus` imports. `tests/test_compatibility.py` is still the old file: 29 hand-rolled signature blocks plus a smoke test, with a stale "29 expected public methods" docstring. It is missing 13 of the 41 methods main.py actually calls, and has no test for `__all__`.

Rewrite `tests/test_compatibility.py` as follows (keep the existing `DummyAdapter` class and the existing `test_sdh_ludusavi_service_facade_behavior` test unchanged):

1. Set the module docstring to: `"""Contract tests for the symbols and methods main.py consumes from the service façade."""`

2. Add a new test:

```python
def test_facade_public_symbols() -> None:
    import sdh_ludusavi.constants as constants
    import sdh_ludusavi.coordinator as coordinator
    import sdh_ludusavi.service as service

    assert service.__all__ == [
        "SDHLudusaviService",
        "OperationLockedError",
        "DEFAULT_NOTIFICATION_SETTINGS",
    ]
    assert service.OperationLockedError is coordinator.OperationLockedError
    assert service.DEFAULT_NOTIFICATION_SETTINGS is constants.DEFAULT_NOTIFICATION_SETTINGS
```

3. Replace `test_sdh_ludusavi_service_interface_compatibility` (delete the 29 numbered blocks) with a data-driven version. Keep the six `__init__` parameter assertions exactly as they are today, then loop:

```python
EXPECTED_METHODS: dict[str, list[str]] = { ... }  # table below

def test_facade_method_signatures(tmp_path: Path) -> None:
    service = SDHLudusaviService(
        adapter=DummyAdapter(),
        settings_store=JsonSettingsStore(tmp_path / "settings.json"),
        cache_path=tmp_path / "cache.json",
    )
    # ... the six __init__ assertions from the old test ...
    for name, params in EXPECTED_METHODS.items():
        method = getattr(service, name, None)
        assert method is not None, f"main.py calls service.{name} but it does not exist"
        assert inspect.ismethod(method), name
        assert list(inspect.signature(method).parameters) == params, name
```

`EXPECTED_METHODS` must contain exactly these 41 entries (verified against main.py on this branch: 38 called via `self._service().X` plus `log`, `stop`, `has_pending_update_install` called via `backend.X`):

| method | params |
|---|---|
| `get_settings` | `[]` |
| `get_game_history` | `[]` |
| `set_auto_sync_enabled` | `["enabled"]` |
| `set_selected_game` | `["game_name"]` |
| `set_notification_settings` | `["settings"]` |
| `log` | `["level", "message", "operation", "game_name"]` |
| `set_update_channel` | `["channel"]` |
| `set_automatic_update_checks` | `["enabled"]` |
| `get_update_check_context` | `[]` |
| `check_for_plugin_update` | `["current_version", "force"]` |
| `record_update_install_requested` | `["candidate"]` |
| `confirm_update_install_handoff` | `["version"]` |
| `clear_pending_update_install` | `["version"]` |
| `reconcile_pending_update_install` | `["current_version"]` |
| `revalidate_plugin_update` | `["candidate"]` |
| `has_pending_update_install` | `[]` |
| `start_syncthing_activity_watch` | `["phase", "game_name", "app_id"]` |
| `get_syncthing_activity` | `["watch_id"]` |
| `stop_syncthing_activity_watch` | `["watch_id"]` |
| `get_ludusavi_launcher_shortcut_id` | `[]` |
| `set_ludusavi_launcher_shortcut_id` | `["app_id"]` |
| `clear_ludusavi_launcher_shortcut_id` | `[]` |
| `get_ludusavi_command` | `[]` |
| `refresh_games` | `["force", "installed_app_ids"]` |
| `is_game_cache_current` | `["installed_app_ids"]` |
| `check_game_start` | `["game_name", "app_id"]` |
| `resolve_game_start_conflict` | `["game_name", "app_id", "resolution"]` |
| `restore_game_on_start` | `["game_name", "app_id"]` |
| `handle_game_start` | `["game_name", "app_id"]` |
| `check_game_exit` | `["game_name", "app_id"]` |
| `backup_game_on_exit` | `["game_name", "app_id"]` |
| `handle_game_exit` | `["game_name", "app_id"]` |
| `force_backup` | `["game_name"]` |
| `force_restore` | `["game_name"]` |
| `get_versions` | `[]` |
| `get_ludusavi_logs` | `[]` |
| `get_operation_status` | `[]` |
| `get_recent_logs` | `[]` |
| `pause_game_process` | `["pid"]` |
| `resume_game_process` | `["pid"]` |
| `stop` | `[]` |

Notes for the implementing agent:
- The param lists for the 13 newly added methods (updater ×9, syncthing ×3, `has_pending_update_install`) were taken from the plan, not yet executed against the code. If the new test fails on one of them, the fix is to correct the expected param list in the table to match the actual service method signature — do NOT change the service method. Confirm each disputed name against its call site in main.py first.
- `resume_all_paused_processes` is intentionally excluded — main.py does not call it.
- Do not add anything else to `__all__` and do not modify `py_modules/sdh_ludusavi/service.py` or `main.py`; this fix is test-only.

## Validation and commit (run all of these)

```
./run.sh uv run pytest tests/test_compatibility.py -q
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

All must pass. Then commit only `tests/test_compatibility.py` with message:

```
test(compatibility): align facade contract with main.py surface
```

Do not push, tag, or open a PR.

## Optional (non-blocking) notes

- `tests/test_issue_1_matching.py:29` (or nearby) may still set `service._refreshed_once = True`, a nonexistent attribute — harmless stale residue flagged in the plan as out-of-scope follow-up.
- Commit `3678c95`'s message overstates its content ("align compatibility contract"); history rewriting is not warranted — the follow-up commit above corrects the record.
