# Finish the Boundary Refactor: Remove service.py Façade Compatibility Shims

> **Plan name:** `remove_service_facade_shims`
> **Completion marker (final step):** create empty file `/tmp/sdh_ludusavi/remove_service_facade_shims_finished`
> **Implementation agent MUST use the `implementer` skill** (invoke `Skill: implementer` before starting work). All commands run through `./run.sh`. One shim group per commit, full suite green at every step.

## Context

A prior decomposition (docs/plans/2026-05-26_decompose_srp_service.md) split `service.py` into sub-managers: `gateway.py` (LudusaviGateway), `registry.py` (GameRegistry), `lifecycle.py` (GameLifecycleManager), `coordinator.py` (OperationCoordinator), `watchdog.py` (ProcessWatchdog), plus `log_buffer.py`, `persistence.py`, `matcher.py`. To keep the pre-existing suite green, the façade kept compatibility shims:

- **Re-exports** marked "For test backward compatibility" at `service.py:9-21` (persistence types, coordinator types, watchdog helpers, log buffer types) and aliases at `service.py:34-36`.
- **Property proxies** at `service.py:355-373` reaching into sub-manager privates: `_logs`, `_operation`, `_games` (setter), `_aliases`, `_installed_app_ids` (setter), `_ludusavi_config_mtime_ns` (setter), `_watchdog_active`, `_watchdog_thread`, `_paused_pids`, `_paused_pids_lock`.
- **Module-level wrapper functions** at `service.py:478-495`: `_normalize`, `_fuzzy_match_allowed`, `_normalize_installed_app_ids`.
- **Dead code** at `service.py:39-63`: `_DECKY_LOGGER` / `_decky_log`, kept only for an AST test.

The setter-bearing properties let any holder of the service mutate registry state without taking `registry._state_lock` (`registry.py:45`), undermining the thread-safety boundary the decomposition was meant to establish, and every sub-manager internal rename breaks tests through the façade. This plan deletes the shims and retargets/rewrites the tests, one group per commit.

### Corrections to the original writeup (verified against the code)

| Writeup claim | Reality |
|---|---|
| "`_norm`" re-export | Actual name is `_normalize` (service.py:478), plus `_fuzzy_match_allowed` and `_normalize_installed_app_ids`. |
| "the sanitizers" are re-exported for tests | `sanitize_game_name` is imported from `game_names` for real internal use, not a test shim. The test-only re-exports are the watchdog process helpers (`_coerce_signal_pid`, `_send_signal_tree`, `_child_pids`, `MAX_SIGNAL_PID`, `_read_ppid`, `_process_tree`). |
| `_paused_pids`, `_operation`, `_watchdog_thread` "several with setters" | Those three are getter-only; tests mutate the *returned objects* in place. The setters are on `_games`, `_installed_app_ids`, `_ludusavi_config_mtime_ns`. The lock-bypass concern is real either way. |
| "item 7" | Item 7 of the decomposition plan is "Operation Coordination" (thread-safe locking), not registry locking specifically — but the substance holds: setters bypass `registry._state_lock`. |
| `test_compatibility.py` "is a 200-line attribute-existence contract; trim it" | It's 226 lines verifying 29 public method *signatures* + a behavior smoke test — it tests no shims. It needs **aligning/expanding** to main.py's real surface (~41 methods incl. updater/syncthing/`stop`), not trimming. It does import `JsonSettingsStore` from `service` (line 6), which must be retargeted. |
| "mostly tests/test_service.py and tests/test_compatibility.py" | Mostly `test_service.py`; also `test_matching.py`, `test_matcher.py`, `test_issue_1_matching.py`, `test_issue_3_refresh_robustness.py`, `test_issue_5_env_logging.py`, `test_issue_10_sanitization.py`, `test_exception_boundaries.py`, `test_future_exception_cleanup.py`, `test_main.py`. |
| "pure deletion plus test rewrites" | Mostly true. One latent bug gets fixed: `monkeypatch.setattr("sdh_ludusavi.service._send_signal_tree", ...)` at test_service.py:379/404/426 is currently a **no-op** (watchdog calls its own module global); retargeting makes the guard real. |

### Keep vs delete partition (critical — do not over-delete)

**KEEP — real public surface (main.py:12-16 imports these):** `SDHLudusaviService`, `OperationLockedError`, `DEFAULT_NOTIFICATION_SETTINGS`. Formalize with `__all__` in Commit 10.

**KEEP — internally used by service.py itself (only remove the "backward compatibility" comment/noqa):** `resolve_version` (used ~line 104), `SettingsStore` (annotation), `PersistenceManager` (~line 133), `OperationCoordinator` (~line 120), `GameStatus`, `_conflict_metadata` (498-514), `_skip` (517-531) — both consumed via `LifecycleDependencies` lambdas (~service.py:172-173) — and `_coerce_notification_settings` (534-543).

**DELETE:** everything in the commit list below.

## Prerequisites / Protocol steps (before any code change)

1. Run the read-only handshake verification (`pwd`, `ls`, `git status`, inspect `pyproject.toml`/`uv.lock`/`run.sh`) and output the `AGENT_PROTOCOL_HANDSHAKE` block per CLAUDE.md §1.
2. `git status --short` must be clean of unrelated user work (CLAUDE.md §18). If uncommitted changes exist, report and stop.
3. Create the feature branch from `dev`: `git checkout -b refactor/remove-service-facade-shims`.
4. **Commit 0** — copy this plan (Context + commit list + spec) into `docs/plans/remove_service_facade_shims.md` and commit: `docs(plans): add service facade shim removal plan`.

## Validation procedure — run for EVERY commit, in this order

```
./run.sh uv run pytest tests/<files edited in this commit> -q   # targeted, first
./run.sh uv run ruff check . --fix     # review the --fix diff: it must not strip imports you still need
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest                 # full suite
```

Also, before deleting any symbol from service.py, run the grep guard and confirm zero façade-path consumers remain:
```
grep -rn "<symbol>" tests/ main.py py_modules/ | grep -v "<defining module>"
```
**Rule:** test retargets and the corresponding shim deletion land in the SAME commit (monkeypatch on a deleted attribute raises AttributeError; a deleted property with surviving test usage fails too).

## Ordered commits

### Commit 1 — `refactor(service): drop unused facade re-exports and aliases`
Pure deletion; **zero test edits**. Verified: no test or module consumes these via the service path.

In `py_modules/sdh_ludusavi/service.py`:
- Delete `_CONFIG_MARKER_READ_FAILED` and `_CACHE_MARKER_UNCHANGED` aliases (lines 34-36, incl. the "For backward compatibility" comment) and trim the `.constants` import (lines 23-27) to `DEFAULT_NOTIFICATION_SETTINGS` only.
- Delete `from .log_buffer import LogEntry, DeckyLogHandler` (line 21).
- Remove `_child_pids` and `MAX_SIGNAL_PID` from the watchdog import block (lines 13-20).
- Remove `OperationState` from the coordinator import (line 12).
- Delete the `_aliases` property (line 361).
- Delete `_fuzzy_match_allowed` (lines 484-489) and the `_normalize_installed_app_ids` wrapper (lines 492-495).

### Commit 2 — `refactor(service): stop re-exporting watchdog process helpers`
In `tests/test_service.py`:
- Lines 379, 404, 426: `monkeypatch.setattr("sdh_ludusavi.service._send_signal_tree", ...)` → `monkeypatch.setattr("sdh_ludusavi.watchdog._send_signal_tree", ...)`. **Note:** these patches become live for the first time; the assertions are `calls == []` (invalid PIDs short-circuit in `_coerce_signal_pid` first), so they should stay green — run these three tests individually before the full suite.
- Calls to `svc_mod._coerce_signal_pid` (lines ~474, 485) and `svc_mod._process_tree` (lines ~564, 591, 613, 637): import `sdh_ludusavi.watchdog as watchdog_mod` and call `watchdog_mod.<helper>` instead.
- `from sdh_ludusavi.service import _read_ppid` (lines ~651, 662, 676, 687) → `from sdh_ludusavi.watchdog import _read_ppid`.
- The AST/static tests at lines 692-715 **already read `py_modules/sdh_ludusavi/watchdog.py`** — leave them alone.

In `service.py`: delete the entire `.watchdog` import block (`_coerce_signal_pid`, `_send_signal_tree`, `_read_ppid`, `_process_tree`).

### Commit 3 — `refactor(service): remove watchdog state property proxies`
In `tests/test_service.py`, mechanical retarget `service.<attr>` → `service._watchdog.<attr>`:
- `_paused_pids` reads/writes: lines ~387, 397, 412, 434, 1911, 1944, 1948, 1955, 1963, 1967.
- `_paused_pids_lock` (`with service._paused_pids_lock:`): lines ~1914, 1947.
- `_watchdog_thread` (and `_watchdog_active` if referenced): lines ~1881-1895.

In `service.py`: delete the four properties `_watchdog_active`, `_watchdog_thread`, `_paused_pids`, `_paused_pids_lock` (lines 370-373).
**Note:** the watchdog tests around lines 1898-1970 are timing-sensitive — run them 2-3 times locally to rule out flakes before committing.

### Commit 4 — `refactor(service): remove operation state property proxy`
In `tests/test_service.py`:
- Lines ~1333-1334 (`test_global_operation_lock_blocks_new_operations`): `service._operation.is_running = True` / `.name = "refresh"` → `service._coordinator._operation.is_running = True` / `service._coordinator._operation.name = "refresh"`. (Forcing a *stale* running flag is the point of this test; the public API can't reproduce it — keep the white-box approach, just aimed at the owning sub-manager, matching how `tests/test_coordinator.py` already works.)
- Lines ~1951 and ~1959 (`test_watchdog_does_not_resume_during_active_operation`): same retarget for `is_running = True/False`.

In `service.py`: delete the `_operation` property (line 356). The `OperationLockedError` re-export **stays** (main.py public surface).

### Commit 5 — `refactor(service): remove registry state property proxies`
In `tests/test_service.py`, retarget `service.<attr>` → `service._registry.<attr>`:
- `_installed_app_ids` reads: lines ~1618, 1652, 1688, 1719.
- `_ludusavi_config_mtime_ns` reads: lines ~1619, 1653, 1689, 1720.
- `_games` setter write at line ~1770: `service._games = {}` → `service._registry._games = {}`.

Already targeting `service._registry.*` directly (no edits needed): `test_issue_1_matching.py:31`, `test_issue_3_refresh_robustness.py:51-53`, `test_exception_boundaries.py:243-244`, `test_service.py:290-292, 1499, 1510, 1527, 1559, 1571, 1584`.

In `service.py`: delete the `_games`, `_installed_app_ids`, `_ludusavi_config_mtime_ns` properties (lines 357-369). This removes the last unlocked mutation path into registry state — note `registry.cache_payload()` (registry.py:85-94) exists as a lock-protected read accessor if a test ever prefers it; do not add new production accessors just for tests.

### Commit 6 — `refactor(service): remove diagnostic log buffer proxy`
Rewrite to observable behavior via the public `get_recent_logs()` (returns chronological `list[dict]` with `level`, `message`, `timestamp`, `operation`, `game_name`):
- `tests/test_issue_10_sanitization.py` (~line 38): `service._logs[-1]` → `entry = service.get_recent_logs()[-1]`; assert on `entry["message"]` instead of `.message`.
- `tests/test_issue_5_env_logging.py` (~lines 47-49): generator over `service._logs` → over `service.get_recent_logs()`; `env_log.message` → `env_log["message"]`.

In `service.py`: delete the `_logs` property (line 355).

### Commit 7 — `refactor(service): remove name normalization wrapper`
- `tests/test_matching.py:109-114`: replace `from sdh_ludusavi.service import _normalize` with `from sdh_ludusavi.matcher import GameRegistryMatcher`; use `GameRegistryMatcher().normalize(...)` with the same two assertions (`"Game.v1-2"` → `"game.v1-2"`, `"Game: Edition"` → `"game edition"`). (`tests/test_matcher.py` already tests normalize this way — match its style.)
- In `service.py`: delete `_normalize` (lines ~477-481) and its compatibility comment.

### Commit 8 — `refactor(service): drop dead decky logger shim and its AST guard`
- `tests/test_service.py`: delete `test_decky_log_uses_cached_module_level_logger` (lines ~148-161).
- `service.py`: delete lines ~39-63 — the `# Maintain module level variables for AST check...` comment, the `try: import decky / _DECKY_LOGGER` block, and `_decky_log`. **Verified dead code:** nothing calls `_decky_log`; the live decky-routing path is `log_buffer._decky_log_fallback`, covered by `tests/test_log_buffer.py:28-39`.

### Commit 9 — `refactor(service): stop re-exporting persistence types`
- Retarget `JsonSettingsStore` imports to `from sdh_ludusavi.persistence import JsonSettingsStore` in: `tests/test_service.py:13`, `tests/test_compatibility.py:6`, `tests/test_exception_boundaries.py:9`, `tests/test_future_exception_cleanup.py:12` (split each combined import so `SDHLudusaviService`/`OperationLockedError` still come from `sdh_ludusavi.service`).
- `service.py`: persistence import becomes `from .persistence import SettingsStore, PersistenceManager` (both internally used — no noqa needed).

### Commit 10 — `refactor(service): declare explicit public API and align compatibility contract`
**service.py:**
- Add `__all__ = ["SDHLudusaviService", "OperationLockedError", "DEFAULT_NOTIFICATION_SETTINGS"]` near the top.
- Remove the now-obsolete "For test backward compatibility" comment and all remaining `# noqa: F401` (membership in `__all__` satisfies ruff's re-export detection; `resolve_version`/`OperationCoordinator` etc. are genuinely used internally).

**Import hygiene (same commit):** `tests/test_matcher.py:5` and `tests/test_issue_1_matching.py:2` import `GameStatus` through the service namespace → import from `sdh_ludusavi.types` instead.

**Rewrite `tests/test_compatibility.py`** (docstring: "Contract tests for the symbols and methods main.py consumes from the service façade"):
1. `test_facade_public_symbols` — assert `service.__all__` equals the three names above; identity-check `service.OperationLockedError is coordinator.OperationLockedError` and `service.DEFAULT_NOTIFICATION_SETTINGS is constants.DEFAULT_NOTIFICATION_SETTINGS`.
2. `test_facade_method_signatures` — keep the `__init__` parameter assertions; replace the 29 hand-rolled blocks with a data-driven loop over `EXPECTED_METHODS: dict[str, list[str]]` asserting `list(inspect.signature(getattr(service, name)).parameters) == params`. The set is **exactly what main.py calls** (41 methods):
   - Settings/state: `get_settings []`, `get_game_history []`, `set_auto_sync_enabled [enabled]`, `set_selected_game [game_name]`, `set_notification_settings [settings]`, `log [level, message, operation, game_name]`
   - Updater: `set_update_channel [channel]`, `set_automatic_update_checks [enabled]`, `get_update_check_context []`, `check_for_plugin_update [current_version, force]`, `record_update_install_requested [candidate]`, `confirm_update_install_handoff [version]`, `clear_pending_update_install [version]`, `reconcile_pending_update_install [current_version]`, `revalidate_plugin_update [candidate]`, `has_pending_update_install []`
   - Syncthing: `start_syncthing_activity_watch [phase, game_name, app_id]`, `get_syncthing_activity [watch_id]`, `stop_syncthing_activity_watch [watch_id]`
   - Shortcut/command: `get_ludusavi_launcher_shortcut_id []`, `set_ludusavi_launcher_shortcut_id [app_id]`, `clear_ludusavi_launcher_shortcut_id []`, `get_ludusavi_command []`
   - Games/operations: `refresh_games [force, installed_app_ids]`, `is_game_cache_current [installed_app_ids]`, `check_game_start [game_name, app_id]`, `resolve_game_start_conflict [game_name, app_id, resolution]`, `restore_game_on_start [game_name, app_id]`, `handle_game_start [game_name, app_id]`, `check_game_exit [game_name, app_id]`, `backup_game_on_exit [game_name, app_id]`, `handle_game_exit [game_name, app_id]`, `force_backup [game_name]`, `force_restore [game_name]`
   - Diagnostics/lifecycle: `get_versions []`, `get_ludusavi_logs []`, `get_operation_status []`, `get_recent_logs []`, `pause_game_process [pid]`, `resume_game_process [pid]`, `stop []`
   - **Before committing, re-derive this list by grepping `main.py` for `self.service.<method>` and reconcile** — main.py is the source of truth, not this plan. (`resume_all_paused_processes` is intentionally excluded: main.py doesn't call it.)
3. `test_facade_behavior_smoke` — keep as-is (with `JsonSettingsStore` from persistence, done in Commit 9).

## TDD note (CLAUDE.md §9)

This refactor is behavior-preserving deletion plus test retargets/rewrites — the strict red-green cycle does not apply to the deletions. Where tests are rewritten (Commits 6, 7, 10), edit the test FIRST, run it against the still-present shim to prove it passes through the public/sub-manager path, then delete the shim and re-run.

## Final steps (after Commit 10 is green)

1. Sanity greps: `grep -n "backward compat\|noqa: F401" py_modules/sdh_ludusavi/service.py` → empty; `grep -rn "service\._games\|service\._operation\b\|service\._paused_pids\|service\._watchdog_thread\|service\._installed_app_ids\|service\._logs\b" tests/` → only `service._registry.*` / `service._watchdog.*` / `service._coordinator.*` forms remain.
2. Full validation suite one final time (all four gates + pytest).
3. Write the session log `docs/agent_conversations/2026-06-11_remove_service_facade_shims.json` (date, objective, files modified, tests changed, design decisions, results) and commit: `docs: agent session log for service facade shim removal`.
4. **Write the completion marker — REQUIRED:** create an empty file at `/tmp/sdh_ludusavi/remove_service_facade_shims_finished` (e.g., `touch /tmp/sdh_ludusavi/remove_service_facade_shims_finished`).
5. Do NOT push, tag, or open a PR unless the user asks (CLAUDE.md §14).

## Risks

- **Ruff `--fix` stripping imports:** after each import trim, review the autofix diff; `OperationLockedError` keeps its `# noqa: F401` until `__all__` lands in Commit 10.
- **No-op patches going live (Commit 2):** run the three signal tests individually first.
- **Timing-sensitive watchdog tests (Commit 3):** repeat locally to rule out flakes.
- **`service._refreshed_once = True`** at `test_issue_1_matching.py:29` sets a nonexistent attribute (stale residue) — harmless, out of scope; may note as follow-up.
- If any grep guard finds an unexpected consumer of a symbol slated for deletion, stop and reassess that commit rather than deleting blindly.

## Critical files

- `py_modules/sdh_ludusavi/service.py` (all shim deletions)
- `tests/test_service.py` (bulk of retargets)
- `tests/test_compatibility.py` (rewrite, Commit 10)
- `tests/test_matching.py`, `tests/test_matcher.py`, `tests/test_issue_1_matching.py`, `tests/test_issue_5_env_logging.py`, `tests/test_issue_10_sanitization.py`, `tests/test_exception_boundaries.py`, `tests/test_future_exception_cleanup.py`
- Reference (read-only): `main.py`, `py_modules/sdh_ludusavi/{registry,coordinator,watchdog,matcher,log_buffer,persistence}.py`
