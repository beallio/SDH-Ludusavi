# Review: `fix/event-loop-blocking-rpcs` (commit `ba24b94`) vs. Implementation Plan

**Date:** 2026-06-10
**Reviewed commit:** `ba24b94` — `fix(rpc): eliminate event-loop-blocking RPCs and bound discovery` (the only commit on the branch vs. `main`)
**Plan reviewed against:** `docs/plans/2026-06-09_fix_event_loop_blocking_rpcs.md`
**Verdict:** ✅ **The implementation meets the plan.** All six acceptance criteria in plan §5 were re-verified by this review and hold (details in §2 below). The production code in `main.py` and `py_modules/pyludusavi/discovery.py` matches the plan's specified code essentially verbatim.

There are **4 findings, all in test code only. No production code changes are required.** Finding F1 is the one that genuinely matters: one of the two tests required by the plan's edge-case table is written in a way that it would still pass even if the exact bug it guards against were reintroduced. F2 is a CI-robustness issue (a regression would hang pytest forever instead of failing). F3 and F4 are optional strengthenings.

This document is written so that a follow-up agent can implement the fixes without reading the plan or the original commit. Every assumption is spelled out.

---

## 1. How to set up before touching anything (follow-up agent: start here)

1. You must be on branch `fix/event-loop-blocking-rpcs` with a clean `git status`. Run `git status --short` first; if there are uncommitted changes you did not create, stop and report (CLAUDE.md §18).
2. All project commands go through the wrapper script so caches land in `/tmp/sdh_ludusavi/` and never inside the repo (CLAUDE.md §5):
   ```bash
   ./run.sh uv sync
   ./run.sh uv run pytest        # baseline must be green: 485 passed as of this review
   ```
3. **TDD note (important):** Every fix in this document modifies *test files only*. Per CLAUDE.md §9, strict red-green TDD applies to behavior-changing implementation code, **not** to test refactors/strengthening. You do **not** need to write a failing test before fixing a test. However, the pre-commit hook runs `scripts/check_tdd.sh` plus ruff/ty/pytest — your test-only commit must still pass all of those.
4. **Do not touch these files under any circumstances** (they are correct and verified):
   - `main.py` — all handler bodies, `log`, `get_versions`, `_main`, `_call`, `_run_blocking`
   - `py_modules/pyludusavi/discovery.py` and anything under `py_modules/pyludusavi-0.2.3.dist-info/`
   - anything under `src/` (zero frontend changes is a plan invariant)
   - `tests/test_ludusavi_discovery.py` (both new discovery tests are correct as-is)
   - `tests/test_main.py::test_plugin_main_triggers_reconciliation` (line ~649) and `tests/test_main.py::test_run_blocking_uses_event_driven_daemon_future_without_polling` (line ~145)
5. The only files you will edit: `tests/test_main_rpc.py` and `tests/test_main.py`.

### Background facts you need (do not guess these; they are verified)

- `Plugin` in `main.py` has `self._backend: SDHLudusaviService | None = None` set in `__init__` (`main.py:53`). `Plugin._service()` (`main.py:56-64`) lazily constructs the service under `self._backend_lock` and **assigns it to `self._backend`** before returning it.
- `Plugin.log(...)` (`main.py:~196-212`) intentionally stays on the event loop. Its contract (plan §1 rule 3 and edge-case row 4) is two-fold:
  1. it must **never construct the service** (i.e. must not call `self._service()`), and
  2. when `self._backend is None`, the log line must go to `decky.logger.info(...)` with the format `f"[frontend:{level}] {operation or 'frontend'}: {message}"` — so `plugin.log("info", "test message")` produces exactly the string `"[frontend:info] frontend: test message"`.
- `Plugin._call(operation, callback)` (`main.py:~131-156`) runs `callback` on a worker thread and converts **any** exception into `{"status": "failed", "message": str(exc)}` (and `OperationLockedError` into a `"skipped"` dict). On success it returns the callback's return value unchanged.
- Test helpers live in `tests/test_main.py`: `fake_decky_module(tmp_path, settings_dir=...)` returns `(decky_namespace, FakeLogger)` where `FakeLogger` records into `.infos`, `.warnings`, `.errors`, `.exceptions` (lists of formatted strings). `import_main(monkeypatch, decky)` imports `main.py` as a module with that fake `decky`. `tests/test_main_rpc.py` imports both helpers via `from tests.test_main import fake_decky_module, import_main`.

---

## 2. What was verified as correct (no action needed — context only)

Re-verified during this review on 2026-06-10:

| Plan requirement | Status | Evidence |
|---|---|---|
| §3 2a–2e: five handler bodies (`is_game_cache_current`, `get_ludusavi_launcher_shortcut_id`, `get_operation_status`, `get_recent_logs`, `log`) reworked with coercion / fallback | ✅ matches plan verbatim | `git diff main..HEAD -- main.py` |
| §3 2f: `get_versions` eager-binding fix (`lambda: self._service().get_versions()`) | ✅ | `main.py:~291` |
| §3 2g: `_main` offloads construction via `_call("startup_init", self._service)` and reconciliation via `_call(...)`, with failed-dict logging | ✅ matches plan verbatim | `main.py:~313-339` |
| §3 Step 4: `_VERIFY_TIMEOUT_SECONDS = 15.0` + marker comment + `timeout=` on both `subprocess.run` branches + `TimeoutExpired` → `False` | ✅ | `py_modules/pyludusavi/discovery.py:7-12,89,102,105` (grep shows exactly 2 `timeout=_VERIFY_TIMEOUT_SECONDS` hits) |
| §5 AC1: full suite green, no test deleted/weakened; `test_plugin_main_triggers_reconciliation` unmodified | ✅ | `./run.sh uv run pytest` → **485 passed**; the test has no diff vs. `main` |
| §5 AC2: `ruff check`, `ruff format` (no diff), `ty check`, `pnpm run verify` | ✅ all pass | ran 2026-06-10; `pnpm run verify` = supply-chain check + 79 vitest tests + `tsc --noEmit`, exit 0 |
| §5 AC3: `grep -n "self._service()." main.py \| grep -v lambda` reports nothing | ✅ | exit code 1 (no matches) |
| §5 AC4: changes only to plan-§2 files; nothing under `src/` or `dist-info/` | ✅ | `git diff --stat main..HEAD` shows exactly: `main.py`, `py_modules/pyludusavi/discovery.py`, 3 test files, the plan, the session log |
| §5 AC5: `test_find_ludusavi_signature_is_clean_upstream` passes unmodified | ✅ | in the green suite; no diff |
| §5 AC6: type contracts (bool / int / `is_running` dict / list) | ✅ | coercion tests at `tests/test_main_rpc.py:133-239` |
| §3 Step 6: session log with design decisions (a) per-handler defaults, (b) `log` on-loop + fallback, (c) vendored-patch authorization & re-vendor follow-up | ✅ | `docs/agent_conversations/2026-06-10_fix_event_loop_blocking_rpcs.json` — all three present |
| Edge-case rows 4 & 6 extra tests exist | ✅ exist (but see F1/F4 for quality) | `tests/test_main_rpc.py:242`, `tests/test_main.py:756` |

---

## 3. Findings (fix in this order)

### F1 — `test_log_rpc_before_service_construction` cannot detect the regression it exists to prevent

**Severity:** Medium (test gap on an acceptance-criteria test; production code is fine)
**File:** `tests/test_main_rpc.py`, lines 242–259 (last test in the file)

**Current code (verbatim):**

```python
def test_log_rpc_before_service_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, _logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)

    mock_service = MockService()

    class FakePlugin(module.Plugin):
        def _service(self) -> Any:
            return mock_service

    plugin = FakePlugin()
    # plugin._backend is initially None because _service() hasn't been called.
    asyncio.run(plugin.log("info", "test message"))

    # Assert _backend remains None
    assert plugin._backend is None
```

**Why this is broken — walk through the regression scenario explicitly.** The plan's edge-case row 4 requires two outcomes when `log` arrives before service construction: (a) the line goes to `decky.logger`, and (b) the service is **not** constructed by `log`. Now suppose a future change reverts `Plugin.log` to the old buggy body `self._service().log(level, message, operation, game_name)`:

1. The test's `FakePlugin._service` override returns `mock_service` **without assigning `self._backend`** (the real `_service` assigns it; this override does not — that is the flaw).
2. `MockService.log(*args)` is a no-op (`tests/test_main_rpc.py:36-37`), so nothing raises.
3. The only assertion, `plugin._backend is None`, **still passes**, because the override never set `_backend`.
4. Outcome (a) is never asserted at all — the `FakeLogger` is bound to the discarded name `_logger` and never inspected.

So the test passes both before and after the exact regression it guards. It is vacuous.

**Required fix — replace the entire test with this (drop `MockService`/`FakePlugin` from it; they serve no purpose here):**

```python
def test_log_rpc_before_service_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def fail_service() -> Any:
        raise AssertionError("log must never construct the service")

    monkeypatch.setattr(plugin, "_service", fail_service)

    asyncio.run(plugin.log("info", "test message"))

    assert plugin._backend is None
    assert "[frontend:info] frontend: test message" in logger.infos
```

**Why each line of the fix is the way it is (do not "improve" it):**
- `plugin = module.Plugin()` — use the real class so `_backend` starts as `None` exactly like production.
- `fail_service` raising `AssertionError` — if `log` ever calls `self._service()` again, the test now fails loudly instead of silently passing. (`monkeypatch.setattr` on a plain instance attribute is the established pattern in this suite — see `tests/test_main.py:712` which does `monkeypatch.setattr(plugin, "_service", lambda: BlockingService())`.)
- The exact expected string `"[frontend:info] frontend: test message"` comes from `main.py`'s fallback: `decky.logger.info(f"[frontend:{level}] {operation or 'frontend'}: {message}")` with `level="info"`, `operation=None`, `message="test message"`. `FakeLogger.info` stores the already-formatted string unchanged (no `%`-args are passed), so an exact-match `in logger.infos` is correct. If this assertion fails with an off-by-format error, fix the **test's expected string** to match `main.py` — never change `main.py`.
- Keep the test name unchanged so the session-log / plan cross-references stay valid.

**Verification:** `./run.sh uv run pytest tests/test_main_rpc.py -q` → all pass. Then temporarily (do not commit) revert `Plugin.log`'s body to `self._service().log(level, message, operation, game_name)` and re-run: the test must now FAIL with the `AssertionError("log must never construct the service")`. Undo the temporary revert (`git checkout -- main.py`) and confirm green again.

---

### F2 — Loop-responsiveness test hangs pytest forever on regression instead of failing

**Severity:** Low (CI robustness; the test is correct when the code is correct)
**File:** `tests/test_main.py`, lines 700–725, test `test_is_game_cache_current_does_not_block_event_loop`

**Current relevant fragment (verbatim):**

```python
    class BlockingService:
        def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
            event.wait()
            return True
```

**Why this is a problem.** `event.wait()` has no timeout, and this repo has **no pytest-timeout plugin configured** (verified: no `timeout` setting in `pyproject.toml`, no `pytest.ini`/`setup.cfg`). Walk through the regression scenario: if `is_game_cache_current` ever reverts to calling the service synchronously **on the event loop**, then inside `scenario()` the created task runs `event.wait()` directly on the loop thread. The loop is now blocked; `await asyncio.sleep(0.01)` never resumes; nothing ever calls `event.set()` (that line is *after* the sleep); pytest hangs **indefinitely** — locally and in CI — instead of reporting a failure. (Note the existing sibling test `test_call_does_not_block_event_loop_while_callback_runs` at line 174 does not have this problem because it uses a bounded `time.sleep(0.15)`.)

**Required fix — one-line change inside `BlockingService` (leave every other line of the test untouched, including `event.set()` and both assertions):**

```python
    class BlockingService:
        def is_game_cache_current(self, installed_app_ids: str | None = None) -> bool:
            # Bounded wait: if the handler regresses to running on the event
            # loop, the elapsed-time assertion fails after ~5s instead of
            # hanging pytest forever (no pytest-timeout plugin is configured).
            event.wait(timeout=5.0)
            return True
```

**Why this works in both directions:**
- *Correct code (off-loop):* the worker thread waits, the loop stays free, `event.set()` fires at ~0.01 s, `event.wait(timeout=5.0)` returns immediately — identical behavior to today, test stays green and fast.
- *Regressed code (on-loop):* `event.wait(timeout=5.0)` blocks the loop for 5 s, then returns `False` (ignored), the handler returns, `asyncio.sleep(0.01)` finally resumes, and `assert time.perf_counter() - started < 0.08` **fails** (elapsed ≈ 5 s). A clean failure instead of a hang.

**Verification:** `./run.sh uv run pytest tests/test_main.py::test_is_game_cache_current_does_not_block_event_loop -q` → passes in well under 1 s (if it takes ~5 s, something is wrong — investigate, don't ship).

---

### F3 — `test_main_offloads_service_initialization` pre-seeds `_backend`, weakening what it proves (optional strengthening)

**Severity:** Informational / optional
**File:** `tests/test_main.py`, lines 728–753

**Observation.** The test sets `plugin._backend = FakeService()` and monkeypatches `_service` before running `_main`, so it proves `_main` *routes* both steps through `_call` (which is exactly the assertion the plan's Step 1c required — so this is **not** a plan violation), but it does not prove ordering, and it appends `"reconcile_call"` to `calls` via `FakeService.reconcile_pending_update_install` without ever asserting it.

**Optional fix — append two assertions at the end of the test (after the two existing `assert ... in calls` lines); change nothing else:**

```python
    assert calls.index("startup_init") < calls.index("reconcile_pending_update_install")
    assert "reconcile_call" in calls
```

The first asserts construction is offloaded *before* reconciliation runs (the order `_main` must preserve); the second asserts the reconcile callback actually executed the service method rather than merely being scheduled. Both pass against the current implementation (verified by reading `_main` at `main.py:~313-339`: `startup_init` is awaited and checked before the reconcile `_call` is made).

---

### F4 — `_main` failure-path test bypasses the real `_call` (optional integration variant)

**Severity:** Informational / optional
**File:** `tests/test_main.py`, lines 756–775, test `test_main_logs_initialization_failure_without_crashing`

**Observation.** The test fakes `_call` to *return* `{"status": "failed", "message": "disk exploded"}` for `startup_init`. That covers `_main`'s failed-dict branch (edge-case row 6's required outcome — so again, **not** a plan violation) but never exercises the real chain: callback raises on the worker thread → real `_call` converts to the failed dict → `_main` logs and returns. The conversion itself is what the plan relies on, and here it is only simulated.

**Optional fix — add this new test directly below the existing one (keep the existing one unchanged):**

```python
def test_main_logs_initialization_failure_via_real_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decky, logger = fake_decky_module(tmp_path, settings_dir=tmp_path / "settings")
    module = import_main(monkeypatch, decky)
    plugin = module.Plugin()

    def exploding_service() -> Any:
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(plugin, "_service", exploding_service)

    asyncio.run(plugin._main())

    assert any(
        "Service initialization failed during startup: disk exploded" in msg
        for msg in logger.errors
    )
```

**Why this works (facts verified in `main.py`):** `_main` calls `await self._call("startup_init", self._service)`; the monkeypatched `_service` raises `RuntimeError("disk exploded")` on the worker thread; the real `_call`'s `except Exception` branch returns `{"status": "failed", "message": "disk exploded"}` (and also records via `decky.logger.exception` — which lands in `logger.exceptions`, a different list; don't assert on that); `_main` sees `status == "failed"` and calls `decky.logger.error("Service initialization failed during startup: %s", "disk exploded")`; `FakeLogger.error` applies the `%s` formatting (via `_format_log`) and stores the final string in `logger.errors`. Because `_main` returns immediately after logging, `_service` is invoked exactly once — the raising stub never breaks anything downstream.

---

## 4. Definition of done for the follow-up agent

Work on branch `fix/event-loop-blocking-rpcs` (or a child branch if the user prefers; ask only if the branch has moved).

1. Apply F1 and F2 (required). F3 and F4 are recommended but optional — if skipped, say so in the session log.
2. Run the full gate, all via the wrapper (CLAUDE.md §12):
   ```bash
   ./run.sh uv run ruff check . --fix
   ./run.sh uv run ruff format .
   ./run.sh uv run ty check py_modules/sdh_ludusavi/
   ./run.sh uv run pytest          # expect 485 passed if only F1+F2 (no new tests), 486 if F4's new test is added
   pnpm run verify
   ```
3. Confirm `git status --porcelain` shows **only** `tests/test_main_rpc.py`, `tests/test_main.py`, your session log, and (if you update it) this review file. Nothing else.
4. Commit with a Conventional Commit, e.g.:
   ```
   test(main): strengthen log-fallback and loop-responsiveness regression tests
   ```
   This is a test-only change — strict TDD red-first does not apply (CLAUDE.md §9), but pre-commit hooks must pass.
5. Write a session log to `docs/agent_conversations/<YYYY-MM-DD>_event_loop_rpc_test_hardening.json` with the standard fields (`date`, `task_objective`, `files_modified`, `tests_added`, `design_decisions`, `results`). Under `design_decisions`, record: (a) why the F1 test was rewritten (vacuous against the guarded regression), (b) why `event.wait` got a 5 s bound (no pytest-timeout plugin).
6. Do **not** modify `main.py`, anything under `py_modules/`, or anything under `src/`. If any fix in this document appears to require that, the document is wrong — stop and report instead of improvising.

## 5. Explicit non-findings (checked and fine — do not "fix" these)

- `_call`'s `except asyncio.CancelledError: raise` appearing *after* `except Exception` is correct: `CancelledError` derives from `BaseException` in Python ≥ 3.8, so `except Exception` does not swallow it. Out of scope regardless (plan forbids touching `_call`).
- The session log `files_modified` omits the session log file itself — trivial, not worth a fix.
- The plan's Step 3 test code included an unused `import subprocess` in `test_verify_passes_timeout_to_subprocess_run`; the implementation correctly dropped it (ruff would flag it). Intentional, fine.
- Discovery worst case is now ~4 candidates × 15 s = 60 s, running off-loop — this matches plan §3 Step 4's stated bound; it is not a bug.
- `pnpm run verify` was run and passed even though no frontend files changed — required by plan §3 Step 5.
