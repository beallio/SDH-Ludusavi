# Plan: Report "no changes" for manual backup/restore that are no-ops

> This plan has TWO parties:
> - **Implementer agent** — a spawned agent that invokes the `implementer` skill, writes the code, and later finalizes (merge/push/release).
> - **Reviewer (orchestrator)** — the main Claude session that spawns the implementer, watches for completion markers, writes review notes, and approves.
>
> Assume the implementer is a literal-minded executor. Every path, filename, branch, and command below is exact — do not improvise names.

---

## 1. Context (why)

A user ran a **manual backup** of "Wobbly Life" (log `2026-06-13 14.04.46.log`, lines 319–333).
Ludusavi ran `backup --force` and reported `change: "Same"` / `changedGames: {new:0, different:0, same:1}`
(`/tmp/sdh_ludusavi/steamdeck-logs/wobbly_life_backup_force.json`) and **wrote no new snapshot** — the
latest backup in `wobbly_life_backups.json` is still `backup-20260613T004054Z` from June 13.

Despite nothing being backed up, the plugin logged `status="backed_up"` and the QAM **"Last Operation"**
line shows *"Backup complete"* with the current date/time, falsely implying a fresh backup was created.

The plugin already handles this exact `change == "Same"` situation for auto-sync-on-exit
(`check_game_exit` → `skip(..., "local_current")`), and the frontend already renders that reason as
*"Skipped — local save is already current"*. The manual backup/restore paths simply never inspect the
result's `change` field.

**Confirmed decisions (from the user):**
1. Present a no-op as the existing `skipped` / `local_current` outcome → *"Skipped — local save is already current"*. No new strings; the genuine `last_backup`/`last_restore` timestamp is preserved (not bumped).
2. Apply symmetric handling to both manual **Backup** and manual **Restore**.

---

## 2. Roles, branch, and skill

- The implementer agent **MUST** invoke the `implementer` skill (Skill tool, `skill: "implementer"`) before writing any code, and follow its TDD/atomic-commit discipline.
- All work happens on a **new branch off `dev`**:
  - Branch name: **`fix/manual-backup-no-changes`**
  - Create it from `dev`: `git checkout dev && git pull --ff-only` (if remote tracking) `&& git checkout -b fix/manual-backup-no-changes`
- The implementer **MUST NOT review its own work** — it must not run `/code-review`, write review notes, or self-approve. Review is exclusively the reviewer's job.
- Per `CLAUDE.md` §1, the implementer must emit the `AGENT_PROTOCOL_HANDSHAKE` before implementation.
- Commits: Conventional Commits, run through pre-commit. End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Gotcha (from prior sessions): if a local commit's pre-commit/`uv` step fails because a dependency is newer than the machine's 7-day `uv` cutoff, set **`UV_FROZEN=1`** for that command.

---

## 3. The communication protocol (EXACT paths)

Two filesystem channels coordinate the two parties. **Marker files written by the implementer are empty.**

### Implementer → Reviewer (markers under the project tmp dir `/tmp/sdh_ludusavi/`)
- **`/tmp/sdh_ludusavi/elegant-swinging-bengio_finished`** — touch (create empty) after EACH implementation round (initial build, and after addressing each review round) **once all quality gates pass and the round is committed**. This is the signal "ball is in the reviewer's court."
- **`/tmp/sdh_ludusavi/elegant-swinging-bengio_released`** — touch (create empty) only at the very end, after the merge → branch cleanup → push → dev-release are all done. This tells the reviewer the entire task is complete.

### Reviewer → Implementer (notes inside the PROJECT dir, tracked by git)
- Review-notes directory: **`docs/review/elegant-swinging-bengio/`** (reviewer creates it).
- Per-round findings: **`docs/review/elegant-swinging-bengio/round-01.md`**, `round-02.md`, … (incrementing). Each contains specific, actionable findings.
- Approval sentinel: **`docs/review/elegant-swinging-bengio/APPROVED`** (empty file). Created **only** when the reviewer has no further findings. Its presence = "review passed, proceed to finalization."
- Rule: the reviewer never writes a `round-NN.md` and `APPROVED` in the same pass. `APPROVED` is written only on a clean pass.

### Ownership of marker deletion
- The **reviewer** deletes `/tmp/sdh_ludusavi/elegant-swinging-bengio_finished` immediately after consuming it (so the next appearance is an unambiguous fresh signal). The implementer re-creates it each round.

---

## 4. The loop (step by step)

### 4a. Implementer — initial round
1. `Skill: implementer`. Emit `AGENT_PROTOCOL_HANDSHAKE`.
2. Create branch `fix/manual-backup-no-changes` from `dev` (see §2).
3. Write the protocol plan doc `docs/plans/manual_backup_no_changes.md` (mirror §1, §5, §6 here).
4. **TDD RED** — add the tests in §6 first; run `./run.sh uv run pytest tests/test_history_integration.py -k "skip or no_change"` and confirm they FAIL.
5. **GREEN** — implement the code change in §5 (minimal).
6. **REFACTOR** — factor the shared logic if it reads cleanly; keep tests green.
7. Run ALL quality gates (§7). Everything must pass.
8. Commit (atomic, Conventional Commits) on the working branch. Suggested: `fix(qam): report no-op manual backup/restore as skipped`.
9. `touch /tmp/sdh_ludusavi/elegant-swinging-bengio_finished`.
10. Enter the **wait loop** (4c).

### 4b. Reviewer — review pass (orchestrator owns this directly)
1. Wait for `/tmp/sdh_ludusavi/elegant-swinging-bengio_finished` using the **Monitor tool directly** (do NOT spawn a subagent to watch — prior attempts to delegate this failed repeatedly).
2. When it appears: delete it. Then review the diff of `fix/manual-backup-no-changes` vs `dev` (`git diff dev...fix/manual-backup-no-changes`, read changed files, optionally run the `/code-review` skill).
3. **If findings:** write `docs/review/elegant-swinging-bengio/round-NN.md` (next number) with concrete, actionable notes. Go back to step 1 (Monitor for the next `_finished`).
4. **If clean:** create empty `docs/review/elegant-swinging-bengio/APPROVED`. Then Monitor for `/tmp/sdh_ludusavi/elegant-swinging-bengio_released`.
5. When `_released` appears: report completion to the user (branch merged, dev pushed, dev release dispatched).

### 4c. Implementer — wait loop (after each `_finished`)
Use the **Monitor tool** to watch `docs/review/elegant-swinging-bengio/` (foreground `sleep` is blocked; use Monitor with an until-condition). On wake:
- If **`APPROVED`** exists → go to **Finalization (§4d)**.
- Else if a **new `round-NN.md`** exists (number higher than the last one processed) →
  1. Read it. Address every finding (TDD where behavior changes).
  2. Re-run ALL quality gates (§7).
  3. Commit the changes (atomic, Conventional Commits).
  4. `touch /tmp/sdh_ludusavi/elegant-swinging-bengio_finished` again.
  5. Keep waiting.
- Else → keep waiting.

### 4d. Implementer — finalization (only after `APPROVED` exists)
Run these in order, on the working branch first:
1. **Commit the review notes** if not already committed: `git add docs/review/elegant-swinging-bengio/ && git commit -m "docs(review): record review notes for manual backup no-op fix" ...` (skip if already committed/clean).
2. Switch to `dev` and merge the working branch with a merge commit (repo convention uses merge commits into `dev`):
   `git checkout dev` → `git merge --no-ff fix/manual-backup-no-changes`
3. **Clean up** the working branch: `git branch -d fix/manual-backup-no-changes`
4. **Push dev** to GitHub: `git push origin dev`
5. **Dispatch a dev release** (explicitly authorized by the user, overriding `CLAUDE.md` §14's default prohibition):
   `./scripts/request_dev_release.sh 0.3.0`
   (Base version is `0.3.0` per `package.json`/`plugin.json`. The script needs `gh` auth and the commit to be on the remote — that's why push (step 4) precedes it. If `gh auth status` fails, stop and report rather than guessing.)
6. `touch /tmp/sdh_ludusavi/elegant-swinging-bengio_released`.
7. Write the session log `docs/agent_conversations/<YYYY-MM-DD>_manual_backup_no_changes.json` (per `CLAUDE.md` §15) and include it in a final commit if needed (then re-push dev). Keep this lightweight; do not re-trigger another release.

---

## 5. Implementation details (the code change)

All required production changes are **backend-only** — the "Last Operation" line is driven by re-fetched
backend history (`getGameHistoryCall()` → `last_operation`), and the frontend already renders
`skipped`/`local_current` (`src/formatting/operationText.ts:19-20`). The TypeScript `OperationResult`
type already includes `status: "skipped"` and `reason?: string` — **no type or frontend changes needed.**

### File: `py_modules/sdh_ludusavi/lifecycle.py`

**(a) Add a defensive helper** (mirrors how `check_game_exit` reads `game_output.get("change")` at line 311):

```python
def _result_change(self, result: object, game_name: str) -> str | None:
    """Return the per-game ludusavi `change` ("Same"/"Different"/"New") or None."""
    if not isinstance(result, dict):
        return None
    games = result.get("games")
    if not isinstance(games, dict):
        return None
    game_output = games.get(game_name)
    if not isinstance(game_output, dict):
        return None
    change = game_output.get("change")
    return change if isinstance(change, str) else None
```

**(b) `force_backup()` (currently lines 380–405):** after `result = run_locked(...)`, branch on the change.
- If `change == "Same"`: record a skip and return skipped.
  - `record_history(game.name, "backup", "manual_backup", "skipped", reason="local_current")`
  - return `{"status": "skipped", "reason": "local_current", "game": game.name, "result": result}`
  - log info: `f"Backup skipped for {game.name}: local save already current"`
- Otherwise (`"Different"`, `"New"`, or **change missing/None**): keep existing behavior — `record_history(..., "backed_up")`, return `{"status": "backed_up", "game": game.name, "result": result}`.
- Keep the existing `except Exception` → `record_history(..., "failed", message=str(exc))` + `raise`.
- Call `registry.refresh_after_operation(game.name)` on BOTH the skip and backed_up paths (as today).

Reference shape of the new body (preserve existing lock/except structure):

```python
try:
    result = self.dependencies.run_locked(
        "backup", game.name,
        lambda: self.dependencies.gateway.get_adapter().backup(game.name),
    )
    change = self._result_change(result, game.name)
    if change == "Same":
        self.dependencies.history.record_history(
            game.name, "backup", "manual_backup", "skipped", reason="local_current"
        )
    else:
        self.dependencies.history.record_history(
            game.name, "backup", "manual_backup", "backed_up"
        )
except Exception as exc:
    self.dependencies.history.record_history(
        game.name, "backup", "manual_backup", "failed", message=str(exc)
    )
    raise

self.dependencies.registry.refresh_after_operation(game.name)
if change == "Same":
    self.dependencies.log(
        "info", f"Backup skipped for {game.name}: local save already current", "backup", game.name
    )
    return {"status": "skipped", "reason": "local_current", "game": game.name, "result": result}
self.dependencies.log("info", f"Backed up {game.name}", "backup", game.name)
return {"status": "backed_up", "game": game.name, "result": result}
```
(Note `change` must be in scope after the `try`; assign it to `None` before the `try` if a linter flags possibly-unbound, or keep the assignment inside and guard. Implementer: choose whichever keeps `ty`/`ruff` clean.)

**(c) `force_restore()` (currently lines 407–431):** apply the SAME pattern using the restore result, with
operation `"restore"` / trigger `"manual_restore"`. On `change == "Same"` →
`record_history(game.name, "restore", "manual_restore", "skipped", reason="local_current")` and return
`{"status": "skipped", "reason": "local_current", "game": game.name, "result": result}`; otherwise the
existing `"restored"` path. (A forced restore when local already matches the backup is a no-op; the
restore still ran, but the user-facing outcome is "no change" — consistent with the backup case.)

**Scope note:** point-in-time restore (`restore_backup_version` / `runSnapshotRestore`) is **left unchanged** — it is a deliberate user selection of a specific snapshot.

### Why no frontend change
`history.py` already routes `status == "skipped"` into the `last_skip` slot and recomputes
`last_operation` as the newest entry. So a no-op manual backup leaves `last_backup` at the real last
snapshot, writes `last_skip` at the current time, and makes `last_operation` the skip →
"Last Operation" shows *"Skipped — local save is already current"* at the current time. Exactly desired.

### Optional polish (NOT required; only if a review round asks)
`summarizeOperationResult` (`src/formatting/operationText.ts:58-71`) prefixes skips with
*"Auto-sync skipped:"*, so a manual notification toast would read "Auto-sync skipped: local save is
already current". Manual-operation notifications are off by default; this is cosmetic. Do not change
unless a review note requests it.

---

## 6. Testing strategy (TDD — RED first)

Add tests to `tests/test_history_integration.py`, reusing `FakeAdapter` + `service_with_state` imported
from `tests/test_service.py`. Crucial guard: the shared `FakeAdapter.backup()`/`restore()` return
`{"ok": True, ...}` with **no `games`/`change`**, which must keep defaulting to `backed_up`/`restored` —
this protects all existing callers. Follow the monkeypatch pattern already at `tests/test_service.py:1242-1264`.

Add these tests (names are suggestions; keep `skip`/`no_change` in at least the backup-Same test name so the RED command in §4a-4 matches):
1. **`test_force_backup_no_changes_records_skip`** — monkeypatch `adapter.backup` so non-preview returns
   `{"overall": {"changedGames": {"new":0,"different":0,"same":1}}, "games": {name: {"change": "Same", "decision": "Processed"}}}`.
   Assert: `force_backup` → `{"status": "skipped", "reason": "local_current"}`; after `refresh_games()`,
   `history["last_skip"]` has `status="skipped"`, `reason="local_current"`, `operation="backup"`,
   `trigger="manual_backup"`; `history["last_backup"] is None`; `history["last_operation"]["status"] == "skipped"`.
2. **`test_force_backup_different_records_backed_up`** — non-preview returns `change="Different"` →
   `status="backed_up"`, `last_backup` populated (regression guard).
3. **`test_force_backup_missing_change_defaults_backed_up`** — default `FakeAdapter` (no `games`) →
   `status="backed_up"` (guards existing behavior/all existing tests).
4. **`test_force_restore_no_changes_records_skip`** — monkeypatch `adapter.restore` non-preview to return
   `change="Same"` → `status="skipped"`, `reason="local_current"`; `history["last_skip"]` populated with
   `operation="restore"`/`trigger="manual_restore"`; `history["last_restore"] is None`.
5. **`test_force_restore_different_records_restored`** — `change="Different"` → `status="restored"` (regression guard).

RED check (must fail before implementing): `./run.sh uv run pytest tests/test_history_integration.py -k "skip or no_change"`

---

## 7. Quality gates (run via `./run.sh`, all must pass before each `_finished`)

```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest        # full suite; coverage gate --cov-fail-under=83
```
Caches/venv are redirected to `/tmp/sdh_ludusavi` by `run.sh` — never create caches in the repo.

---

## 8. Files touched

- `py_modules/sdh_ludusavi/lifecycle.py` — `_result_change` helper; branch in `force_backup` + `force_restore`.
- `tests/test_history_integration.py` — the 5 tests in §6.
- `docs/plans/manual_backup_no_changes.md` — protocol plan doc.
- `docs/review/elegant-swinging-bengio/` — reviewer's `round-NN.md` + `APPROVED` (committed during finalization).
- `docs/agent_conversations/<date>_manual_backup_no_changes.json` — session log.
- No frontend/TypeScript changes (unless a review round requests the optional polish in §5).

---

## 9. Verification & deferred Steam Deck testing

- Pre-merge gating is **automated tests (§7) + reviewer code review only**.
- **On-device / user testing on the Steam Deck is deferred until after the dev release is published on GitHub** — the dev prerelease (`v0.3.0-dev.<sha>`) is what gets installed on the deck for manual verification. Do not block the merge/push/release on Steam Deck testing.
- Post-release manual checks to perform on the deck (after the dev release lands):
  1. Manual backup of a game whose save is unchanged → "Last Operation" reads *"Skipped — local save is already current"* at the current time; **no** new folder under `~/ludusavi-backup/<game>/`; `last_backup` timestamp unchanged.
  2. Manual backup of a game with real changes → still *"Backup complete"* and a new snapshot is written.
  3. Manual restore when local already matches backup → *"Skipped — local save is already current"*; a restore that changes files → *"Restore complete"*.

---

## 10. Quick reference — exact strings

| Purpose | Exact path |
|---|---|
| Working branch | `fix/manual-backup-no-changes` (from `dev`) |
| Impl-complete marker (agent→reviewer, empty) | `/tmp/sdh_ludusavi/elegant-swinging-bengio_finished` |
| All-done marker (agent→reviewer, empty) | `/tmp/sdh_ludusavi/elegant-swinging-bengio_released` |
| Review notes dir (reviewer→agent) | `docs/review/elegant-swinging-bengio/` |
| Per-round findings | `docs/review/elegant-swinging-bengio/round-01.md`, `round-02.md`, … |
| Approval sentinel (reviewer→agent, empty) | `docs/review/elegant-swinging-bengio/APPROVED` |
| Dev release base version | `0.3.0` → `./scripts/request_dev_release.sh 0.3.0` |
