# Review: `fix/operation-timeouts-watchdog-ceiling` (commit `0feaa1d`) vs. Implementation Plan

**Date:** 2026-06-10
**Reviewed commit:** `0feaa1d` — `feat(adapter): bound operations and add watchdog ceiling`
**Plan reviewed against:** `docs/plans/2026-06-09_fix_operation_timeouts_watchdog_ceiling.md` (Review Finding B3)
**Branch context:** the branch carries three commits past `main`. The other two (`ba24b94`, `eebc320`) are the B2 event-loop work, already reviewed in `docs/review/2026-06-10_review_ba24b94_event_loop_blocking_rpcs.md` and `docs/review/2026-06-10_review_571e64f_event_loop_rpc_test_hardening.md`. This review covers only `0feaa1d`, the sole commit implementing the B3 plan.

**Verdict:** ✅ **The implementation meets the plan. No findings. No follow-up implementation work is required.**

All six acceptance criteria in plan §5 were independently re-verified by this review and hold. The production code in `constants.py`, `ludusavi.py`, and `watchdog.py` matches the plan's specified code essentially verbatim. All quality gates were re-run and pass.

---

## 1. Verification evidence (everything below was re-executed during this review, not taken on faith)

### 1.1 Quality gates (plan Step 8 / repo Definition of Done)

| Gate | Command | Result |
|---|---|---|
| Lint | `./run.sh uv run ruff check .` | All checks passed |
| Format | `./run.sh uv run ruff format --check .` | 106 files already formatted (no diff) |
| Types | `./run.sh uv run ty check py_modules/sdh_ludusavi/` | All checks passed |
| Backend tests | `./run.sh uv run pytest` | **495 passed** in 13.11s |
| Frontend | `pnpm run verify` | vitest 79 passed (8 files) + `tsc --noEmit` clean |
| No unbounded calls | `grep -rn "timeout=None" py_modules/sdh_ludusavi/` | no matches (exit 1) — OK |
| Constant usage | `grep -c "LUDUSAVI_PREVIEW_TIMEOUT_SECONDS" py_modules/sdh_ludusavi/ludusavi.py` | 7 (import block + 2 ternaries + 3 preview sites, ≥ the plan's expected ≥4) |

### 1.2 Acceptance criteria (plan §5), one by one

1. **Full pytest green, no deleted tests, only permitted test edits** — ✅. 495 passed. The commit's test diff contains only: the Step 2a fake-client signature additions (`FakeLudusaviClient.backup/restore` gained `force`/`timeout` params and a `calls` recording list), `**kwargs` tolerance on the inline `MockClient` in `test_refresh_statuses_forwards_game_names_to_client` (whose assertion was extended, not weakened — it now also asserts the preview timeout), and 9 new tests. `tests/test_exception_boundaries.py` defines no `backup`/`restore`/`backups_list` fakes (verified by grep), so no change was needed there — consistent with the plan's "verify by running it" instruction.
2. **ruff check, ruff format, ty, pnpm verify** — ✅ (table above).
3. **Only §2 files touched** — ✅. `git show 0feaa1d --stat` lists exactly: `README.md`, `docs/agent_conversations/2026-06-11_fix_operation_timeouts_watchdog_ceiling.json`, `docs/plans/2026-06-09_fix_operation_timeouts_watchdog_ceiling.md`, `py_modules/sdh_ludusavi/{constants,ludusavi,watchdog}.py`, `tests/test_{ludusavi,service,watchdog}.py`. Nothing under `py_modules/pyludusavi/`, `src/`, and no edits to `coordinator.py`, `lifecycle.py`, or `main.py` in this commit.
4. **Every non-`backups_list` client invocation carries an explicit `timeout=`** — ✅ per the plan's own operational definition (Step 3g: exactly five new `timeout=` keywords; see §2.1 below for the literal-reading caveat, which is a non-finding). All five sites verified present: `backup()` and `restore()` ternaries (operation vs. preview budget), both `refresh_statuses` preview submits, `compare_recency`'s restore preview, `get_conflict_metadata`'s backup preview.
5. **Watchdog deferral within ceiling preserved; unconditional resume past ceiling proven by test** — ✅. `test_watchdog_defers_resume_while_operation_running_within_ceiling` (60s paused, op running → not resumed) and `test_watchdog_resumes_past_absolute_ceiling_even_when_operation_running` (ceiling+1s, op running → resumed via SIGCONT, warning containing "absolute ceiling" asserted).
6. **`WATCHDOG_ABSOLUTE_RESUME_SECONDS` derived from `LUDUSAVI_OPERATION_TIMEOUT_SECONDS`** — ✅. `constants.py:44`: `WATCHDOG_ABSOLUTE_RESUME_SECONDS = LUDUSAVI_OPERATION_TIMEOUT_SECONDS + 60.0`.

### 1.3 Step-by-step plan conformance

- **Step 1 (constants):** all four constants added with the plan's exact values (900.0 / 300.0 / 15.0 / derived ceiling) and rationale comments.
- **Step 2 (adapter tests):** all six specified tests exist with the exact names and assertions the plan prescribed. The plan's suggested `_make_adapter_with_client` helper was unnecessary — the file's existing `adapter_with_backups` helper (tests/test_ludusavi.py:189) already returns `(adapter, client)`. Using it instead is exactly the "mirror the file's existing construction" behavior the plan asked for; an acceptable, arguably better-than-plan deviation.
- **Step 3 (adapter):** matches the plan's code verbatim, including the required one-line comment at both untouched `backups_list` submits ("backups_list has no timeout param; executor 30s default applies") and leaving `compare_recency`'s `backups_list` call outside its try block (plan invariant).
- **Step 4 (service-level lock-release test):** `test_force_backup_timeout_fails_and_releases_operation_lock` implements the plan's spec at the service layer with `pytest.raises(LudusaviError)`, asserts failure history with the timeout message, `is_running is False`, and a successful second call (`calls["n"] == 2`). The session log records the plan-anticipated note that this regression guard passed immediately once wired.
- **Steps 5–6 (watchdog):** `_check_and_resume_stuck_pids` replaced exactly as specified: scan under `_paused_pids_lock`, resumes outside the lock, `_watchdog_active = False` empty-map short-circuit preserved, `"absolute ceiling"` / `"idle timeout"` reasons in a warning-level `self._log`, broad-except around `resume()` preserved with its comment. New tests mirror the existing file's conventions precisely (patch `sdh_ludusavi.watchdog.os.kill` + `_process_tree`, literal signal numbers 19/18 as the pre-existing tests use, backdated `wd._paused_pids[pid]` under the lock).
- **Step 7 (docs):** README sentence added verbatim in "Understanding Status Messages" (README.md:86). Plan committed at its destination path. Session log `docs/agent_conversations/2026-06-11_fix_operation_timeouts_watchdog_ceiling.json` contains all required fields, including the four design decisions the plan mandated (budget values + rationale, no cancellation RPC, `backups_list` left on the 30s executor default, regression-guard note).

### 1.4 Edge-case table (plan §4)

Rows 1, 2, 6, 7, 10 are covered by the new tests listed above; rows 3–5, 8, 9 are documented invariants/implicit paths the plan explicitly said need no new tests. The full suite passing (including `tests/test_exception_boundaries.py`) confirms row 10 (no `TypeError` from the new `timeout` kwarg anywhere).

---

## 2. Observations considered and dismissed (non-findings — do NOT "fix" these)

These were examined during review and are recorded so a future agent does not mistake them for defects.

### 2.1 `config_show()`, `version()`, `config_path()`, `log_show()`, and direct `backups_list()` calls carry no explicit `timeout=`

Acceptance criterion #4 read literally says *every* non-`backups_list` invocation carries an explicit timeout. These five other client methods do not — and that is correct. The vendored executor `LudusaviExecutor.execute` defaults to `timeout: Optional[float] = 30.0` (`py_modules/pyludusavi/core.py:58`), so every one of these calls is already bounded at 30s, identical to the `backups_list` situation the plan documents in §1a and §6 ("leave it documented", "no vendored edits"). The plan's own Step 3g defines the expected end state as exactly five new `timeout=` keywords, which is what exists. Adding timeouts to these methods is impossible without vendored changes (they expose no `timeout` parameter), which the plan forbids.

### 2.2 Watchdog tests assert literal signal numbers (`mock_kill.assert_called_with(7777, 18)`)

`18` is SIGCONT and `19` is SIGSTOP on Linux x86. The pre-existing tests in the file use the same literals (e.g. `test_process_watchdog_pause_resume`, tests/test_watchdog.py:33,38), so the new tests correctly mirror the established convention; this is a Linux-only Decky plugin.

### 2.3 Session log dated/named `2026-06-11` while the commit is `2026-06-10 22:39 -0700`

The filename and `date` field reflect UTC. Cosmetic; not worth a commit to change.

### 2.4 Idle-resume warning text changed

The old text was "suspended for too long"; the new text is "suspended for {N}s (idle timeout exceeded)". The plan explicitly permits rewording as long as it stays a warning through `self._log` (it does), and no existing test asserted the old exact text (no test edits were needed for it; the suite is green).

---

## 3. Conclusion

`0feaa1d` is a faithful, complete implementation of the B3 plan. Nothing to fix; no follow-up agent task exists for this plan. The branch (B2 + B3 work) is, from this review's perspective, ready to merge once the previously-recorded B2 test-only findings (see the `ba24b94` review, which `eebc320` addressed) are considered resolved — `docs/review/2026-06-10_review_571e64f_event_loop_rpc_test_hardening.md` records that resolution.
