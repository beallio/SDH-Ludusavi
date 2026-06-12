# Review — Backup Browser with Point-in-Time Restore — Round 2

Reviewed: branch `feat/backup-browser` (HEAD `fb10e13`) against
`docs/plans/2026-06-12_backup_browser_point_in_time_restore.md` and the round 1 findings.

## Round 1 findings — all resolved

1. **file_count displayed** — snapshot rows now render `"{n} files"` alongside size. ✓
2. **backup_id/force assertions** — `FakeLudusaviClient` records `last_restore_kwargs`; test asserts `backup_id == "backup_123"` and `force is True`. ✓
3. **LudusaviError propagation** — `try/except` removed from `PyludusaviAdapter.list_backups`; `test_adapter_list_backups_propagates_ludusavi_error` pins it. ✓
4. **Formatter tests** — `src/formatting/bytes.test.ts` covers 0/B/KB/MB/GB. ✓
5. **Global busy/notify flow** — restore lifted into `runSnapshotRestore` in `LudusaviContent.tsx`: sets `busyLabel`, start toast, `failures_errors` category on failure/throw, full post-op refresh; modal only selects the snapshot. ✓
6. **Confirm dialog wording** — now "restore {game} to the backup from {date}". ✓
7. **Header snapshot count** — added. ✓
8. **README** — Backup Browser feature documented. ✓
9. **Lock-contention test** — `test_lifecycle_restore_backup_version_locked` added; `OperationLockedError` re-raises without history pollution. ✓

Session log `docs/agent_conversations/2026-06-12_backup_browser_point_in_time_restore.json` is present.

## Verification (run by reviewer at `fb10e13`)

- `./run.sh uv run ruff check .` — passed
- `./run.sh uv run ty check py_modules/sdh_ludusavi/` — passed
- `./run.sh uv run pytest` — 557 passed
- `pnpm run test` — 161 passed + tsc clean
- `pnpm run build` — bundle created

No new findings.

## Next steps — proceed with Finalization (plan Part A.6)

1. Commit any uncommitted review notes (this file) — `docs(review): record backup browser review notes`.
2. `git checkout dev && git merge --no-ff feat/backup-browser && git branch -d feat/backup-browser`
3. `git push origin dev`
4. `./scripts/request_dev_release.sh 0.3.0`
5. Create the final marker:
   `/tmp/sdh_ludusavi/2026-06-12_backup_browser_point_in_time_restore_release_finished`

STATUS: APPROVED
