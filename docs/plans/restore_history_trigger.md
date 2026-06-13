# Fix: Point-in-Time Restore Not Recorded — Collapse to `manual_restore`

## Context

"Last Operation" still shows **"Backup complete"** after a point-in-time restore from
the Backup Browser (user-confirmed on `v0.3.0-dev.g514dede`, which already has last
round's frontend history-refresh fix). On-device logs
(`/tmp/sdh_ludusavi/steamdeck-logs/2026-06-13 12.29.48.log`) prove the restore
**succeeds** (`status="restored"` at 12:31) yet Last Operation stays at the 5:58 AM
backup.

### Root cause (confirmed by code read)

`py_modules/sdh_ludusavi/history.py` → `_coerce_history_entry` only accepts these
`trigger` values: `manual_backup`, `manual_restore`, `auto_start`, `auto_exit`. Any
other trigger makes the entry **silently dropped** (`return None` → `record_history`
returns early at `history.py:75-76`).

`restore_backup_version` (the Backup Browser path) records with trigger
**`"point_in_time_restore"`** (`lifecycle.py:468` failure, `lifecycle.py:473` success)
— NOT in the whitelist — so the restore is never persisted; `_update_last_operation`
keeps the prior backup. (`force_restore` uses `"manual_restore"`, so it records fine —
only the point-in-time path is broken.)

### Chosen fix (user decision: collapse to `manual_restore`)

The **Force Restore button was removed**; the Backup Browser's point-in-time restore
is now the *only* manual restore (the `force_restore` RPC + `forceRestoreCall` binding
remain but have no UI). `trigger` semantically means *what triggered the op*
(manual vs auto) — "point_in_time_restore" was a category error. So:

- Change `restore_backup_version`'s two `record_history` calls to use trigger
  **`"manual_restore"`** (already whitelisted). **No `history.py` change.**

This fixes the bug AND aligns the taxonomy. Trade-off accepted by the user: the
UI-less `force_restore` and the Backup Browser restore become indistinguishable in
history (fine — force restore has no UI).

### Why the bug shipped (and how we prevent recurrence)

The existing `restore_backup_version` unit tests (`tests/test_backup_browser.py`) use a
**mocked** `deps.history` and only assert `record_history` was *called* — they never
exercised the real `HistoryManager` validation that drops the entry. This round adds an
**integration test through the real service + HistoryManager** so the actual
"last_operation becomes restored" behavior is locked in.

This runs through the same **plan → implement → review** loop. **On-device / user
testing is deferred until the dev release is pushed to GitHub.**

---

## Canonical tokens (use these EXACT strings everywhere)

| Thing | Value |
|---|---|
| `plan_name` | `restore_history_trigger` |
| Working branch | `fix/restore-history-trigger` (branched from **`dev`**, NOT `main`) |
| This plan doc | `docs/plans/restore_history_trigger.md` |
| **Completion marker** (implementer → reviewer) | `/tmp/sdh_ludusavi/restore_history_trigger_finished` |
| **Review notes** (reviewer → implementer) | `docs/review/restore_history_trigger_review_<n>.md` (`<n>` = 1, 2, 3…) |
| Approval signal | a review note whose body contains the literal token `PASS` |
| Dev-release base version | `0.3.0` → `./scripts/request_dev_release.sh 0.3.0` |

> **Branch from `dev`, not `main`** (`main` lacks this code). Override the implementer
> skill's "branch from main" default.

## How to run this

This plan doc is delivered untracked in the working tree by the reviewer. Hand it to a
**fresh session** and tell it to **use the `implementer` skill**. That session is "the
implementer"; the reviewer does the code review. They communicate only through the
marker file and the review-note files above.

---

# PART A — Technical work (for the implementer)

**BACKEND change → strict TDD (CLAUDE.md §9): write/adjust failing tests first.**

Files in scope:
- `py_modules/sdh_ludusavi/lifecycle.py` (the 2 trigger strings)
- `tests/test_backup_browser.py` (update 2 mock-based assertions)
- `tests/test_history_integration.py` (NEW integration regression test)
- `tests/test_service.py` (add a `restore_backup` stub to `FakeAdapter` so the
  integration test can drive `restore_backup_version`)

Out of scope: `history.py` (unchanged — `manual_restore` is already valid), the
frontend (already refreshes history after manual ops), the skip-path operation arg
`"restore_backup_version"` (separate latent edge case; leave it), `force_restore`,
version bumps.

## A1. RED — tests first (run with `./run.sh uv run pytest`, confirm they FAIL)

### A1a. Update the two mock-based assertions in `tests/test_backup_browser.py`
- `test_lifecycle_restore_backup_version_success` (~line 226): change the expected
  call from
  `record_history.assert_called_with("Hades", "restore", "point_in_time_restore", "restored")`
  to `"manual_restore"`.
- `test_lifecycle_restore_backup_version_failure` (~line 247): change
  `"point_in_time_restore"` → `"manual_restore"` (keeps `message="failed"`).

These now FAIL against current `lifecycle.py` (which still passes
`"point_in_time_restore"`).

### A1b. Add a real-HistoryManager integration test (the gap-closer)
First, add a `restore_backup` stub to `FakeAdapter` in `tests/test_service.py`
(mirror the existing `FakeAdapter.restore` method's return shape; signature
`def restore_backup(self, game_name: str, backup_id: str) -> dict[str, object]:`).

Then add to `tests/test_history_integration.py`, mirroring
`test_history_manual_restore_success`:

```python
def test_history_point_in_time_restore_records_restored(tmp_path: Path) -> None:
    service = service_with_state(tmp_path)
    service.refresh_games()

    result = service.restore_backup_version("Hades", "backup-123")
    assert result["status"] == "restored"

    refresh = service.refresh_games()
    history = refresh["history"]["Hades"]
    assert history["last_restore"] is not None
    assert history["last_restore"]["trigger"] == "manual_restore"
    assert history["last_restore"]["status"] == "restored"
    assert history["last_operation"]["status"] == "restored"
    assert history["last_operation"]["operation"] == "restore"
```

Against current code this FAILS (lifecycle passes `"point_in_time_restore"` → the real
`HistoryManager` drops it → `last_restore` is `None`). This is the test that actually
reproduces the user's bug. (Note: `Hades` has `has_backup=True` in `FakeAdapter`, and
`"backup-123"` passes the `backup_id` validation in `restore_backup_version`.)

## A2. GREEN — change the trigger in `py_modules/sdh_ludusavi/lifecycle.py`

In `restore_backup_version`, change BOTH `record_history` triggers from
`"point_in_time_restore"` to `"manual_restore"`:
- line ~468 (failure path):
  `record_history(game.name, "restore", "manual_restore", "failed", message=str(exc))`
- line ~473 (success path):
  `record_history(game.name, "restore", "manual_restore", "restored")`

Do NOT touch `history.py`, the frontend, or `force_restore`.

Re-run `./run.sh uv run pytest` → A1a + A1b now pass.

## A3. Sanity check (for the implementer)

After A2: a point-in-time restore records trigger `"manual_restore"` (valid) → entry
stored under `last_restore` with a current timestamp → `_update_last_operation` picks
it (newest) → `get_game_history` returns it → the already-merged frontend post-op
refresh applies it → `getLastOperationText("restored")` renders **"Restore complete"**.
No other change required.

## A4. Gates (backend round — run via `./run.sh`; all must pass before each commit)

```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```
(The pre-commit hook also runs `pnpm run verify` + `check_tdd.sh`.) If a commit/merge
fails with "requirements are unsatisfiable" (vendored dep newer than the machine's
global 7-day `uv` cutoff), prefix git with `UV_FROZEN=1`; use
`./run.sh uv run --frozen pytest` for ad-hoc runs. Do not edit hook scripts.
**No on-device testing during the loop** (see §B6).

---

# PART B — Coordination protocol (for the implementer)

## B1. Setup
1. `git status` — this plan doc (`docs/plans/restore_history_trigger.md`) is delivered
   untracked by the reviewer; expected. Run the implementer skill's discovery + emit
   `AGENT_PROTOCOL_HANDSHAKE`.
2. `git checkout dev && git pull`, then
   `git checkout -b fix/restore-history-trigger dev`.
3. Commit the plan doc: `docs(plans): add restore history trigger fix plan`.

## B2. Implement (atomic conventional commits, TDD order)
- `test(history): add failing point-in-time restore integration test` (A1a+A1b, RED)
- `fix(restore): record point-in-time restore as manual_restore` (A2, GREEN)

Run the A4 gates before each commit. **Commit ALL work before signaling** (ensure
`git status` is clean except the marker before B3).

## B3. Signal completion (how the implementer tells the reviewer it's done)
After the round is committed and gates pass:
```
mkdir -p /tmp/sdh_ludusavi
touch /tmp/sdh_ludusavi/restore_history_trigger_finished
```
Empty file; existence + fresh mtime is the signal. **Re-`touch` it at the end of EVERY
round** so the reviewer's mtime-based watcher re-fires.

## B4. Wait for review notes (how the implementer knows the review is done)
Reviewer writes findings to `docs/review/restore_history_trigger_review_<n>.md`. **Own
the wait loop yourself** with the `Monitor` tool (never delegate to a background
subagent). After touching the marker for round `N`, poll ~60s for the next-numbered
note:
```
test -f docs/review/restore_history_trigger_review_<N>.md
```
(`<N>` = 1, then 2, …). When it appears, read it.

## B5. Process each review round, then loop
1. Address EVERY item in the note as atomic commits; run A4 gates each time.
2. Commit the review-note file if not already
   (`docs(review): record restore history trigger review round <n>`).
3. Re-`touch /tmp/sdh_ludusavi/restore_history_trigger_finished`.
4. Return to B4 and wait for the next-numbered note.

Repeat until a review note's body contains the literal token **`PASS`** → go to B6.

## B6. Endgame (only after a review note contains `PASS`)
> **On-device / user testing is deferred to AFTER this step.** PASS is granted on code
> review + green gates alone; do NOT wait for Steam Deck confirmation.

In order:
1. Ensure the approving review note (and all prior) are committed on the branch.
2. Record session log at
   `docs/agent_conversations/<YYYY-MM-DD>_restore_history_trigger.json`; commit it.
3. Merge into `dev`:
   ```
   git checkout dev
   git pull --ff-only
   git merge --no-ff fix/restore-history-trigger
   ```
   (`UV_FROZEN=1 git merge …` if hook re-resolution fails.)
4. Clean up:
   ```
   git branch -d fix/restore-history-trigger
   rm -f /tmp/sdh_ludusavi/restore_history_trigger_finished
   ```
5. Push: `git push origin dev`.
6. Dev release (workflow dispatch — NOT a stable tag/release):
   `./scripts/request_dev_release.sh 0.3.0` (needs `gh` auth; surface failures).
7. Report the merge SHA + dev-release dispatch. On the `v0.3.0-dev.*` build the user
   will do a point-in-time restore and confirm Last Operation → "Restore complete".

---

## Reviewer side (for reference — implementer does not do these)
- Watch `/tmp/sdh_ludusavi/restore_history_trigger_finished` (`Monitor`, ~60s, mtime
  cutoff). On fire, code-review the branch diff + run backend gates, then write
  `docs/review/restore_history_trigger_review_<n>.md`. When satisfied (code + gates
  only — no Deck check), write a note containing `PASS`.

## Definition of Done
- [ ] RED first: integration test through the real service/HistoryManager asserts a
      point-in-time restore yields `last_operation.status == "restored"`; plus the two
      `test_backup_browser.py` assertions expect `"manual_restore"`.
- [ ] `restore_backup_version` records trigger `"manual_restore"` (both paths);
      `history.py` untouched.
- [ ] `FakeAdapter` has a `restore_backup` stub.
- [ ] `./run.sh uv run ruff check`, `ruff format`, `ty check`, `pytest` all pass.
- [ ] Session log recorded; review notes committed.
- [ ] Branch merged to `dev`, branch deleted, marker removed; `dev` pushed; dev release
      dispatched. On-device testing deferred to the published build.
