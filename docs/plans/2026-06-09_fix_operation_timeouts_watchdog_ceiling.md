# Implementation Plan: Bound Ludusavi Operations and Add Watchdog Absolute Resume Ceiling (Review Finding B3)

**Plan file destination in repo:** `docs/plans/2026-06-09_fix_operation_timeouts_watchdog_ceiling.md`
**Branch:** create from the current integration branch, named `fix/operation-timeouts-watchdog-ceiling`
**Prerequisites assumed already merged:** B1 (`compare_recency` direction safety — `lifecycle.py` now contains `_timestamp_direction`/`_conflict_response` and the adapter returns `backup_differs`) and B4 (Syncthing TLS). This plan is independent of B2; it can land before or after it with no conflicts (B2 touches `main.py` + `pyludusavi/discovery.py`; this plan touches `sdh_ludusavi/ludusavi.py`, `constants.py`, `watchdog.py`).
**Estimated scope:** 3 backend modules, ~10 new/updated tests, **zero vendored-library changes**, **zero frontend changes**, no persisted-state changes.

---

## 1. Problem Statement (read fully before editing anything)

### 1a. Unbounded operations under a global lock with no cancellation

`pyludusavi` deliberately defaults backup and restore to **no timeout** (`py_modules/pyludusavi/main.py:171` and `:266` — `timeout: Optional[float] = None  # Operations default to no timeout`). The plugin's adapter never overrides this:

| Call site (`py_modules/sdh_ludusavi/ludusavi.py`) | Underlying client call | Effective timeout today |
|---|---|---|
| `PyludusaviAdapter.backup()` | `self._client.backup(games=[...], preview=..., force=True)` | **None (infinite)** — for both real backups **and previews** |
| `PyludusaviAdapter.restore()` | `self._client.restore(games=[...], preview=..., force=True)` | **None (infinite)** |
| `refresh_statuses()` | `self._client.backup(preview=True)` (in a `ThreadPoolExecutor`) | **None (infinite)** |
| `refresh_statuses()` | `self._client.backups_list(...)` | 30 s (executor default — `backups_list` exposes no `timeout` param) |
| `compare_recency()` | `self._client.restore(games=[...], preview=True)` | **None (infinite)** |
| `compare_recency()` / `get_conflict_metadata()` | `self._client.backups_list(...)` | 30 s (executor default) |
| `get_conflict_metadata()` | `self._client.backup(games=[...], preview=True, force=True)` | **None (infinite)** |

Every one of these runs inside `OperationCoordinator.run_locked` (or feeds a flow that does). The lock is global and there is **no cancellation RPC**. Consequence: a single hung Ludusavi invocation (rclone cloud-sync stall, network-mounted backup directory, dead FUSE mount) makes every subsequent operation return `operation_running` **forever**, until the user reloads the plugin.

### 1b. The watchdog defers indefinitely while an operation "runs"

During the launch gate the frontend SIGSTOPs the game's process tree. `ProcessWatchdog._check_and_resume_stuck_pids` (`py_modules/sdh_ludusavi/watchdog.py:139-152`) auto-resumes processes paused longer than a hardcoded `15.0` seconds — **but returns early whenever `self._is_operation_running()` is true**. Combined with 1a, a hung restore leaves the user's game frozen with no recovery path. Even after 1a is fixed, the deferral has no absolute ceiling: if the coordinator's `is_running` flag were ever wedged true, paused processes would never resume.

### Target behavior (the contract you are implementing)

1. **Every Ludusavi subprocess launched by the adapter is time-bounded.** Two budgets, defined as constants:
   - `LUDUSAVI_OPERATION_TIMEOUT_SECONDS = 900.0` — real (non-preview) backup and restore. Generous because Ludusavi cloud sync of large saves over slow links is legitimate.
   - `LUDUSAVI_PREVIEW_TIMEOUT_SECONDS = 300.0` — all previews and recency checks. Generous because the `backup` command may piggyback a manifest update on first run. Note this also bounds the worst-case launch-gate pause introduced by `check_game_start` (game stays SIGSTOPped while the recency preview runs), which today is infinite.
2. **A timeout is an ordinary operation failure.** `LudusaviExecutor.execute` already converts `subprocess.TimeoutExpired` into `LudusaviError("Ludusavi command timed out after …")` (`py_modules/pyludusavi/core.py:103-105`), and `subprocess.run` kills the child process on timeout, so no orphan cleanup is needed. The exception must propagate through the **existing** failure paths — `run_locked` releases the lock in its `finally`, records `last_result="failed"`, lifecycle records failure history, `_call` converts to `{"status": "failed", message}`, and the frontend's existing failure toast/strip handling fires. **You are not adding any new error type, status string, or frontend handling.**
3. **The watchdog gains an absolute resume ceiling.** While an operation is running, the existing 15 s idle-resume stays deferred — but any process paused longer than `WATCHDOG_ABSOLUTE_RESUME_SECONDS` (operation budget + 60 s) is resumed **unconditionally**, with a distinct warning log.
4. **No vendored changes.** `pyludusavi.backup`/`restore` already accept `timeout=`; `backups_list` is already bounded at 30 s by the executor default. Everything lands in `sdh_ludusavi`.

### Invariants you must not break

- Do not modify anything under `py_modules/pyludusavi/` or `py_modules/pyludusavi-0.2.3.dist-info/`.
- Do not change `coordinator.py`, `lifecycle.py`, `main.py`, or any file under `src/`. The B1 logic in `lifecycle.py` (`_timestamp_direction`, `backup_differs` handling) must be untouched.
- Do not change the `LudusaviAdapter` protocol in `types.py` — `backup(game_name, preview=False)` / `restore(game_name, preview=False)` signatures stay as-is; timeouts are internal to the concrete adapter.
- The known propagation routes (verify after implementation, they are all pre-existing): a timeout in `refresh_statuses` → `registry.refresh_games` broad-except → cached fallback with `dependency_error`; in `check_game_exit`'s preview → existing broad-except → skip `preview_failed`; in `compare_recency`'s restore preview → already caught inside `compare_recency` → `"ambiguous"` → conflict modal; in `compare_recency`'s **`backups_list`** call (which sits *outside* its try block) → propagates → `run_locked` failed → `_call` failed dict → frontend failure notification. All acceptable; none require code changes.
- Follow the repo TDD protocol (`AGENTS.md` §9, `scripts/check_tdd.sh`): failing test first, then implementation.

---

## 2. Files You Will Touch (exhaustive list)

| File | Action |
|---|---|
| `py_modules/sdh_ludusavi/constants.py` | Add 4 constants |
| `py_modules/sdh_ludusavi/ludusavi.py` | Pass explicit `timeout=` at 5 client call sites; import constants; docstring updates |
| `py_modules/sdh_ludusavi/watchdog.py` | Replace hardcoded `15.0`; add absolute-ceiling logic; import constants |
| `tests/test_ludusavi.py` | Update fake-client signatures; add timeout-propagation tests |
| `tests/test_watchdog.py` | Add 2 ceiling tests |
| `tests/test_service.py` | Add 1 lock-release-after-timeout test |
| `README.md` | One sentence in "Understanding Status Messages" area (see Step 7) |
| `docs/plans/2026-06-09_fix_operation_timeouts_watchdog_ceiling.md` | This plan, committed per repo convention |
| `docs/agent_conversations/<date>_fix_operation_timeouts_watchdog_ceiling.json` | Session log per `AGENTS.md` §15 |

**Known hazard you must handle:** `tests/test_ludusavi.py` contains several fake Ludusavi *clients* with strict method signatures that will break the moment the adapter starts passing `timeout=`. Identified by `grep -n "def backup\|def restore\|def backups_list" tests/test_ludusavi.py`:
- line ~98: `def backup(self, preview: bool = False, **kwargs: object)` — already tolerant (`**kwargs`), no change.
- line ~153: `def backups_list(self, games: list[str] | None = None)` — adapter does not pass timeout to `backups_list`, no change needed, but verify.
- lines ~157 and ~164: `def restore(...)` / `def backup(...)` on `FakeLudusaviClient` — **must** gain `timeout: float | None = None` (or `**kwargs: object`) and should *record* the received timeout for assertions.
- lines ~258/262: inline fake with `def backup(self, games=None, preview=False)` — **must** gain `**kwargs`.

Re-run the grep after editing and inspect every hit; also grep `tests/test_exception_boundaries.py` the same way (its fakes raise before signature mismatch would matter, but verify by running it).

---

## 3. Step-by-Step Implementation

### Step 0 — Environment and baseline

```bash
cd <repo-root>
./run.sh uv sync
./run.sh uv run pytest          # must be green; record passing count
pnpm install --frozen-lockfile --ignore-scripts
```

Read in full before editing: `py_modules/sdh_ludusavi/ludusavi.py`, `watchdog.py`, `coordinator.py` (read-only — to confirm the `finally`-release), `tests/test_ludusavi.py` (fixture/fake structure), `tests/test_watchdog.py` (how existing tests neutralize real signaling — note whether they monkeypatch `watchdog._send_signal_tree` or `os.kill`; **mirror exactly what they do**, never signal real PIDs from tests).

### Step 1 — Constants

**File:** `py_modules/sdh_ludusavi/constants.py`. Append:

```python
# Upper bound for real (non-preview) Ludusavi backup/restore subprocesses.
# Deliberately generous: Ludusavi-managed cloud sync of large saves over slow
# links is legitimate. On expiry, subprocess.run kills the child and the
# operation surfaces as an ordinary failure, releasing the global lock.
LUDUSAVI_OPERATION_TIMEOUT_SECONDS = 900.0

# Upper bound for preview/recency Ludusavi subprocesses. Generous because the
# backup command may perform a manifest update on first run. This also bounds
# the worst-case launch-gate pause during check_game_start.
LUDUSAVI_PREVIEW_TIMEOUT_SECONDS = 300.0

# Watchdog: resume a SIGSTOPped game after this long when NO operation is
# running (pre-existing behavior, previously hardcoded as 15.0 in watchdog.py).
WATCHDOG_STUCK_RESUME_SECONDS = 15.0

# Watchdog: resume a SIGSTOPped game after this long UNCONDITIONALLY, even if
# an operation still claims to be running. Sized to outlast the longest legal
# operation so it only fires when something is genuinely wedged.
WATCHDOG_ABSOLUTE_RESUME_SECONDS = LUDUSAVI_OPERATION_TIMEOUT_SECONDS + 60.0
```

### Step 2 — RED: adapter timeout tests

**File:** `tests/test_ludusavi.py`

2a. First make the fakes tolerant **and** observable. On `FakeLudusaviClient` (line ~140), change `backup` and `restore` to accept and record the timeout:

```python
    def restore(
        self,
        games: list[str] | None = None,
        preview: bool = False,
        force: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.calls.append(("restore", tuple(games or ()), preview, timeout))
        ...

    def backup(
        self,
        games: list[str] | None = None,
        preview: bool = False,
        force: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.calls.append(("backup", tuple(games or ()), preview, timeout))
        ...
```

Adapt to the file's actual recording convention — if the fakes don't currently record calls, add a `self.calls: list[tuple] = []` to their `__init__`. Add `**kwargs: object` to the inline fakes at lines ~98 (already has it) and ~258/262.

2b. Add the tests (mirror the file's existing `_make_adapter` construction):

```python
from sdh_ludusavi.constants import (
    LUDUSAVI_OPERATION_TIMEOUT_SECONDS,
    LUDUSAVI_PREVIEW_TIMEOUT_SECONDS,
)


def test_adapter_backup_passes_operation_timeout() -> None:
    adapter, client = _make_adapter_with_client(...)  # mirror existing helper; expose the fake client
    adapter.backup("Hades")
    assert ("backup", ("Hades",), False, LUDUSAVI_OPERATION_TIMEOUT_SECONDS) in client.calls


def test_adapter_backup_preview_passes_preview_timeout() -> None:
    adapter, client = _make_adapter_with_client(...)
    adapter.backup("Hades", preview=True)
    assert ("backup", ("Hades",), True, LUDUSAVI_PREVIEW_TIMEOUT_SECONDS) in client.calls


def test_adapter_restore_passes_operation_timeout() -> None:
    adapter, client = _make_adapter_with_client(...)
    adapter.restore("Hades")
    assert ("restore", ("Hades",), False, LUDUSAVI_OPERATION_TIMEOUT_SECONDS) in client.calls


def test_refresh_statuses_uses_preview_timeout() -> None:
    """The bulk preview inside refresh_statuses must pass the preview budget."""
    ...  # assert the fake client's backup call recorded timeout == LUDUSAVI_PREVIEW_TIMEOUT_SECONDS


def test_compare_recency_restore_preview_uses_preview_timeout() -> None:
    ...  # assert the restore(preview=True) call recorded the preview timeout


def test_get_conflict_metadata_preview_uses_preview_timeout() -> None:
    ...  # assert the backup(preview=True, force=True) call recorded the preview timeout
```

Where the existing `_make_adapter` helper hides the client, add a sibling helper `_make_adapter_with_client` that returns `(adapter, fake_client)`; do not rewrite existing tests to use it. Run and confirm all six fail with `timeout == None` recorded:

```bash
./run.sh uv run pytest tests/test_ludusavi.py -k timeout -x -q
```

### Step 3 — GREEN: adapter changes

**File:** `py_modules/sdh_ludusavi/ludusavi.py`

3a. Add to imports:

```python
from .constants import (
    LUDUSAVI_OPERATION_TIMEOUT_SECONDS,
    LUDUSAVI_PREVIEW_TIMEOUT_SECONDS,
)
```

3b. `backup` method — replace:

```python
    def backup(self, game_name: str, preview: bool = False) -> dict[str, object]:
        timeout = (
            LUDUSAVI_PREVIEW_TIMEOUT_SECONDS if preview else LUDUSAVI_OPERATION_TIMEOUT_SECONDS
        )
        return cast(
            dict[str, object],
            self._client.backup(
                games=[game_name], preview=preview, force=True, timeout=timeout
            ).data,
        )
```

3c. `restore` method — identical pattern with `self._client.restore(...)`.

3d. `refresh_statuses` — both `executor.submit(self._client.backup, ...)` branches gain `timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS` (pass it as a keyword in the `submit` call, e.g. `executor.submit(self._client.backup, games=game_names, preview=True, timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS)`). Leave both `backups_list` submits untouched (no timeout parameter exists; executor default 30 s applies — add a one-line comment saying exactly that).

3e. `compare_recency` — the `self._client.restore(games=[game_name], preview=True)` call gains `timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS`. Do not move the `backups_list` call into the try block; its 30 s default and propagation path are intentional (see §1 invariants).

3f. `get_conflict_metadata` — the `self._client.backup(games=[game_name], preview=True, force=True)` call gains `timeout=LUDUSAVI_PREVIEW_TIMEOUT_SECONDS`.

3g. Verify there are exactly five new `timeout=` keywords:

```bash
grep -n "LUDUSAVI_OPERATION_TIMEOUT_SECONDS\|LUDUSAVI_PREVIEW_TIMEOUT_SECONDS" py_modules/sdh_ludusavi/ludusavi.py
```

Expected: the import block, two uses in `backup`/`restore` ternaries, and three preview call sites (`refresh_statuses`, `compare_recency`, `get_conflict_metadata`). Run Step 2's tests — all green — then the full `tests/test_ludusavi.py` and `tests/test_exception_boundaries.py`.

### Step 4 — RED: lock-release-after-timeout test at the service level

**File:** `tests/test_service.py`. Append, mirroring the file's established service-with-fake-adapter construction (template: the tests around lines 880–940 that set `adapter.recency` and call lifecycle methods):

```python
def test_force_backup_timeout_fails_and_releases_operation_lock(tmp_path: Path) -> None:
    """A LudusaviError (e.g. subprocess timeout) during backup must surface as a
    failed RPC payload, record failure history, and leave the global lock free
    so the next operation can run."""
    from pyludusavi import LudusaviError

    service, adapter = _make_service(tmp_path, ...)  # mirror existing helper
    calls = {"n": 0}

    def flaky_backup(game_name: str, preview: bool = False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LudusaviError("Ludusavi command timed out after 900.0s: [...]")
        return {"games": {game_name: {}}}

    adapter.backup = flaky_backup

    with pytest.raises(LudusaviError):
        service.force_backup("Hades")

    history = service.get_game_history()["Hades"]
    assert history["last_failure"]["message"].startswith("Ludusavi command timed out")
    assert service.get_operation_status()["is_running"] is False

    # Lock must be free: a second backup attempt reaches the adapter and succeeds.
    result = service.force_backup("Hades")
    assert result["status"] == "backed_up"
    assert calls["n"] == 2
```

> Note on the `pytest.raises`: at the **service** layer `force_backup` re-raises (history is recorded in lifecycle's except-then-raise); the conversion to `{"status": "failed"}` happens in `main.Plugin._call`. If the existing test file's helpers exercise force_backup through a plugin-level wrapper instead, adapt the assertion to the failed-dict form — read the neighboring tests first and match the layer they use. The two non-negotiable assertions are: failure history recorded with the timeout message, and the **second** call succeeding (lock released).

Run; confirm it fails only if your helper wiring is wrong (the lock-release behavior already exists via `run_locked`'s `finally`) — this test is a **regression guard**, and it is acceptable for it to pass immediately once wired correctly. Document that in the session log rather than forcing an artificial red.

### Step 5 — RED: watchdog ceiling tests

**File:** `tests/test_watchdog.py`. First read the three existing tests (lines 19–84) and copy exactly how they (a) construct `ProcessWatchdog`, (b) neutralize real signaling, (c) backdate `wd._paused_pids[pid]`. Then append:

```python
def test_watchdog_defers_resume_while_operation_running_within_ceiling() -> None:
    """Paused 60s with an operation running: must NOT be resumed (pre-existing
    deferral behavior, now bounded)."""
    # is_operation_running -> True; paused_at = time.time() - 60
    # call wd._check_and_resume_stuck_pids(); assert pid still in wd._paused_pids
    # and no resume/signal recorded.


def test_watchdog_resumes_past_absolute_ceiling_even_when_operation_running() -> None:
    """Paused longer than WATCHDOG_ABSOLUTE_RESUME_SECONDS with an operation
    running: MUST be resumed, and the warning log must mention the absolute
    ceiling."""
    from sdh_ludusavi.constants import WATCHDOG_ABSOLUTE_RESUME_SECONDS
    # is_operation_running -> True
    # paused_at = time.time() - (WATCHDOG_ABSOLUTE_RESUME_SECONDS + 1)
    # call wd._check_and_resume_stuck_pids(); assert pid resumed (removed from
    # _paused_pids / resume recorded) and a warning containing "absolute" was logged.
```

Implement both fully using the file's existing fixtures. Run and confirm the second test **fails** (current code early-returns while the operation is running):

```bash
./run.sh uv run pytest tests/test_watchdog.py -x -q
```

### Step 6 — GREEN: watchdog changes

**File:** `py_modules/sdh_ludusavi/watchdog.py`

6a. Add to imports:

```python
from .constants import (
    WATCHDOG_ABSOLUTE_RESUME_SECONDS,
    WATCHDOG_STUCK_RESUME_SECONDS,
)
```

6b. Replace `_check_and_resume_stuck_pids` in its entirety:

```python
    def _check_and_resume_stuck_pids(self) -> None:
        now = time.time()
        stuck: list[tuple[int, float, str]] = []
        with self._paused_pids_lock:
            if not self._paused_pids:
                self._watchdog_active = False
                return
            operation_running = self._is_operation_running()
            for pid, paused_at in list(self._paused_pids.items()):
                paused_for = now - paused_at
                if paused_for > WATCHDOG_ABSOLUTE_RESUME_SECONDS:
                    # Unconditional safety net: even a (claimed) running
                    # operation may not keep a game suspended past the longest
                    # legal operation duration.
                    stuck.append((pid, paused_for, "absolute ceiling"))
                elif not operation_running and paused_for > WATCHDOG_STUCK_RESUME_SECONDS:
                    stuck.append((pid, paused_for, "idle timeout"))

        for pid, paused_for, why in stuck:
            self._log(
                "warning",
                f"Watchdog detected PID {pid} suspended for {paused_for:.0f}s "
                f"({why} exceeded). Resuming automatically.",
                "watchdog",
                None,
            )
            try:
                self.resume(pid)
            # Intentionally broad: catch automatic resume errors in background watchdog thread
            except Exception as exc:
                self._log(
                    "error",
                    f"Watchdog failed to resume stuck PID {pid}: {exc}",
                    "watchdog",
                    None,
                )
```

Behavioral notes you must preserve: the lock is held only for the scan (resumes happen outside it, as before); the `_watchdog_active = False` short-circuit on empty map stays; the warning text for the idle case may change wording, but it must remain a `"warning"`-level log through `self._log` (the existing auto-resume test asserts resume behavior — re-run it; if it asserts exact log text, update the *expected text* in that test minimally and note it in the session log).

Run Step 5's tests — both green — plus the whole `tests/test_watchdog.py`.

### Step 7 — Documentation

7a. **README.md** — in the "Understanding Status Messages" section (or directly after the Automatic Sync feature bullet if that reads more naturally), add one sentence:

> Backups and restores are limited to 15 minutes (status checks to 5 minutes); if Ludusavi exceeds this — for example, a stalled cloud sync — the operation is reported as failed instead of hanging, and any paused game is resumed automatically.

7b. Commit this plan to `docs/plans/2026-06-09_fix_operation_timeouts_watchdog_ceiling.md` and write the session log JSON to `docs/agent_conversations/` (fields: `date`, `task_objective`, `files_modified`, `tests_added`, `design_decisions`, `results`). Under `design_decisions`, record: the two budget values and their rationale, the decision **not** to add a cancellation RPC (out of scope, future work), the decision to leave `backups_list` on the executor's 30 s default, and the Step 4 regression-guard note if that test passed immediately.

### Step 8 — Full verification sweep

```bash
grep -rn "timeout=None" py_modules/sdh_ludusavi/ && echo "FAIL" || echo OK
grep -c "LUDUSAVI_PREVIEW_TIMEOUT_SECONDS" py_modules/sdh_ludusavi/ludusavi.py   # expect >= 4 (import + 3 sites)
git status --porcelain                                                            # only §2 files
./run.sh uv run ruff check .
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run verify
```

`pnpm run verify` is required by the commit gate even though no frontend file changed.

---

## 4. Edge Cases — Required Behavior Table

| # | Scenario | Required outcome | Test |
|---|---|---|---|
| 1 | Real backup exceeds 900 s (stalled cloud sync) | Child killed by `subprocess.run`; `LudusaviError` → failed history + failed RPC payload + failure toast; lock free immediately after | ✅ Step 4 |
| 2 | Next operation right after a timeout | Succeeds (lock was released in `run_locked` finally) | ✅ Step 4 (second call) |
| 3 | Launch-gate recency preview hangs | Bounded at 300 s; game resumes via existing post-RPC `resumeGameProcessCall` in the frontend `finally`, watchdog as backstop | adapter test ✅; integration implicit |
| 4 | Exit-check preview times out | Existing broad-except → skip `preview_failed`; silent (already in frontend `silentReasons`? — it is not; it routes to `completeAutoSyncStatus`, acceptable) | existing path; no new test required |
| 5 | `refresh_games` preview times out | Existing broad-except → cached games + `dependency_error` string | existing path |
| 6 | Game paused 60 s while a *legitimate* slow restore runs | NOT resumed (deferral preserved) | ✅ Step 5 test 1 |
| 7 | Game paused > 960 s with operation flag stuck true | Resumed unconditionally with "absolute ceiling" warning | ✅ Step 5 test 2 |
| 8 | `compare_recency`'s `backups_list` (outside its try) times out at 30 s | Propagates → failed RPC → frontend failure handling; no wedge | invariant, documented, no code change |
| 9 | Legitimate 14-minute cloud-synced backup | Completes normally (under budget) | implicit |
| 10 | Fake clients in tests receive the new `timeout` kwarg | No `TypeError` anywhere in the suite | Step 2a + full suite |

## 5. Acceptance Criteria (all must hold)

1. Full `./run.sh uv run pytest` green, including all new tests; no previously passing test deleted; only permitted edits to existing tests are the fake-client signature additions (Step 2a) and, if necessary, the watchdog log-text expectation (Step 6b note).
2. `ruff check`, `ruff format` (no diff), `ty check`, `pnpm run verify` all pass.
3. `git status` shows changes only to the files listed in §2 — in particular, **nothing** under `py_modules/pyludusavi/`, `src/`, `coordinator.py`, `lifecycle.py`, or `main.py`.
4. Every non-`backups_list` client invocation in `ludusavi.py` carries an explicit `timeout=` constant (verified by Step 8 greps and Step 2 assertions).
5. Watchdog: deferral within ceiling preserved; unconditional resume past ceiling proven by test.
6. `WATCHDOG_ABSOLUTE_RESUME_SECONDS` is derived from `LUDUSAVI_OPERATION_TIMEOUT_SECONDS` (single source of truth) — changing the operation budget must automatically move the ceiling.

## 6. Out of Scope — Do NOT do these

- No cancellation RPC, no process-group kill plumbing, no progress reporting (candidate future work; record in session log only).
- No user-facing settings for the budgets; constants only.
- No changes to `_run_blocking`, the coordinator lock model, or event-loop handler wiring (that is finding **B2**).
- No vendored `pyludusavi` edits — if you believe one is required, **stop and report** instead of improvising.
- Do not "fix" the `backups_list` 30 s executor default by patching the vendored library; leave it documented.

## 7. Rollback

`git revert` of this plan's commits restores prior behavior completely. No persisted state, settings schema, RPC names, or response shapes change: timeouts only convert a previously-infinite hang into the **already-existing** failure path, and the watchdog change only adds an additional resume condition. A reverted build reads all on-disk state identically; nothing new is written anywhere.
