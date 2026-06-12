# Review — Backup Browser with Point-in-Time Restore — Round 1

Reviewed: branch `feat/backup-browser` (HEAD `90b7da6`) against
`docs/plans/2026-06-12_backup_browser_point_in_time_restore.md`.

Verified passing before review: `./run.sh uv run ruff check .`, `./run.sh uv run ty check py_modules/sdh_ludusavi/`, `./run.sh uv run pytest` (555 passed), `pnpm run test` (156 passed + typecheck), `pnpm run build`. Process compliance is good: plan committed first, RED test commit before implementation, atomic Conventional Commits, clean tree.

Address EVERY finding below. After fixing, re-run all quality gates, commit on `feat/backup-browser`, then create the empty marker file:
`/tmp/sdh_ludusavi/2026-06-12_backup_browser_point_in_time_restore_review_round_1_finished`

---

## Finding 1 (HIGH) — `file_count` is computed but never displayed

Feature requirement (plan C4): each snapshot row shows **date, file count, total size**. The backend computes `file_count` and the `BackupSnapshot` type carries it, but `src/components/modals/BackupBrowserModal.tsx` never renders it.

**Fix:** In the snapshot row (the `div` showing `formatBytes(b.size_bytes)`), also render the file count, e.g. `"{b.file_count} files"` when `b.file_count !== null`, and omit it (or show `"—"`) when `null`.

## Finding 2 (HIGH) — restore test does not assert `backup_id`/`force` reach the client

`tests/test_backup_browser.py::test_adapter_restore_backup_calls_client` only asserts `client.requested_games`. `FakeLudusaviClient.restore` (tests/test_ludusavi.py:175) swallows `backup_id` into `**kwargs`. Consequence: a regression that drops `backup_id` would still pass the suite — and ludusavi would silently restore the **latest** backup instead of the selected snapshot, which is destructive. Plan B7.3 explicitly required asserting `games=[game]`, `backup_id=<id>`, `force=True`.

**Fix:**
1. In `FakeLudusaviClient` (tests/test_ludusavi.py), record restore kwargs without breaking existing tests, e.g. add `self.last_restore_kwargs: dict[str, object] = {}` in `__init__` and in `restore(...)` set `self.last_restore_kwargs = {"games": games, "preview": preview, "force": force, "timeout": timeout, **kwargs}`.
2. In `test_adapter_restore_backup_calls_client`, assert `client.last_restore_kwargs["backup_id"] == "backup_123"` and `client.last_restore_kwargs["force"] is True`.

## Finding 3 (MEDIUM) — `list_backups` swallows `LudusaviError`, masking CLI failures as "no backups"

`PyludusaviAdapter.list_backups` (py_modules/sdh_ludusavi/ludusavi.py) catches `LudusaviError` and returns the empty-result shape. A real ludusavi failure (binary missing, config broken, timeout) is then indistinguishable from "this game has no backups" — the modal shows "No backups found.", which is wrong and could make a user think their backups are gone.

**Fix (TDD — write the failing test first):**
1. Remove the `try/except LudusaviError` around `self._client.backups_list(...)` and let the exception propagate. It will flow through `run_locked` → `Plugin._call` (main.py:408), which serializes it to `{"status": "failed", "message": ...}`; the frontend modal already handles that via `isRpcStatus` and shows the error state.
2. Add a test in `tests/test_backup_browser.py`: a fake client whose `backups_list` raises `LudusaviError` → assert `adapter.list_backups("Hades")` raises `LudusaviError` (i.e. `pytest.raises`).

## Finding 4 (MEDIUM) — no frontend test for the size formatter

Plan C3/C6 required a vitest test for the size formatter (written first). `src/formatting/bytes.ts` has none.

**Fix:** Add `src/formatting/bytes.test.ts` (follow any existing `*.test.ts` style, e.g. `src/utils/logging.test.ts`) covering at least: `0` → `"0 B"`, a bytes value < 1024, exact `1024` → `"1 KB"`, an MB-range value, and a GB-range value. While here: the modal renders an empty string for `size_bytes === null` and `"Unknown"` for null totals; that's acceptable, but keep the formatter's contract (`number` in, string out) covered by the tests.

## Finding 5 (MEDIUM) — snapshot restore bypasses the global busy/notify flow

Plan C5 required the snapshot restore to follow the `runForceOperation` flow (LudusaviContent.tsx:623). The current implementation runs the restore entirely inside the modal, so:
- `busyLabel` is never set: while a restore runs, the QAM behind the modal still shows idle status and Force Backup/Restore stay enabled (the backend lock rejects a second op, but the user gets a confusing "operation is already running" error instead of disabled buttons).
- There is no "Restore started" toast, and on a failed result the toast category is `"manual_operations"` instead of `"failures_errors"` (users who only enabled failure notifications won't hear about a failed restore).
- A failed restore renders only as red text inside the modal and the snapshot list disappears (render condition `!error`), with no toast.

**Fix (minimal, keep the modal-owned fetch):** Lift the restore execution into `LudusaviContent.tsx` as the plan described:
1. In `LudusaviContent.tsx`, add `runSnapshotRestore(backupId: string, whenLabel: string)` modeled on `runForceOperation` ("Restore" label): `setBusyLabel("Restore running")`, start notify (`manual_operations`), `await restoreBackupVersionCall(selectedGame, backupId)`, result notify via `summarizeOperationResult` with category `failures_errors` when `result.status === "failed"` or on throw, then the same post-op refresh (`refreshGamesCall(false)`, `getOperationStatus()`, `getRecentLogs()`, `applyRefreshResult`), `setBusyLabel(null)` in `finally`. Reuse/extract shared logic from `runForceOperation` if the refactor stays small; copy-adapt otherwise.
2. Change `BackupBrowserModal` props: replace `onRestoreComplete` with `onRestoreSnapshot: (backupId: string, whenLabel: string) => void`. The confirm dialog's `onOK` should `closeModal?.()` then call `onRestoreSnapshot(...)` — the modal no longer calls `restoreBackupVersionCall` itself (remove that import).
3. `tsc` must stay clean (`pnpm run test`).

## Finding 6 (LOW) — confirmation dialog shows the raw backup id, not the snapshot date

Plan C4: "Restore {gameName} to the backup from {date time}? Current save data will be overwritten." Current text interpolates `backupId` (e.g. `backup-20260601T120000Z`), which is machine noise to a user.

**Fix:** Pass the formatted timestamp (`formatTimestamp(b.when)`) into the confirm description and use it instead of (or alongside) the id. Combine with Finding 5's `whenLabel` parameter.

## Finding 7 (LOW) — modal header lacks snapshot count

Plan C4 header: game name, **snapshot count**, total size. **Fix:** add the count (e.g. `"{listResult.backups.length} snapshots"`) next to Total Size.

## Finding 8 (LOW) — README not updated

Plan Part D / Definition of Done: README must be updated when user-facing behavior changes. **Fix:** add the Backup Browser (browse snapshots + point-in-time restore from the QAM) to README's feature/usage section. `docs(readme): ...` commit.

## Finding 9 (LOW) — missing lock-contention test for `restore_backup_version`

Plan B7.4 required a test that lock contention propagates `OperationLockedError` without recording a `"restored"` history entry. **Fix:** in `tests/test_backup_browser.py`, set `deps.run_locked.side_effect = OperationLockedError("busy")`, assert `pytest.raises(OperationLockedError)`, and assert `deps.history.record_history` was not called with a `"restored"` status (the failure branch must not swallow it — note `lifecycle.py` already re-raises `OperationLockedError` before the broad handler; this test pins that behavior).

---

## Reminders (not findings)

- Session log (`docs/agent_conversations/2026-06-12_backup_browser_point_in_time_restore.json`) is still required before finalization (plan Part A.7).
- Do not merge/push/release yet — that happens only after a review note with `STATUS: APPROVED`.

STATUS: CHANGES_REQUESTED
