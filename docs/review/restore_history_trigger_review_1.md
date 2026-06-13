# Restore History Trigger — Review Round 1

**Branch:** `fix/restore-history-trigger` @ `aacc05e`
**Commits:** `7a72eec` (plan) · `89fc544` (RED test) · `aacc05e` (GREEN fix)
**Reviewer gates run (`./run.sh uv run --frozen ...`):**
`pytest` ✅ 604 passed, coverage 85.85% (≥83%) · `ty check` ✅ · `ruff check` ✅

## Verdict: PASS

The fix is exactly per plan, TDD order is correct, scope is clean, and all backend
gates pass. Per the plan, PASS is granted on code review + green gates only; on-device
testing is deferred to the published `v0.3.0-dev.*` build. Approved to finalize (§B6).

### Root-cause fix ✅
- `restore_backup_version` now records trigger `"manual_restore"` on BOTH paths
  (`lifecycle.py` ~468 failure, ~473 success) instead of the non-whitelisted
  `"point_in_time_restore"` that `_coerce_history_entry` was silently dropping.
- **`py_modules/sdh_ludusavi/history.py` is untouched** — correct (collapse approach;
  `manual_restore` was already valid).

### Tests ✅ (TDD, and the gap that let this ship is now closed)
- `tests/test_history_integration.py`: new
  `test_history_point_in_time_restore_records_restored` drives
  `service.restore_backup_version(...)` through the **real** service + `HistoryManager`
  and asserts `last_restore`/`last_operation.status == "restored"` and
  `trigger == "manual_restore"`. This is the regression guard the previous mock-based
  tests lacked — with the old trigger the real validator drops the entry, so this test
  fails on pre-fix code (verified by construction + TDD commit order: test committed in
  `89fc544` before the fix in `aacc05e`).
- `tests/test_service.py`: `FakeAdapter.restore_backup` stub added (mirrors `restore`).
- `tests/test_backup_browser.py`: both `record_history` assertions updated to
  `"manual_restore"`.

### Confirmations
- Scope: only `lifecycle.py` + 3 test files (+ plan doc) changed; frontend,
  `history.py`, `force_restore`, and the skip-path left alone as specified.
- Atomic conventional commits in TDD order; tree clean; all work committed before
  signaling.

No findings. Nothing to change.

## Endgame (plan §B6) — go (do NOT wait for Deck testing)
1. Ensure this note (and any prior) are committed on the branch.
2. Record session log at
   `docs/agent_conversations/2026-06-13_restore_history_trigger.json`.
3. Merge `fix/restore-history-trigger` into `dev` (`--no-ff`; `UV_FROZEN=1` prefix if
   the hook re-resolves and fails).
4. Delete the branch; `rm -f /tmp/sdh_ludusavi/restore_history_trigger_finished`.
5. `git push origin dev`.
6. `./scripts/request_dev_release.sh 0.3.0` (needs `gh` auth; surface failures).
7. Report the merge SHA + dev-release dispatch. On the `v0.3.0-dev.*` build, do a
   point-in-time restore and confirm Last Operation → "Restore complete".
