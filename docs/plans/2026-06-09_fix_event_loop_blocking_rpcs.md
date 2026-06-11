# Implementation Plan: Eliminate Event-Loop-Blocking RPCs and Bound Ludusavi Discovery (Review Finding B2)

**Plan file destination in repo:** `docs/plans/2026-06-09_fix_event_loop_blocking_rpcs.md`
**Branch:** create from the current integration branch, named `fix/event-loop-blocking-rpcs`
**Prerequisites assumed already merged:** B1 (`compare_recency` direction safety) and B4 (Syncthing TLS). This plan does not touch `lifecycle.py` recency logic or `syncthing/`. If you find merge conflicts in those areas, **stop and report** — you are on the wrong base.
**Estimated scope:** `main.py` (7 localized edits), `py_modules/pyludusavi/discovery.py` (1 function, internals only), ~9 new tests across 2 test files, no frontend changes, no persisted-state changes.

---

## 1. Problem Statement (read fully before editing anything)

Decky Loader runs the plugin backend on a single asyncio event loop. Every `async def` RPC handler in `main.py` that does synchronous work **without** offloading it freezes the entire plugin (all RPCs, the status strip, the updater, everything) for the duration of that work. The codebase's own convention is to offload via `Plugin._call(...)` → `_run_blocking(...)`, which runs the callback on a worker thread. Five handlers violate this, and one of them can block **indefinitely**:

| Handler (main.py line) | Current body | Worst-case blocking behavior |
|---|---|---|
| `is_game_cache_current` (205–206) | `return self._service().is_game_cache_current(...)` | **Unbounded.** Chain: `registry.is_game_cache_current` → `gateway.current_config_mtime_ns()` → `gateway.get_adapter()` → lazy `PyludusaviAdapter()` → `pyludusavi.discovery.find_ludusavi()` → `_verify()` → `subprocess.run([..., "--version"])` with **no `timeout=` argument** (`py_modules/pyludusavi/discovery.py:79-95`). A cold `flatpak run` takes seconds; a wedged Flatpak/portal stack hangs forever. Even with the adapter already constructed, `get_config_mtime_ns()` may call `config_path()` (a subprocess, executor default 30 s) plus several `stat()` calls — still loop-blocking disk/subprocess work. |
| `get_ludusavi_launcher_shortcut_id` (156–157) | `return self._service().get_ludusavi_launcher_shortcut_id()` | In-memory read **after** the service exists, but `self._service()` lazily **constructs** the service: persistence JSON reads, `mkdir`/`chmod`, logging setup, `getpass.getuser()` — disk I/O on the loop if this is the first RPC to arrive. |
| `get_operation_status` (271–272) | direct call | Same lazy-construction hazard; otherwise in-memory. |
| `get_recent_logs` (274–275) | direct call | Same lazy-construction hazard; otherwise in-memory. |
| `log` (~196) | `self._service().log(...)` | Same lazy-construction hazard. The log write itself (deque append + decky logger) must stay on-loop because this is the hottest RPC (the frontend logs every lifecycle event); spawning a thread per log line is unacceptable. |

One additional latent instance of the same bug class:

| Location | Problem |
|---|---|
| `main.py:268-269` — `get_versions` | `await self._call("get_versions", self._service().get_versions)` — the argument expression `self._service().get_versions` is evaluated **eagerly on the event loop** before `_call` ever runs, so lazy service construction happens on the loop here too. Only the *bound method object* is offloaded. |

And `_main` itself constructs the service synchronously on the loop (`service = self._service()` then `reconcile_pending_update_install(...)`, which performs disk writes via `_save_callback`).

### Target behavior (the contract you are implementing)

1. **No RPC handler and no lifecycle hook in `main.py` may construct the service, touch the adapter, or perform disk/subprocess work on the event loop.** Everything routes through `_call`, except the `log` fast path defined in rule 3.
2. **Each offloaded handler must preserve its frontend type contract.** `_call` converts exceptions to `{"status": "failed"|"skipped", ...}` dicts. Handlers whose frontend callers expect a primitive (`boolean`, `number`) or a specific shape (`OperationStatus`, `LogEntry[]`) must coerce failure payloads to a documented safe default rather than leak the dict. The defaults are specified per-handler in §3.
3. **`log` stays synchronous** but must never *construct* the service: if `self._backend is None`, fall back to `decky.logger` directly and return.
4. **Ludusavi discovery verification must be time-bounded.** `pyludusavi.discovery._verify` gains an internal subprocess timeout (15 s per candidate) and treats `subprocess.TimeoutExpired` as verification failure. The public signature of `find_ludusavi` must remain byte-identical (a test enforces this — see §2 invariants).

### Invariants you must not break

- `tests/test_ludusavi_discovery.py::test_find_ludusavi_signature_is_clean_upstream` asserts `find_ludusavi`'s parameter list is exactly `["explicit_path", "explicit_flatpak_id", "flatpak_id", "env"]` and that certain helper names do not exist. Your discovery change must keep `find_ludusavi`'s signature untouched and must not add any of the forbidden names. Modify **only** the internals of `_verify` plus one new private module constant.
- `py_modules/pyludusavi/` is a **vendored** copy of the `pyludusavi` 0.2.3 wheel. You are authorized to patch `discovery.py` *for this finding only*, under these rules: (a) keep the patch minimal, (b) add the marker comment specified in §3 Step 6 so the divergence from the wheel is discoverable, (c) do **not** edit anything in `py_modules/pyludusavi-0.2.3.dist-info/` (the stale `RECORD` hash for `discovery.py` is harmless — nothing verifies it at runtime), (d) do not import anything from `sdh_ludusavi` inside `pyludusavi` (layering: the vendored library must stay self-contained).
- Do not modify `_run_blocking` or `_call` themselves. `tests/test_main.py:141` (`test_run_blocking_uses_event_driven_daemon_future_without_polling`) AST-checks `_run_blocking`; leave it alone.
- Do not change any RPC names, parameters, or the `callable<...>` typings in `src/api/ludusaviRpc.ts`. **Zero frontend file changes.** The frontend already tolerates the coerced defaults: `src/ludusaviLauncher.ts:84-95` maps non-numbers to `-1`; `src/components/qam/LudusaviContent.tsx:407` consumes a plain boolean; `:289,531,675` read `OperationStatus` fields; `:532,596` iterate the logs array.
- Follow the repo TDD protocol (`AGENTS.md` §9, enforced by `scripts/check_tdd.sh`): failing test first, then implementation, then green.

---

## 2. Files You Will Touch (exhaustive list)

| File | Action |
|---|---|
| `main.py` | Rework 5 handler bodies + `get_versions` lambda + `_main` offload |
| `py_modules/pyludusavi/discovery.py` | Add `_VERIFY_TIMEOUT_SECONDS` constant; add `timeout=` + `TimeoutExpired` handling inside `_verify` |
| `tests/test_main_rpc.py` | Add 6 handler tests (uses existing `MockService`/`FakePlugin` pattern already in this file) |
| `tests/test_main.py` | Add 1 loop-responsiveness test + 1 `_main` offload test (mirrors patterns at lines 170 and 361) |
| `tests/test_ludusavi_discovery.py` | Add 2 `_verify` timeout tests |
| `docs/plans/2026-06-09_fix_event_loop_blocking_rpcs.md` | This plan, committed per repo convention |
| `docs/agent_conversations/<date>_fix_event_loop_blocking_rpcs.json` | Session log per `AGENTS.md` §15 |

Files that must show **no diff** at the end: everything under `src/`, `py_modules/sdh_ludusavi/`, `py_modules/pyludusavi-0.2.3.dist-info/`, and `pyproject.toml`. Verify with `git status` before committing.

---

## 3. Step-by-Step Implementation

### Step 0 — Environment and baseline

```bash
cd <repo-root>
./run.sh uv sync
./run.sh uv run pytest            # must be green; record the passing count
pnpm install --frozen-lockfile --ignore-scripts
```

If the baseline is not green, **stop and report**. Also read these files in full before editing, in this order: `main.py`, `tests/test_main.py` (lines 1–110 define `fake_decky_module` and `import_main` — you will reuse them), `tests/test_main_rpc.py` (the `MockService` + `FakePlugin` subclass pattern), `py_modules/pyludusavi/discovery.py`, `tests/test_ludusavi_discovery.py`.

### Step 1 — RED: handler coercion tests

**File:** `tests/test_main_rpc.py`. Extend the existing `MockService` (top of file) with the methods below, then append the tests. Keep the established pattern: build `decky` via `fake_decky_module`, import via `import_main`, subclass `module.Plugin` as `FakePlugin` overriding `_service`.

1a. Extend `MockService`:

```python
    def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
        self.calls.append(("is_game_cache_current", installed_app_ids))
        if getattr(self, "raise_on_cache_check", False):
            raise RuntimeError("adapter exploded")
        return True

    def get_ludusavi_launcher_shortcut_id(self) -> int:
        if getattr(self, "raise_on_shortcut", False):
            raise RuntimeError("boom")
        return 42

    def get_operation_status(self) -> dict[str, object]:
        if getattr(self, "raise_on_status", False):
            raise RuntimeError("boom")
        return {
            "is_running": True,
            "name": "backup",
            "game_name": "Hades",
            "last_result": None,
            "last_error": None,
        }

    def get_recent_logs(self) -> list[dict[str, object]]:
        if getattr(self, "raise_on_logs", False):
            raise RuntimeError("boom")
        return [{"level": "info", "message": "hi", "timestamp": "t", "operation": None, "game_name": None}]
```

1b. Append these tests (each follows the file's existing construction boilerplate — copy it verbatim from `test_plugin_refresh_games_passes_installed_app_ids`):

```python
def test_is_game_cache_current_returns_service_bool(tmp_path, monkeypatch) -> None:
    ...  # boilerplate
    assert asyncio.run(plugin.is_game_cache_current("1,2")) is True
    assert ("is_game_cache_current", "1,2") in mock_service.calls


def test_is_game_cache_current_coerces_failure_to_false(tmp_path, monkeypatch) -> None:
    ...  # boilerplate
    mock_service.raise_on_cache_check = True
    assert asyncio.run(plugin.is_game_cache_current("1,2")) is False


def test_get_ludusavi_launcher_shortcut_id_returns_int(tmp_path, monkeypatch) -> None:
    ...
    assert asyncio.run(plugin.get_ludusavi_launcher_shortcut_id()) == 42


def test_get_ludusavi_launcher_shortcut_id_coerces_failure_to_minus_one(tmp_path, monkeypatch) -> None:
    ...
    mock_service.raise_on_shortcut = True
    assert asyncio.run(plugin.get_ludusavi_launcher_shortcut_id()) == -1


def test_get_operation_status_coerces_failure_to_idle_default(tmp_path, monkeypatch) -> None:
    ...
    mock_service.raise_on_status = True
    assert asyncio.run(plugin.get_operation_status()) == {
        "is_running": False,
        "name": None,
        "game_name": None,
        "last_result": None,
        "last_error": None,
    }


def test_get_recent_logs_coerces_failure_to_empty_list(tmp_path, monkeypatch) -> None:
    ...
    mock_service.raise_on_logs = True
    assert asyncio.run(plugin.get_recent_logs()) == []
```

> Why these specific defaults: a failure dict leaking through `is_game_cache_current` would be truthy → frontend (`LudusaviContent.tsx:407`) would *skip* a needed refresh; `False` forces a refresh, which is the safe direction. `-1` is the launcher module's existing "no shortcut" sentinel. The idle `OperationStatus` shape matches `OperationState()`'s field-for-field defaults in `coordinator.py`. `[]` renders an empty log modal instead of crashing `.map`.

1c. **File:** `tests/test_main.py` — append two tests mirroring existing patterns:

```python
def test_is_game_cache_current_does_not_block_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirror test_call_does_not_block_event_loop_while_callback_runs (line ~170):
    service.is_game_cache_current blocks on a threading.Event; assert the loop
    can run another coroutine to completion while the handler is in flight,
    then release the event and assert the handler returns True."""
    ...


def test_main_offloads_service_initialization(tmp_path, monkeypatch) -> None:
    """Mirror test_unload_stops_backend_through_call (line ~361): monkeypatch
    plugin._call with a recorder fake that invokes the callback inline and
    returns its result; run plugin._main(); assert the recorded operation
    names include "startup_init" and "reconcile_pending_update_install"."""
    ...
```

Implement both fully by copying the referenced tests' structure — do not invent new helpers. Run and confirm **all new tests fail**:

```bash
./run.sh uv run pytest tests/test_main_rpc.py tests/test_main.py -x -q
```

Expected failure modes: coercion tests fail because exceptions currently propagate out of the direct calls (or failure dicts are returned where primitives are expected); `_main` test fails because no `_call` is recorded.

### Step 2 — GREEN: rewrite the five handlers in `main.py`

Replace each handler body exactly as follows. Do not rename, reorder, or change signatures.

2a. `is_game_cache_current` (currently lines 205–206):

```python
    async def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
        result = await self._call(
            "is_game_cache_current",
            lambda: self._service().is_game_cache_current(installed_app_ids),
        )
        # _call converts failures to status dicts; the frontend expects a bare
        # boolean. False is the safe default: it triggers a refresh.
        return result if isinstance(result, bool) else False
```

2b. `get_ludusavi_launcher_shortcut_id` (156–157):

```python
    async def get_ludusavi_launcher_shortcut_id(self) -> int:
        result = await self._call(
            "get_ludusavi_launcher_shortcut_id",
            lambda: self._service().get_ludusavi_launcher_shortcut_id(),
        )
        # bool is an int subclass; exclude it explicitly. -1 == "no shortcut".
        if isinstance(result, int) and not isinstance(result, bool):
            return result
        return -1
```

2c. `get_operation_status` (271–272):

```python
    async def get_operation_status(self) -> dict[str, object]:
        result = await self._call(
            "get_operation_status", lambda: self._service().get_operation_status()
        )
        if isinstance(result, dict) and "is_running" in result:
            return result
        # Failure/skip dicts from _call lack "is_running"; return an idle state
        # matching coordinator.OperationState() defaults.
        return {
            "is_running": False,
            "name": None,
            "game_name": None,
            "last_result": None,
            "last_error": None,
        }
```

2d. `get_recent_logs` (274–275):

```python
    async def get_recent_logs(self) -> list[dict[str, object]]:
        result = await self._call(
            "get_recent_logs", lambda: self._service().get_recent_logs()
        )
        return result if isinstance(result, list) else []
```

2e. `log` (~line 196). Replace the body with:

```python
    async def log(
        self,
        level: str,
        message: str,
        operation: str | None = None,
        game_name: str | None = None,
    ) -> None:
        """
        Route frontend logs to the backend service.

        Stays on the event loop intentionally: this is the hottest RPC and the
        work is an in-memory ring-buffer append. It must therefore never be the
        call that *constructs* the service (disk I/O); before construction,
        fall back to decky's logger directly.
        """
        backend = self._backend
        if backend is None:
            decky.logger.info(
                f"[frontend:{level}] {operation or 'frontend'}: {message}"
            )
            return
        backend.log(level, message, operation, game_name)
```

(`self._backend` is a plain attribute read; the worst race outcome is one log line taking the decky-logger fallback path, which is acceptable.)

2f. `get_versions` (268–269) — fix the eager binding. Replace:

```python
        return await self._call("get_versions", self._service().get_versions)
```

with:

```python
        return await self._call("get_versions", lambda: self._service().get_versions())
```

2g. `_main` — replace the whole method with:

```python
    async def _main(self) -> None:
        decky.logger.info("SDH-ludusavi backend loaded")

        init_result = await self._call("startup_init", self._service)
        if isinstance(init_result, dict) and init_result.get("status") == "failed":
            decky.logger.error(
                "Service initialization failed during startup: %s",
                init_result.get("message"),
            )
            return

        try:
            from sdh_ludusavi._version import resolve_version
        except Exception:
            decky.logger.exception("Failed to import version resolver on startup")
            return

        reconcile_result = await self._call(
            "reconcile_pending_update_install",
            lambda: self._service().reconcile_pending_update_install(resolve_version()),
        )
        if isinstance(reconcile_result, dict) and reconcile_result.get("status") == "failed":
            decky.logger.error(
                "Failed to reconcile pending update install on startup: %s",
                reconcile_result.get("message"),
            )
```

Notes: `self._service` (no parentheses) is passed as the callback — `_call` invokes it on the worker thread, performing construction off-loop; `_call` already swallows exceptions into failed dicts, which is why the explicit failed-dict logging replaces the old `try/except` around `reconcile`. The existing test `test_plugin_main_triggers_reconciliation` (`tests/test_main.py:645`) must still pass; if it fails, read it and adjust **the test's monkeypatching only** to account for `_call` indirection while preserving its assertion that reconciliation runs — do not weaken the assertion.

Run Step 1's tests; all must pass. Then run the whole backend suite:

```bash
./run.sh uv run pytest
```

### Step 3 — RED: discovery timeout tests

**File:** `tests/test_ludusavi_discovery.py`. Append:

```python
def test_verify_passes_timeout_to_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(discovery.subprocess, "run", fake_run)
    assert discovery._verify(["ludusavi"]) is True
    assert captured["timeout"] == discovery._VERIFY_TIMEOUT_SECONDS
    assert captured["timeout"] is not None


def test_verify_returns_false_when_subprocess_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(discovery.subprocess, "run", fake_run)
    assert discovery._verify(["flatpak", "run", APP_ID]) is False
```

Confirm both fail (`AttributeError: _VERIFY_TIMEOUT_SECONDS` / `TimeoutExpired` propagating):

```bash
./run.sh uv run pytest tests/test_ludusavi_discovery.py -x -q
```

### Step 4 — GREEN: patch `_verify` in the vendored module

**File:** `py_modules/pyludusavi/discovery.py`

4a. Directly below the imports, add:

```python
# SDH-Ludusavi local patch (see docs/plans/2026-06-09_fix_event_loop_blocking_rpcs.md):
# bound the discovery verification subprocess so a wedged `flatpak run` cannot
# hang adapter initialization indefinitely. Upstream to pyludusavi and remove
# on the next re-vendor.
_VERIFY_TIMEOUT_SECONDS = 15.0
```

4b. Replace the body of `_verify` (lines ~79–95) with:

```python
def _verify(prefix: list[str], env: Optional[dict[str, str]] = None) -> bool:
    """Verify that the command prefix correctly calls Ludusavi."""
    try:
        if env is None:
            result = subprocess.run(
                prefix + ["--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=_VERIFY_TIMEOUT_SECONDS,
            )
        else:
            result = subprocess.run(
                prefix + ["--version"],
                capture_output=True,
                text=True,
                check=False,
                env=env,
                timeout=_VERIFY_TIMEOUT_SECONDS,
            )
        return result.returncode == 0
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return False
```

Keep the function signature identical; do not touch `find_ludusavi`. Note `subprocess.run` kills the child on `TimeoutExpired`, so no orphan cleanup is needed here. Worst-case discovery time is now bounded at ~4 candidates × 15 s = 60 s, off-loop.

Run Step 3's tests (must pass) plus the signature guard:

```bash
./run.sh uv run pytest tests/test_ludusavi_discovery.py -q
```

### Step 5 — Full verification sweep

```bash
grep -n "self._service()." main.py | grep -v "lambda" && echo "FAIL: eager service call outside lambda" || echo OK
grep -n "timeout=_VERIFY_TIMEOUT_SECONDS" py_modules/pyludusavi/discovery.py   # expect 2 hits
git status --porcelain                                                          # only files from §2
./run.sh uv run ruff check .
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run verify
```

The first grep's `OK` condition: the only remaining permitted on-loop touches of `self._backend`/`self._service` outside lambdas are in `log` (guarded fallback), `_unload` (already reads `self._backend` and offloads `stop` via `_call`), and the lazy-init body of `_service()` itself. `pnpm run verify` is required by the commit gate even with zero frontend changes.

### Step 6 — Documentation

- Commit this plan to `docs/plans/2026-06-09_fix_event_loop_blocking_rpcs.md`.
- Write the session log to `docs/agent_conversations/` matching the existing JSON schema (`date`, `task_objective`, `files_modified`, `tests_added`, `design_decisions`, `results`). Under `design_decisions`, explicitly record: (a) the per-handler failure defaults and why, (b) the decision to keep `log` on-loop with a pre-construction fallback, (c) the vendored-patch authorization and the upstream/re-vendor follow-up.

---

## 4. Edge Cases — Required Behavior Table

| # | Scenario | Required outcome | Test |
|---|---|---|---|
| 1 | QAM opens before `_main` finished; frontend calls `is_game_cache_current` | Service constructed on a worker thread; loop stays responsive; bool returned | ✅ Step 1c loop test |
| 2 | Flatpak hangs during first adapter init | Discovery candidate fails after 15 s; loop unaffected (work is off-loop) | ✅ Step 3 timeout test |
| 3 | Service method raises inside any of the five handlers | Coerced default (`False` / `-1` / idle status / `[]`), never a leaked failure dict where a primitive is expected | ✅ Step 1b tests |
| 4 | `log` RPC arrives before service construction | Line goes to `decky.logger`; service is **not** constructed by `log` | manual assert in Step 1b style test (add: `assert plugin._backend is None` after the call) — **add this test** |
| 5 | `get_versions` called as first-ever RPC | Construction happens inside the lambda on the worker thread | covered by Step 5 grep |
| 6 | Service construction itself fails at startup | `_main` logs the failure via `decky.logger.error` and returns without crashing the loader | ✅ Step 1c `_main` test variant — extend it with a callback-raises case |
| 7 | `flatpak --version` succeeds slowly (5–10 s cold start) | Verification succeeds (15 s budget); no behavior change | implicit |
| 8 | Concurrent first RPCs racing service construction | Already handled by `Plugin._backend_lock` double-checked init (`main.py:_service`) and covered by existing `test_service_initializes_once_when_called_concurrently` (`tests/test_main.py:554`) — must still pass | existing |

Rows 4 and 6 require you to add the two indicated tests; they are part of the acceptance criteria.

## 5. Acceptance Criteria (all must hold)

1. All new tests pass; full `./run.sh uv run pytest` is green; no previously passing test deleted or weakened (only `test_plugin_main_triggers_reconciliation` may be *mechanically adapted* per Step 2g).
2. `ruff check`, `ruff format` (no diff), `ty check`, `pnpm run verify` all pass.
3. `grep -n "self._service()." main.py | grep -v lambda` reports nothing.
4. `git status` shows changes only to the files in §2; nothing under `src/` or `dist-info/`.
5. `tests/test_ludusavi_discovery.py::test_find_ludusavi_signature_is_clean_upstream` passes unmodified.
6. Frontend type contracts hold: `is_game_cache_current` always returns `bool`, `get_ludusavi_launcher_shortcut_id` always `int`, `get_operation_status` always has `is_running`, `get_recent_logs` always a list.

## 6. Out of Scope — Do NOT do these

- Do not add timeouts to backup/restore/preview operations or touch the watchdog (that is finding **B3**, a separate plan).
- Do not replace `_run_blocking` with an executor/thread pool, however tempting.
- Do not modify `gateway.py`, `registry.py`, `coordinator.py`, or any frontend file.
- Do not edit `py_modules/pyludusavi-0.2.3.dist-info/` or any vendored file other than `discovery.py`.
- Do not make `_VERIFY_TIMEOUT_SECONDS` configurable.

## 7. Rollback

`git revert` of this plan's commits restores prior behavior completely. No persisted state, settings schema, or RPC contract changes are involved: the handler coercions only alter *failure-path* payload shapes (toward the frontend's existing tolerant handling), and the discovery patch only changes how long a verification subprocess may run. The vendored patch reverts with the same revert; `dist-info/RECORD` was never touched, so the tree returns to wheel-pristine.
