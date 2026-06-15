# Plan: Fix restore no-op reporting + make "Last Operation" skip text operation-aware

**Plan slug (used everywhere):** `restore-noop-and-skip-labels`

---

## 1. Context (why)

A user exercised manual **Backup** and **Restore** of *Wobbly Life* on the Steam Deck
(log `/tmp/sdh_ludusavi/steamdeck-logs/2026-06-14 16.07.36.log`). Two reporting defects surfaced:

1. **Backup no-op text is too terse.** When a manual backup is a no-op (Ludusavi returns
   `change: "Same"`), the backend already reports `status="skipped" reason="local_current"`
   (log lines 88–90) — that part is correct. But the QAM **"Last Operation"** line renders just
   *"Skipped — local save is already current"*. The desired text names the operation:
   *"Backup skipped — …"*.

2. **Restore no-op is falsely reported as success.** The point-in-time restore
   (`restore --force --backup backup-20260613T004054Z 'Wobbly Life'`, log lines 109–120) ran but
   Ludusavi changed **nothing** — every file came back `"change": "Same"` and
   `overall.changedGames = {new:0, different:0, same:1}` (confirmed by the user's
   `restore … --api --preview` output). Despite that, the backend logged
   `status="restored"` and "Last Operation" showed *"Restore complete"*, falsely implying files
   were restored.

**Root causes (verified in code):**
- `force_backup()` and `force_restore()` already inspect the result's `change` field via the
  `_result_change()` helper and report a no-op as `skipped`/`local_current`
  (`py_modules/sdh_ludusavi/lifecycle.py:95-106`, `force_backup` ~ lines 393-441, `force_restore`
  lines 443-492). **`restore_backup_version()` (lines 505-546) never inspects `change`** — it
  always records `"restored"`. This is the restore bug (defect #2).
- The frontend formatter `getLastOperationText()` (`src/formatting/operationText.ts:3-49`) switches
  on `status`/`reason` only and never sees the `operation` field, so every skip reads "Skipped — …"
  regardless of whether it was a backup or restore (defect #1).

**Confirmed decisions (from the user):**
1. **Wording (no-op):**
   - Backup no-op → **"Backup skipped — local save is already current"**
   - Restore no-op → **"Restore skipped — local save already matches backup"**
2. **Scope of the verb prefix:** make **all** `skipped` messages operation-aware
   ("Backup skipped — …" / "Restore skipped — …"), not only the no-op case. Map auto lifecycle
   operations too: `start` → Restore, `exit` → Backup. Unknown/missing operation falls back to the
   current generic "Skipped — …".
3. Success messages ("Backup complete" / "Restore complete") are **unchanged**; they are correct for
   real operations. The restore-success complaint is fixed by defect #2 (a true no-op now reports as
   skipped, so it no longer says "Restore complete").
4. On-device / user testing on the Steam Deck is **deferred until after the dev release is pushed to
   GitHub** (the `v0.3.0-dev.<sha>` prerelease is what gets installed on the deck).

---

## 2. Roles, branch, and skill

- **MUST** invoke the `implementer` skill (Skill tool, `skill: "implementer"`) before writing any
  code, and follow its TDD / atomic-commit discipline.
- Per `CLAUDE.md` §1, emit the `AGENT_PROTOCOL_HANDSHAKE` after read-only verification
  (`pwd`, `ls`, `git status`, dependency/config inspection) and before implementation.
- All work happens on a **new branch off `dev`**:
  - Branch name: **`fix/restore-noop-and-skip-labels`**
  - Create it: `git checkout dev` → (if it has remote tracking) `git pull --ff-only` →
    `git checkout -b fix/restore-noop-and-skip-labels`
- **Do NOT review your own work** — no `/code-review`, no writing review notes, no self-approval. A
  separate reviewer handles review (see §3/§4).
- Commits: Conventional Commits, run through pre-commit. End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- All project tooling runs through **`./run.sh`** (caches redirected to `/tmp/sdh_ludusavi`).
- Gotcha (from prior sessions): if a local commit's pre-commit/`uv` step fails because a dependency
  is newer than the machine's 7-day `uv` cutoff, set **`UV_FROZEN=1`** for that command.

---

## 3. The communication protocol (EXACT paths)

Two filesystem channels coordinate work. **Marker files you write are empty.**

### Implementer → Reviewer (empty markers under the project tmp dir `/tmp/sdh_ludusavi/`)
- **`/tmp/sdh_ludusavi/restore-noop-and-skip-labels_finished`** — `touch` (create empty) after EACH
  implementation round (the initial build, and after addressing each review round) **once all quality
  gates pass and the round is committed**. This signals "ball is in the reviewer's court."
- **`/tmp/sdh_ludusavi/restore-noop-and-skip-labels_released`** — `touch` (create empty) only at the
  very end, after merge → branch cleanup → push → dev-release are all done. This signals the entire
  task is complete.

### Reviewer → Implementer (notes inside the PROJECT dir, tracked by git)
- Review-notes directory: **`docs/review/restore-noop-and-skip-labels/`** (the reviewer creates it).
- Per-round findings: **`docs/review/restore-noop-and-skip-labels/round-01.md`**, `round-02.md`, …
  (incrementing). Each contains specific, actionable findings to address.
- Approval sentinel: **`docs/review/restore-noop-and-skip-labels/APPROVED`** (empty file). Its
  presence = "review passed, proceed to finalization."

---

## 4. The loop (step by step)

### 4a. Initial round
1. `Skill: implementer`. Emit `AGENT_PROTOCOL_HANDSHAKE`.
2. Create branch `fix/restore-noop-and-skip-labels` from `dev` (see §2).
3. Ensure the plan doc `docs/plans/restore-noop-and-skip-labels.md` exists (this file). If absent,
   create it from this content.
4. **TDD RED** — add the tests in §6 first (backend + frontend); confirm they FAIL:
   - Backend: `./run.sh uv run pytest tests/test_history_integration.py -k "restore_backup_version"`
   - Frontend: `pnpm run test:unit -- operationText` (the new `operationText.test.ts` cases fail).
5. **GREEN** — implement the minimal code changes in §5 (backend) and §5 (frontend).
6. **REFACTOR** — tidy while keeping tests green.
7. Run ALL quality gates (§7). Everything must pass.
8. Commit (atomic, Conventional Commits) on the working branch. Suggested split:
   - `fix(qam): report point-in-time restore no-op as skipped`
   - `fix(ui): make Last Operation skip text operation-aware`
   (Two atomic commits preferred; one combined commit is acceptable if gates stay green.)
9. `touch /tmp/sdh_ludusavi/restore-noop-and-skip-labels_finished`.
10. Enter the **wait loop** (4b).

### 4b. Wait loop (after each `_finished`)
Use the **Monitor tool** to watch `docs/review/restore-noop-and-skip-labels/` (foreground `sleep` is
blocked; use Monitor with an until-condition). On wake:
- If **`APPROVED`** exists → go to **Finalization (§4c)**.
- Else if a **new `round-NN.md`** exists (number higher than the last processed) →
  1. Read it. Address every finding (TDD where behavior changes).
  2. Re-run ALL quality gates (§7).
  3. Commit the changes (atomic, Conventional Commits).
  4. `touch /tmp/sdh_ludusavi/restore-noop-and-skip-labels_finished` again.
  5. Keep waiting.
- Else → keep waiting.

### 4c. Finalization (only after `APPROVED` exists)
Run in order, on the working branch first:
1. **Commit the review notes** if not already committed:
   `git add docs/review/restore-noop-and-skip-labels/ && git commit -m "docs(review): record review notes for restore no-op + skip labels"`
   (skip if already committed/clean).
2. Switch to `dev` and merge with a merge commit (repo convention uses `--no-ff` merges into `dev`):
   `git checkout dev` → `git merge --no-ff fix/restore-noop-and-skip-labels`
3. **Clean up** the working branch: `git branch -d fix/restore-noop-and-skip-labels`
4. **Push dev** to GitHub: `git push origin dev`
5. **Dispatch a dev release** (explicitly authorized by the user, overriding `CLAUDE.md` §14's default
   prohibition): `./scripts/request_dev_release.sh 0.3.0`
   (Base version `0.3.0` per `package.json`/`plugin.json`. The script needs `gh` auth and the commit
   to be on the remote — that is why push (step 4) precedes it. If `gh auth status` fails, **stop and
   report** rather than guessing.)
6. Write the session log `docs/agent_conversations/<YYYY-MM-DD>_restore_noop_and_skip_labels.json`
   (per `CLAUDE.md` §15: date, task objective, files modified, tests added, design decisions,
   quality-gate results). Commit it (`docs(session): …`) and re-push `dev`. Do **not** trigger another
   release.
7. `touch /tmp/sdh_ludusavi/restore-noop-and-skip-labels_released`.

---

## 5. Implementation details (the code changes)

### 5A. Backend — `py_modules/sdh_ludusavi/lifecycle.py`

**Reuse the existing `_result_change()` helper (lines 95-106).** No new helper needed.

Modify **`restore_backup_version()` (lines 505-546)** so it detects the `change == "Same"` no-op,
exactly mirroring `force_restore()` (lines 443-492). Replace the body after the `run_locked` block so it:

- Reads `change = self._result_change(result, game.name)` inside the `try` (right after `result = …`).
- If `change == "Same"`: `record_history(game.name, "restore", "manual_restore", "skipped", reason="local_current")`.
- Else: keep `record_history(game.name, "restore", "manual_restore", "restored")`.
- Preserve the existing `except OperationLockedError: raise` and the broad
  `except Exception as exc: record_history(..., "failed", message=str(exc)); raise`.
- Keep `registry.refresh_after_operation(game.name)` on both the skip and restored paths.
- On the skip path: log `f"Restore skipped for {game.name} from backup {backup_id}: local save already matches backup"`
  and return `{"status": "skipped", "reason": "local_current", "game": game.name, "backup_id": backup_id, "result": result}`.
- On the restored path: keep the existing log `f"Restored {game.name} from backup {backup_id}"`
  and return `{"status": "restored", "game": game.name, "backup_id": backup_id, "result": result}`.

Reference shape (preserve the existing validation guard above it; `OperationLockedError` re-raise stays):

```python
try:
    result = self.dependencies.run_locked(
        "restore",
        game.name,
        lambda: self.dependencies.gateway.get_adapter().restore_backup(
            game.name, backup_id
        ),
    )
    change = self._result_change(result, game.name)
    if change == "Same":
        self.dependencies.history.record_history(
            game.name, "restore", "manual_restore", "skipped", reason="local_current"
        )
    else:
        self.dependencies.history.record_history(
            game.name, "restore", "manual_restore", "restored"
        )
except OperationLockedError:
    raise
# Intentionally broad: record history and re-raise on point in time restore failure
except Exception as exc:
    self.dependencies.history.record_history(
        game.name, "restore", "manual_restore", "failed", message=str(exc)
    )
    raise

self.dependencies.registry.refresh_after_operation(game.name)
if change == "Same":
    self.dependencies.log(
        "info",
        f"Restore skipped for {game.name} from backup {backup_id}: local save already matches backup",
        "restore",
        game.name,
    )
    return {
        "status": "skipped",
        "reason": "local_current",
        "game": game.name,
        "backup_id": backup_id,
        "result": result,
    }
self.dependencies.log(
    "info", f"Restored {game.name} from backup {backup_id}", "restore", game.name
)
return {
    "status": "restored",
    "game": game.name,
    "backup_id": backup_id,
    "result": result,
}
```

- **Linter note:** if `ty`/`ruff` flags `change` as possibly-unbound after the `try`, initialize
  `change: str | None = None` immediately before the `try`. (`force_restore` assigns it inside the
  `try` and uses it after, and passes gates — mirror that; add the pre-init only if a checker complains.)
- **Why this is safe:** the forced point-in-time restore runs `restore --force --backup <id> --api`,
  which returns the same per-game `change` field the backup/restore no-op detection already relies on.
  When ludusavi omits `games`/`change` (e.g. the default `FakeAdapter.restore_backup`), `_result_change`
  returns `None`, so the behavior stays `"restored"` — no regression.
- **Do NOT touch** `force_backup` / `force_restore` (already correct) or the `check_game_start` /
  `check_game_exit` auto paths.

### 5B. Frontend — `src/formatting/operationText.ts`

Make `getLastOperationText()` operation-aware. Add a 4th parameter `operation: string | null = null`
(keep it optional/defaulted so existing callers/tests don't break), and rework only the `"skipped"`
branch. Leave `"backed_up"`, `"restored"`, `"failed"`, and the default unchanged.

Target behavior for `status === "skipped"`:
- **Verb label** from `operation`:
  - `"backup"` or `"exit"` → `"Backup skipped"`
  - `"restore"` or `"start"` → `"Restore skipped"`
  - anything else / null → `"Skipped"` (current behavior, backward compatible)
- **Detail** from `reason` (same texts as today, minus the leading "Skipped — "), with one
  operation-dependent special case for `local_current`:
  - `local_current` → if the verb is Restore (`operation` is `"restore"`/`"start"`):
    `"local save already matches backup"`; otherwise `"local save is already current"`.
  - `remote_current` → `"cloud save is already current"`
  - `not_processed` → `"game is deselected in Ludusavi"`
  - `no_backup` → `"no backup found"`
  - `ambiguous_recency` → `"recency is ambiguous"`
  - `conflict_unresolved` → `"save conflict was not resolved"`
  - `no_files_found` → `"no files found"`
  - `preview_failed` → `"preview failed"`
  - `auto_sync_disabled` → `"feature disabled"`
  - `operation_running` → `"another operation is running"`
  - `unmatched_game` → `"could not match game name"`
  - default (unknown reason) → `reason.replace(/_/g, " ")`
  - no `reason` but a `message` → the `message`
  - no `reason` and no `message` → no detail
- **Assemble:** `detail ? `${label} — ${detail}` : label`.

Example outputs (these are the acceptance strings — assert them in tests):
- `("skipped","local_current",null,"backup")` → `"Backup skipped — local save is already current"`
- `("skipped","local_current",null,"restore")` → `"Restore skipped — local save already matches backup"`
- `("skipped","local_current",null,"exit")` → `"Backup skipped — local save is already current"`
- `("skipped","local_current",null,"start")` → `"Restore skipped — local save already matches backup"`
- `("skipped","no_backup",null,"restore")` → `"Restore skipped — no backup found"`
- `("skipped","operation_running",null,"backup")` → `"Backup skipped — another operation is running"`
- `("skipped","local_current",null,null)` → `"Skipped — local save is already current"` (backward compat)
- `("skipped",null,null,"backup")` → `"Backup skipped"`
- `("backed_up",null,null,"backup")` → `"Backup complete"` (unchanged)
- `("restored",null,null,"restore")` → `"Restore complete"` (unchanged)

> Implementation hint: extract a small `skipLabel(operation)` helper and reuse the existing
> reason→detail mapping; keep the `default` case using `reason.replace(/_/g, " ")`. Avoid `switch`
> fall-through bugs (the existing `case "failed":` declares `const err` — keep block scoping with
> braces if you reorganize).

### 5C. Frontend — call site `src/components/qam/GameSettingsSection.tsx` (lines 122-126)

Pass the operation through:

```tsx
{getLastOperationText(
  selectedHistory.status,
  selectedHistory.reason,
  selectedHistory.message,
  selectedHistory.operation,
)}
```

`selectedHistory` is a `GameOperationHistoryEntry` whose `operation` field
(`"backup" | "restore" | "start" | "exit"`) already exists (`src/types/index.ts:51-58`) and is carried
on `last_operation`. **No type change required.**

### 5D. No change required to `runSnapshotRestore` or `summarizeOperationResult`
- `runSnapshotRestore` (`src/components/qam/LudusaviContent.tsx:706-756`) already handles a `skipped`
  status gracefully — it only treats `status === "failed"` as an error and otherwise re-fetches
  history, which drives the corrected "Last Operation" line. **Leave it unchanged.**
- `summarizeOperationResult` (`operationText.ts:51-77`) builds the optional toast and currently prefixes
  skips with "Auto-sync skipped:". Manual-op notifications are off by default, and this is not the
  "Last Operation" line, so it is **out of scope** — change it only if a review round explicitly asks.

---

## 6. Testing strategy (TDD — RED first)

### 6A. Backend — `tests/test_history_integration.py`
Reuse `FakeAdapter` + `service_with_state` (imported from `tests/test_service.py`). `FakeAdapter`
already has `restore_backup(game_name, backup_id)` returning `{"ok": True, ...}` (no `games`/`change`),
so the default path must keep returning `"restored"`. Mirror the monkeypatch style of
`test_force_restore_no_changes_records_skip` (lines 252-276). Add:

1. **`test_restore_backup_version_no_changes_records_skip`** — monkeypatch `adapter.restore_backup`
   to append to `adapter.restores` and return
   `{"games": {name: {"change": "Same", "decision": "Processed"}}}`. Assert:
   `service.restore_backup_version(name, "backup-123")` → `{"status": "skipped", "reason": "local_current"}`;
   after `refresh_games()`, `history["last_skip"]` has `status="skipped"`, `reason="local_current"`,
   `operation="restore"`, `trigger="manual_restore"`; `history["last_restore"] is None`;
   `history["last_operation"]["status"] == "skipped"`.
2. **`test_restore_backup_version_different_records_restored`** — monkeypatch to return
   `change="Different"` → `status="restored"`; `history["last_restore"]["status"] == "restored"`
   (regression guard).
3. **`test_restore_backup_version_missing_change_defaults_restored`** — default `FakeAdapter`
   (no `games`/`change`) → `status="restored"` (guards existing behavior and existing callers such as
   the test near `tests/test_history_integration.py:51`).

RED check (must fail before implementing):
`./run.sh uv run pytest tests/test_history_integration.py -k "restore_backup_version"`

### 6B. Frontend — new file `src/formatting/operationText.test.ts` (vitest)
Mirror the style of `src/formatting/bytes.test.ts` / `dateTime.test.ts`
(`import { describe, it, expect } from "vitest"`). Cover every acceptance string in §5B, including:
backup/restore/start/exit `local_current`; a non-`local_current` reason per operation
(`no_backup`, `operation_running`); the null-operation backward-compat case; `skipped` with no reason;
and that `backed_up`→"Backup complete", `restored`→"Restore complete", `failed`→"Failed — …" are
unchanged.

RED check (must fail before implementing): `pnpm run test:unit -- operationText`

---

## 7. Quality gates (all must pass before each `_finished` marker)

Backend (via `./run.sh`, caches redirect to `/tmp/sdh_ludusavi`):
```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest        # full suite; coverage gate enforced
```
Frontend:
```
pnpm run test:unit            # vitest (includes the new operationText.test.ts)
pnpm run typecheck            # tsc --noEmit
```
Never create caches inside the repo. The pre-commit hook also runs `scripts/check_tdd.sh` (every new
or modified `py_modules/sdh_ludusavi/*.py` needs a matching `tests/test_*.py`); `lifecycle.py` already
has `tests/test_lifecycle.py`, and the behavior change is covered in `test_history_integration.py`.

---

## 8. Files touched

- `py_modules/sdh_ludusavi/lifecycle.py` — no-op branch in `restore_backup_version` (§5A).
- `src/formatting/operationText.ts` — operation-aware `getLastOperationText` (§5B).
- `src/components/qam/GameSettingsSection.tsx` — pass `selectedHistory.operation` (§5C).
- `tests/test_history_integration.py` — 3 backend tests (§6A).
- `src/formatting/operationText.test.ts` — new frontend tests (§6B).
- `docs/plans/restore-noop-and-skip-labels.md` — this plan doc.
- `docs/review/restore-noop-and-skip-labels/` — reviewer's `round-NN.md` + `APPROVED`
  (committed during finalization).
- `docs/agent_conversations/<date>_restore_noop_and_skip_labels.json` — session log.

---

## 9. Verification & deferred Steam Deck testing

- Pre-merge gating is **automated tests (§7) + reviewer code review only**.
- **On-device / user testing on the Steam Deck is deferred until after the dev release is pushed to
  GitHub.** The dev prerelease (`v0.3.0-dev.<sha>`) is what gets installed on the deck for manual
  verification. Do **not** block merge/push/release on Steam Deck testing.
- Post-release manual checks to perform on the deck (after the dev release lands):
  1. Manual **backup** of an unchanged game → "Last Operation" reads
     *"Backup skipped — local save is already current"* at the current time; no new snapshot folder.
  2. Manual **point-in-time restore** of a snapshot whose contents already match local
     (the *Wobbly Life* case) → "Last Operation" reads
     *"Restore skipped — local save already matches backup"*, **not** "Restore complete";
     log shows `status="skipped" reason="local_current"`.
  3. A restore that actually changes files → still *"Restore complete"*; a backup with real changes →
     still *"Backup complete"*.

---

## 10. Quick reference — exact strings

| Purpose | Exact value |
|---|---|
| Plan slug | `restore-noop-and-skip-labels` |
| Working branch | `fix/restore-noop-and-skip-labels` (from `dev`) |
| Impl-complete marker (empty) | `/tmp/sdh_ludusavi/restore-noop-and-skip-labels_finished` |
| All-done marker (empty) | `/tmp/sdh_ludusavi/restore-noop-and-skip-labels_released` |
| Review notes dir | `docs/review/restore-noop-and-skip-labels/` |
| Per-round findings | `docs/review/restore-noop-and-skip-labels/round-01.md`, `round-02.md`, … |
| Approval sentinel (empty) | `docs/review/restore-noop-and-skip-labels/APPROVED` |
| Dev release base version | `0.3.0` → `./scripts/request_dev_release.sh 0.3.0` |
| Backup no-op text | `Backup skipped — local save is already current` |
| Restore no-op text | `Restore skipped — local save already matches backup` |
