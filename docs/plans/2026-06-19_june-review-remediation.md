# Remediate June 18 Review Findings

```text
TITLE=Remediate June 18 Review Findings
SLUG=june-review-remediation
PLAN_PATH=docs/plans/2026-06-19_june-review-remediation.md
```

## Context

Three review documents landed in `docs/review/` on 2026-06-18:

- `2026-06-18_gpt-5_code_review.md` (8 security/correctness findings)
- `2026-06-18_gpt-5_dev_holistic_thermo-nuclear-review.md` (10 architecture/correctness findings)
- `2026-06-18_thermo-nuclear-code-quality-review.md` (narrative; 2 "blockers" + cleanups)

The findings overlap heavily, and **a large fraction are already remediated or factually wrong** because the `dev` branch moved on (the `code-quality-fixes` branch merged just before these reviews were written). This plan acts only on findings that are **verified to have merit in the current `dev` tree**. The goal: land the genuine correctness and security fixes plus the agreed medium refactors, each as an atomic, test-backed change, without destabilizing the plugin.

**Scope decision (already made):** correctness/security fixes + medium refactors. **Excluded** (do NOT implement, even though some have merit): event-driven QAM capture rewrite, full-commit-SHA pinning of all GitHub Actions, and the largest decompositions (QAM god-component split, update-controller state-machine reducer, lifecycle transaction extraction, full PluginUpdater module split). The `setup-uv` version pin (a small piece of the workflow hardening) **is** in scope.

You are the implementer. Develop on a branch off `dev`. Do not write reviews. Do not create, delete, or edit anything under `docs/review/` except committing review notes the orchestrator writes there.

---

## Findings Assessment (do not re-litigate)

**Has merit — in scope (work units below):**

| Finding | Source | Work unit |
|---|---|---|
| Process pause/resume signals any PID>1, no target identity capture, PID-reuse risk | gpt-5 #1 | WU-B |
| Fuzzy match returns first substring candidate → non-deterministic | gpt-5 #3 | WU-C |
| State lock timeout returns None; callers proceed without exclusion (not fail-closed) | gpt-5 #6 | WU-A |
| Late/timed-out settings response reapplies whole stale snapshot, clobbers newer fields | gpt-5 #4 / holistic #1 | WU-H |
| `install()` ignores `recordUpdateInstallRequestedCall()` result; installer runs after persistence failure | gpt-5 #5 / holistic #2 | WU-F |
| Syncthing manager mutex held during credential discovery, network calls, thread joins | gpt-5 #7 | WU-E |
| Backup browser stats every file / loads every ZIP entry inside the global op lock | gpt-5 #8 | WU-D |
| Settings duplicated in snapshot vs `settings`; `syncSelectedGameCache()` repairs divergence | holistic #4 | WU-G |
| Lifecycle backup/restore methods duplicate op-lock/history/refresh/result skeleton | holistic #8 | WU-I |
| Quality-gate sequence duplicated; hooks call `pnpm run verify` outside `./run.sh`; `setup-uv` uses `latest` | holistic gates / gpt-5 #2 (partial) | WU-J |
| `main.py _call` `except BaseException` swallows `SystemExit`/`KeyboardInterrupt` | code-quality pre-existing | WU-F |
| `MutateOptions` fields typed `any` despite generics | code-quality #3 | WU-H |
| Dead `service: Any` constructor param (actually in `watchdog.py`, not coordinator/log_buffer) | code-quality #8 (misattributed) | WU-B |

**No merit / already fixed — DO NOT act on these:**

- Architectural guard tests "gutted/deleted" — **false**. `git log` shows `4caca47 test(architecture): restore deleted architecture guard tests`. `test_architecture.py` (159 lines), `test_module_size_budgets.py`, `test_status_flow_diagram.py` all present and enforcing budgets.
- `_warn_load` logs wrong cache path — **already fixed**: it now logs no path (`"Ignoring SDH-ludusavi state: %s", reason`). (Optional micro-enhancement only; not worth a change. Skip.)
- Atomic-write duplication in `persistence.py` — **already factored** into shared `_atomic_json_write()`.
- Dead `service: Any` in `coordinator.py` / `log_buffer.py` — **false** (neither has it).
- Dead `isMounted` / `setBusyLabel` in `SettingsMutationControllerOptions` — **false** (type has only `ludusaviStore`, `notifyFailure`).
- Duplicate `silentReasons` array at lines 255/420 — **false** (`SILENT_SKIPPED_REASONS` defined once at line 26).
- Duplicate `isSyncthingStatus` across surface/renderer — **false** (already consolidated in `autoSyncStatusRenderer.tsx`; surface imports it).
- Workflow tests "enforce mutable tags" — **false** (actions pinned to major versions; tests assert the pins). Only the `setup-uv: latest` piece is real → WU-J.

**Has merit but excluded by scope (do NOT implement):** event-driven QAM capture (gpt-5/holistic QAM polling), full-SHA action pinning, QAM god-component decomposition (holistic #6), update-controller state-machine reducer (holistic #2 full refactor — only the correctness fix is in WU-F), lifecycle start/exit transaction extraction (holistic #5), full PluginUpdater split (holistic #7).

---

## Orchestration Contract

Plan path:
```text
docs/plans/2026-06-19_june-review-remediation.md
```
Implementation branch:
```text
feat/june-review-remediation
```
Round-complete marker:
```text
/tmp/sdh_ludusavi/june-review-remediation_finished
```
Finalized marker:
```text
/tmp/sdh_ludusavi/june-review-remediation_finalized
```
Review notes (audit records — committed, never deleted/edited by you):
```text
docs/review/june-review-remediation-review-*.md
```

Each review note ends with exactly one of `STATUS: CHANGES_REQUESTED` or `STATUS: APPROVED`.

**Setup:** Use the `implementer` skill. Create `feat/june-review-remediation` off `dev`. Write this plan to `docs/plans/2026-06-19_june-review-remediation.md` and commit it first.

**On completing a round (initial implementation or a review round):**
1. Run the quality gates (see "Quality Gates").
2. Ensure the working tree is clean.
3. Commit all relevant changes (Conventional Commits, atomic per work unit).
4. Write the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished june-review-remediation
   ```
5. Then either keep polling `docs/review/june-review-remediation-review-*.md` or exit cleanly (the orchestrator resumes you via `agy -c -p`). On every resume, scan existing review notes **first** before waiting for new file events.

**When a `STATUS: CHANGES_REQUESTED` note appears:**
1. `scripts/orchestration/clear-finished june-review-remediation`
2. Read the note; implement every requested change.
3. Run quality gates; commit the fixes.
4. Commit the review note if not already committed.
5. `scripts/orchestration/mark-finished june-review-remediation`
6. Keep polling or exit cleanly.

**When a `STATUS: APPROVED` note appears:**
1. Confirm all review notes are committed and the tree is clean.
2. `scripts/orchestration/finalize june-review-remediation`
3. Confirm `/tmp/sdh_ludusavi/june-review-remediation_finalized` exists.
4. Stop polling and exit. (Finalize merges `feat/june-review-remediation` into `dev`, cleans up the branch, pushes `dev`, and requests a dev release. Steam Deck / on-device testing is deferred until after the dev push.)

---

## Work Units

Each work unit is an atomic commit (a couple allow a backend commit + frontend commit). Implement in the order below. Strict TDD: write the failing test first, then the minimal fix. Run the full suite after each.

### Ordering & combination rationale
- **Combine** backend matcher + frontend `isTracked` (WU-C): the finding requires the launch gate not to activate for a game the backend will reject — they must change together.
- **Combine** `main.py _call` hardening + frontend install-abort (WU-F): one RPC contract spans both; backend commit first, frontend commit second.
- **Combine** CI gate dedup + `setup-uv` pin (WU-J): same workflow/script surface.
- **Sequence** WU-G before WU-H: collapsing duplicate settings state first makes the late-response guard a clean "patch one field" change.
- **Keep separate**: WU-A, WU-B, WU-D, WU-E, WU-I are independent surgical/refactor changes — distinct commits.
- **Do WU-I (lifecycle executor) late**, after the surgical fixes are green — it is the highest-churn backend refactor and easiest to regress.

---

### WU-A — State lock fails closed
**Files:** `py_modules/sdh_ludusavi/persistence.py`, `tests/test_persistence.py`
**Verified state:** `_acquire_file_lock` (persistence.py:54-77) returns `None` on `os.open` failure and on timeout; `__enter__` (36-41) stores it and proceeds; `load_all`/`save_settings`/`save_cache`/`locked()` then read/write without exclusion. Atomic temp+`os.replace` already present in `_atomic_json_write` (107-118).

**Change:**
- Add a module-level `class StateLockTimeoutError(RuntimeError)` (or `OSError` subclass — pick `RuntimeError`).
- In `_acquire_file_lock`, on the timeout branch (68-76) raise `StateLockTimeoutError(...)` after `os.close(fd)` instead of returning `None`. On the `os.open` `OSError` branch (58-60) also raise `StateLockTimeoutError` (cannot operate safely without the lock). Return type becomes `int` (no longer `int | None`).
- In `__enter__`, the file-lock acquisition runs only at `_depth == 1`. If it raises, `__exit__` will NOT be called (because `__enter__` raised), so wrap the `_acquire_file_lock()` call: on exception, roll back (`self._depth -= 1`, `self._thread_lock.release()`) and re-raise. Keep `_fd` typed `int | None` for the not-held case.
- Callers (`load_all`, `save_settings`, `save_cache`, and compound users of `locked()`) now propagate the error. Do not catch it in persistence; let it reach the RPC boundary (`main.py _call`, WU-F) where it becomes `{"status": "failed"}`.
- **Audit non-RPC callers** so a raised timeout does not crash plugin load: grep for `persistence`/`load_all`/`save_cache`/`.locked()` usages (notably startup reconcile in `service.py` and the update-install race path in `test_update_install_race.py`). At genuine best-effort startup sites, wrap the call and degrade gracefully (log + continue) rather than letting the exception abort load. Preserve current behavior of `test_update_install_race.py`.

**Tests (write first):**
- Contention: from the test, independently `flock` the lock-file path exclusively, then assert `save_cache(...)` raises `StateLockTimeoutError` **and the target cache file is unchanged** (write a sentinel first, assert bytes identical). Lower `LOCK_ACQUIRE_TIMEOUT_SECONDS` via monkeypatch to keep the test fast.
- The timeout surfaces as a failed RPC: drive it through the service/`_call` path (or assert the exception type that `_call` converts).
- Reentrancy (`with mgr.locked(): mgr.save_cache(...)`) and normal multi-thread serialization still pass.

**Risk:** depth/thread-lock bookkeeping on the `__enter__` exception path — get the rollback exactly right or you leak the `RLock`. Startup callers that previously tolerated `None` must not now crash plugin load.

---

### WU-B — Bind process signaling to the launched game (+ remove dead watchdog param)
**Files:** `main.py`, `py_modules/sdh_ludusavi/watchdog.py`, `py_modules/sdh_ludusavi/service.py` (construction site only), `tests/test_watchdog.py`
**Verified state:** `ProcessWatchdog.pause`/`resume` (watchdog.py:41-92) coerce any `pid>1` (`_coerce_signal_pid`, ~178-198) and signal the tree with no identity proof. `_paused_pids: dict[int, float]` stores only a timestamp. `__init__` accepts and stores `service: Any` (watchdog.py:28,32) but never reads it.

**Change:**
- Capture process identity on pause. Build a small frozen dataclass `_ProcessIdentity(start_ticks: int, uid: int)` where `start_ticks` is field 22 of `/proc/<pid>/stat` and `uid` is `os.stat(f"/proc/{pid}").st_uid`. Add a reader helper, e.g. `_read_process_identity(pid) -> _ProcessIdentity | None` (handle the parenthesized comm field in `/proc/<pid>/stat` by splitting on the last `)`).
- On pause: read identity; refuse (`{"status": "failed", ...}`) if it cannot be read or if `uid != os.geteuid()` (never signal processes we don't own). Store `_paused_pids[pid] = (_ProcessIdentity, time.time())`. Only signal descendants whose root identity is still valid (re-validate the root before sending the tree signal).
- On resume: re-read the current identity for `pid`; if it is missing or `start_ticks`/`uid` differ from the stored identity (PID reuse), refuse to signal, drop the stale entry, and return failed. Only `SIGCONT` when the stored identity matches.
- Keep public return shapes (`{"status": "paused"|"resumed"|"failed", "pid": ...}`) unchanged.
- Remove the unused `service: Any` parameter and `self._service` attribute. Update the single construction site in `service.py` (grep `ProcessWatchdog(`).

**Tests (write first):**
- Arbitrary same-user process is rejected: resume a PID that was never paused (identity mismatch / not tracked) → no `SIGCONT`, returns failed.
- PID reuse: stub the identity reader so the stored `start_ticks` differs from the value at resume → assert `os.kill`/tree-signal is never called and the entry is dropped.
- Descendants signaled only while the root identity is valid: stub `_process_tree` and identity so an invalid root short-circuits.
- Stub `/proc` reads and signal sending (monkeypatch the identity reader and `_send_signal_tree`/`os.kill`); do not signal real processes.

**Risk:** `/proc/<pid>/stat` parsing (comm in parens). Tests must mock all `/proc` and signal calls. The `service.py` constructor edit is internal and justified by the misattributed code-quality finding — keep it to that one line.

---

### WU-C — Reject ambiguous fuzzy matches (backend + frontend)
**Files:** `py_modules/sdh_ludusavi/matcher.py`, `src/state/ludusaviState.tsx`, `tests/test_matcher.py` (and/or `tests/test_matching.py`), plus the frontend test for `isTracked`.
**Verified state:** matcher.py fuzzy branch (~83-90) iterates `games.values()` and `return`s the first substring candidate that passes `fuzzy_match_allowed`. AppID (step 1), alias (step 2), exact-normalized (step 3) precede it. Frontend `LudusaviStateStore.isTracked` (ludusaviState.tsx ~221-249) has a parallel substring branch.

**Change (backend):** In the fuzzy branch, collect **all** candidates that pass `fuzzy_match_allowed` instead of returning the first. Accept only if exactly one unique game qualifies; if two or more distinct games qualify, return `None` (force AppID/alias/exact resolution). Preserve steps 1-3 unchanged.

**Change (frontend):** Mirror the rule in `isTracked`'s substring branch — classify as tracked only when the substring resolution is unique, so the launch gate is not activated for a game the backend will reject.

**Tests (write first):**
- Backend: registry with two substring candidates (e.g. `Portal 2`, `Portal Stories: Mel`) for input `Portal`, built in **both** insertion orders → identical result (`None`).
- Backend: ambiguous candidates → `None`. AppID, alias, and exact-normalized matching still resolve as before.
- Frontend: vitest proving `isTracked` returns false for an ambiguous substring and true for a unique one.
- Inspect existing matcher tests; if any assert a specific pick for an ambiguous input, update them to the new safe behavior (they encoded the bug).

**Risk:** some inputs that previously fuzzy-matched will now require exact/AppID — that is the intended safer behavior. Verify no production alias/exact path regresses.

---

### WU-D — Bound backup-browser filesystem inspection
**Files:** `py_modules/sdh_ludusavi/ludusavi.py`, `tests/test_backup_browser.py`
**Verified state:** `PyludusaviAdapter.list_backups` (~300-345) calls `_backup_disk_stats` (~494-557) synchronously for every snapshot, inside the global op lock (`lifecycle.list_backups` → `run_locked`). `_backup_disk_stats` `os.walk`s every file (502-515) or loads the full ZIP central directory (537-541). Size/count fields are already nullable.

**Change:** Apply a strict, deterministic budget to optional statistics:
- Prefer existing API metadata on the `b` backup dict where present before touching the filesystem.
- Cap inspection with module-level constants: a per-snapshot entry budget (e.g. `BACKUP_STAT_MAX_ENTRIES`), a snapshot-count budget (e.g. stat only the first N snapshots), and/or a wall-clock budget across the whole list. When the budget is exceeded for a snapshot, return its size/count as `None` (unknown) and move on — never block.
- Keep the return schema and restore identifiers identical; only the optional size/count become `None` more often.

**Tests (write first):**
- Large directory entry count and large ZIP entry count → assert inspection stops at the budget (inject the budget constants low, or a counter, so the test is deterministic) and the call returns promptly.
- The backup list still returns **all** snapshot identities when statistics are unavailable/`None`.
- Schema and restore identifiers unchanged (assert key set).

**Risk:** make the budget injectable/monkeypatchable so tests are deterministic; keep all changes within the two functions and the new constants.

---

### WU-E — Keep blocking Syncthing work outside the manager lock
**Files:** `py_modules/sdh_ludusavi/syncthing/watcher.py`, `tests/test_watcher.py`
**Verified state:** `start_watch` (~301-403) holds `self.lock` across `resolve_api_credentials`, `SyncthingAPI(...)`, `get_my_device_id`, folder resolution, and `get_connection_snapshot`. `stop_watch` (~424-431) and `stop_all` (~432-436) hold the lock during `watch.stop()` → `thread.join`.

**Change:** Restructure `start_watch` into three phases:
1. **No lock:** credential discovery, folder resolution, peer probes → build a fully prepared watch object (do not register it). All current skip/early-return paths stay here and return without touching the lock.
2. **Short lock:** check for an existing same-signature watch; register the prepared watch; capture any watch object being replaced into a local. Handle concurrent same-signature starts deterministically (e.g., if an identical signature is already registered, keep the existing one and mark the prepared one for disposal).
3. **No lock:** stop/join the replaced (or discarded) watch.

For `stop_watch`/`stop_all`: under the lock, pop/remove the target watch(es) into local references and clear the dict; release the lock; then `stop()`/`join()` outside it.

Keep all public return shapes unchanged. Same-signature replacement must still leave exactly one registered watch.

**Tests (write first):**
- Concurrency: block credential resolution in one `start_watch` (via an injected `threading.Event`) and assert that polling and `stop_watch` of a pre-existing watch complete without waiting on it.
- `stop_all` does not hold the manager lock while joining (assert the lock is acquirable from another thread during the join, or that join runs after release).
- Same-signature replacement leaves exactly one registered watch.

**Risk:** the most intricate concurrency change — use barriers/events, not sleeps. Preserve every existing skip path verbatim. If you cannot cleanly probe outside the lock without duplicating logic, prefer a private prepare-helper over leaking the API; do not change the public method signatures.

---

### WU-F — Abort install on persistence failure (+ `_call` hardening)
**Files (backend commit):** `main.py`; **(frontend commit):** `src/controllers/pluginUpdateController.tsx`, `src/api/ludusaviRpc.ts`, `src/types/index.ts`; **Tests:** `tests/test_main.py`/`tests/test_main_rpc.py`/`tests/test_exception_boundaries.py`, plus a new `src/controllers/pluginUpdateController.test.ts(x)`.
**Verified state:** `Plugin._call` (main.py ~420-445) catches `OperationLockedError`, `Exception`→`{status:'failed'}`, re-raises `CancelledError`, then `except BaseException`→`{status:'failed'}` (swallows `SystemExit`/`KeyboardInterrupt`). `recordUpdateInstallRequestedCall` (ludusaviRpc.ts ~85-90) is typed to return `UpdateCheckContext` (unconditional success). `install()` (pluginUpdateController.tsx ~410-437) does `await recordUpdateInstallRequestedCall(payload)` and proceeds to `enterPostInstallGuard` + `invokeDeckyInstaller` regardless. No dedicated controller test file exists.

**Change — backend commit (`main.py`):**
- Re-raise `SystemExit` and `KeyboardInterrupt`: add `except (SystemExit, KeyboardInterrupt): raise` before the final `except BaseException`. Keep `CancelledError` re-raise. Other `BaseException` may still convert to failed (or also re-raise — minimal change is the explicit re-raise of the two named ones).
- Confirm the backend `record_update_install_requested` handler returns a `{"status": "failed", ...}` dict on persistence failure (it already does via `_call`'s exception conversion; with WU-A, a lock timeout now surfaces here too). No structural change to the handler beyond ensuring the failure is representable in its return.

**Change — frontend commit:**
- In `ludusaviRpc.ts` and `src/types/index.ts`, type `recordUpdateInstallRequestedCall`'s return as a union that acknowledges resolved failure (e.g. `UpdateCheckContext | RpcStatus`, reusing the existing `RpcStatus`/`RpcResult` type — find the existing failed-status type, do not invent a new one if one exists).
- In `install()`, capture the result, inspect its status; on `failed`/`skipped`: log it, exit the installing state, surface the backend message to the UI, and **return without** calling `enterPostInstallGuard` or `invokeDeckyInstaller`. Apply the same result validation to handoff confirmation and pending-state cleanup where the result affects controller state. Leave the success path behavior identical.
- **Scope guard:** do NOT do the full state-machine reducer refactor (holistic #2) — only this correctness fix.

**Tests (write first):**
- Controller: a failed `recordUpdateInstallRequestedCall` response prevents any `invokeDeckyInstaller` invocation; the UI exits the installing state and shows the persistence error; the success path still records, hands off, and confirms unchanged. (Stand up a vitest harness for the hook with mocked RPC — check how existing controllers/`settingsMutationRuntime.test.ts` mock RPC and follow that pattern.)
- Backend: `_call` re-raises `SystemExit` and `KeyboardInterrupt` (and still converts ordinary `Exception` to failed).

**Risk:** creating the first controller test harness — mirror existing frontend test setup. Keep edits within the cited files.

---

### WU-G — Make `settings` the single source of truth (do before WU-H)
**Files:** `src/state/ludusaviState.tsx`, callers in `src/components/qam/LudusaviContent.tsx` and `src/controllers/gameLifecycleController.tsx`, plus the state store test.
**Verified state:** `LudusaviStateSnapshot` (62-75) stores `selectedGame`, `autoSyncNotificationsEnabled`, `notificationSettings` **separately** from `settings`. `applySettings` (127-136) writes both copies; `setSelectedGame`/`syncSelectedGameCache` (138-147) and the notification/auto-sync setters (149-178) maintain the duplicates; `syncSelectedGameCache()` exists solely to repair divergence.

**Change:** Store each value once in `settings`. Eliminate the independently-mutable duplicate fields and remove `syncSelectedGameCache()`. Preserve the existing snapshot-facing names by deriving them from `settings` in the single commit path (one typed `patchSettings(partial: Partial<Settings>)` store method that all optimistic updates go through). Update setters to patch `settings`; update callers that paired `setSelectedGame()` + `syncSelectedGameCache()` to a single call; update the QAM cache-sync references.

**Decide carefully:** if the snapshot is consumed via own-properties (it is committed as a plain object through the store's `commit`), do not switch to getters that break consumers — instead keep the fields but make them **only ever written by `applySettings`/`patchSettings` as a derivation of `settings`**, removing every independent writer and the repair method. That satisfies "eliminate independently mutable duplicate values" without changing the consumer contract.

**Tests (write first):** invariant tests proving `selectedGame`, notification policy, and auto-sync status cannot diverge from `settings` after any mutation; assert callers no longer need a paired sync call.

**Risk:** the snapshot is consumed widely — verify how `useSyncExternalStore`/selectors read it before changing field shape. Prefer the single-writer-derivation approach over getters if there is any doubt.

---

### WU-H — Guard late settings responses (+ type `MutateOptions`)
**Files:** `src/settings/settingsMutationRuntime.ts`, `src/settings/settingsMutationRuntime.test.ts`
**Verified state:** `withTimeout` (~82-92) races but does not cancel the RPC. `mutateSetting` late-resolution handler (~206-213) applies on `updateSeq === readSeq()`. `applySettings(store, res)` (called e.g. ~267) commits the **entire** normalized `Settings` object. Per-setting counters (`autoSyncSeq`, `notificationSeq`, `selectedGameSeq`, ...) are isolated, so a stale full-snapshot apply overwrites newer unrelated fields. `MutateOptions<T,V>` (~155-174) has `settingValue`/`settingPreviousValue`/`logFallbackValue` as `any` and `getPersistedValue: (res:T)=>any`.

**Change:**
- Add a runtime-wide monotonic mutation generation counter, incremented at the start of every `mutateSetting`. Capture the generation at start.
- On (late) resolution, **do not apply a whole stale snapshot**: either (preferred) merge only the field owned by the completed mutation into the store via WU-G's `patchSettings`, or reject any full snapshot whose captured generation predates a newer started mutation. Keep the per-setting sequence for own-field ordering. Preserve optimistic rollback for genuine RPC failures.
- Replace the `any` fields: `settingValue?: V`, `settingPreviousValue?: V`, `logFallbackValue?: V`, `getPersistedValue: (res: T) => V`.

**Tests (write first):**
- One setting times out, a different setting succeeds, then the first resolves late → the second is **not** reverted.
- Equivalent coverage for selected-game and notification mutations, and at least one non-boolean setting.
- Optimistic rollback still fires for a genuine RPC failure.
- Update existing tests that asserted whole-snapshot application.

**Risk:** depends on WU-G's `patchSettings` — do WU-G first. Keep all edits within this file/test.

---

### WU-I — Centralize lifecycle backup/restore bookkeeping (do late)
**Files:** `py_modules/sdh_ludusavi/lifecycle.py`, `tests/test_lifecycle.py`, `tests/test_history_integration.py`, `tests/test_backup_browser.py`
**Verified state:** `resolve_game_start_conflict` (191-244), `restore_game_on_start` (246-280), `backup_game_on_exit` (350-384), `force_backup` (393-441), `force_restore` (443-492), `restore_backup_version` (505-568) repeat: `run_locked(op, game.name, adapter_call)` → compute `change` via `_result_change` → record success/failure/`Same`-skip history → `registry.refresh_after_operation` → log → shape result dict. They differ subtly and must be preserved exactly:
- `backup_game_on_exit`: refreshes, records `backed_up`, no `Same` handling.
- `force_backup`/`force_restore`/`restore_backup_version`: `Same`→`skipped` (`local_current`), then refresh, success otherwise.
- `restore_game_on_start`: records `restored` **after** logging, no `Same` handling, no refresh.
- `resolve_game_start_conflict`: records **before** logging, no refresh, returns `backed_up`/`restored`.
- `restore_backup_version`: includes `backup_id` in result and re-raises `OperationLockedError`.

**Change:** Introduce one private executor (e.g. `_execute_operation(*, operation, trigger, game, adapter_call, same_handling: bool, refresh: bool, record_order, result_extra)`) that runs the locked adapter call, records history (success/failure, and `Same`→skipped when `same_handling`), optionally refreshes, logs, and shapes the result. Public methods keep all eligibility/recency/validation decisions (game match, `has_backup`, `auto_sync`, `backup_id` validation, conflict resolution branching) and call the executor. Reproduce each method's current behavior **exactly** via parameters — this is a no-behavior-change refactor.

**Tests (write first):** table-driven tests asserting consistent history, refresh, and failure behavior across every trigger; assert operation-specific payloads (e.g. `backup_id`, `result`, `reason`) are unchanged. The existing `test_lifecycle.py`, `test_history_integration.py`, and `test_backup_browser.py` must pass untouched (except additions).

**Risk:** highest-churn backend refactor; the per-method differences (refresh present/absent, record order, `Same` handling, `OperationLockedError` re-raise) are load-bearing. Map each before touching code; run the full suite after.

---

### WU-J — One quality-gate definition + pin `setup-uv`
**Files:** `scripts/pre_commit.sh`, `scripts/post_commit.sh`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/workflows/dev-release.yml`, `.github/actions/setup-toolchain/action.yml`, `tests/test_release_workflows.py` (and check `tests/test_orchestration_scripts.py`).
**Verified state:** CI/release/dev-release run the same sequence (`ruff check`, `ruff format --check`, `ty check`, `pytest`, `pnpm run verify`) via `./run.sh`. `pre_commit.sh` runs the fix-mode sequence but calls `pnpm run verify` **directly** (not via `./run.sh`); `post_commit.sh` also calls `pnpm run verify` directly. `setup-toolchain/action.yml` line ~37 sets `setup-uv` `version: "latest"`.

**Change:**
- Add one authoritative gate script (e.g. `scripts/quality_gates.sh`) with a check mode (`ruff check .`, `ruff format --check .`, `ty check py_modules/sdh_ludusavi/`, `pytest`, `./run.sh pnpm run verify`) and a fix mode (`ruff check . --fix`, `ruff format .`, then the rest) — route all tooling through `./run.sh`.
- Call the check-mode script from `ci.yml`, `release.yml`, `dev-release.yml`. Call the fix-mode script from `pre_commit.sh` (keep its `scripts/check_tdd.sh` invocation). Fix `post_commit.sh` to route `pnpm run verify` through `./run.sh`. Confirm `scripts/orchestration/run-quality-gates` still works (it defers to the project hook — leave its contract intact).
- Pin `setup-uv` to a specific reviewed version instead of `latest` (set `version:` to a concrete uv version that matches the pinned `astral-sh/setup-uv@v8.1.0`).

**Tests (write first):**
- A static assertion in `tests/test_release_workflows.py` that CI/stable/dev workflows reference the shared gate script and contain no duplicated inline gate sequence, and that `setup-uv` `version` is not `latest`. Update existing assertions that pinned the now-relocated inline sequence.

**Risk:** do not change CI semantics or the `./run.sh` env contract; keep `check_tdd.sh` in pre-commit; touch only the cited files. Do **not** convert action tags to full SHAs (out of scope).

---

## Quality Gates (run before every `mark-finished`)

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
```

All must pass. Caches/venv stay under `/tmp/sdh_ludusavi/` (the `./run.sh` wrapper enforces this). After WU-J exists, you may instead run `scripts/quality_gates.sh` (check mode) as the single gate.

## Verification (end-to-end, before approval)

- Full backend suite green, including the new tests for WU-A/B/C/D/E/F/I and the architecture/budget guard tests (`test_architecture.py`, `test_module_size_budgets.py`, `test_status_flow_diagram.py`) still passing.
- Full frontend suite green (`pnpm run verify`), including the new WU-C `isTracked`, WU-F controller, and WU-G/WU-H settings tests.
- `test_release_workflows.py` green with the new WU-J assertions.
- Confirm no caches were written inside the repo (`git status --short` clean of `__pycache__`, `.ruff_cache`, etc.).
- On-device Steam Deck testing is **deferred** until after `dev` is pushed (per the finalize step).

## Constraints
- One coherent commit per work unit (Conventional Commits); the two split units (WU-C, WU-F) may use a backend commit + frontend commit.
- Preserve public APIs and return types of the cited functions (internal helpers/params may change, e.g. the `watchdog.py` dead-param removal and its one construction site).
- No new third-party dependencies.
- Do not act on the "no merit / already fixed" findings, and do not implement the excluded large refactors.
- Do not create, delete, or edit files under `docs/review/` except to commit review notes the orchestrator writes there.
