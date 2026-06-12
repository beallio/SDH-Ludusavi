# Backup Browser with Point-in-Time Restore — Implementation Plan

Plan name (used for all signaling files): `2026-06-12_backup_browser_point_in_time_restore`

## Context

Users currently must launch the Ludusavi GUI (via an awkward non-Steam shortcut on gamepad) to browse or manage individual backup versions. This feature adds a "Backups" action to the QAM Game Settings section that opens a modal listing all Ludusavi backup snapshots for the selected game (date, file count, size, total-size summary) and lets the user restore a specific snapshot with confirmation — completing the "never open Ludusavi directly" promise.

**Scope decisions (confirmed with the user):**
- **List + restore only.** Ludusavi has **no API to delete an individual backup** (`backups edit` supports only `--lock/--unlock/--comment` — verified in vendored `py_modules/pyludusavi/main.py:349-394` and upstream CLI docs/api schema). Delete is OUT of scope. Do not attempt filesystem deletion or `mapping.yaml` editing.
- **Per-snapshot size/file-count via disk inspection.** `backups_list` returns only `name/when/locked/os/comment` per snapshot (`ApiBackup`, `py_modules/pyludusavi/models.py:66-71`). The backend computes size/file count by inspecting the game's `backupPath` on disk. Values may be `None` when undeterminable — the UI must tolerate that.
- **Do NOT modify `py_modules/pyludusavi/`** (vendored upstream). It already has everything needed: `backups_list(games=...)` (`main.py:326`) and `restore(games=..., backup_id=...)` (`main.py:250`, `--backup` flag at line 306).

---

## Part A — Process & Orchestration Protocol (MANDATORY, read first)

1. **Use the `implementer` skill.** Invoke the `implementer` skill at the start of implementation and follow it together with `CLAUDE.md` (handshake, `./run.sh` wrapper, caches under `/tmp/sdh_ludusavi`, strict TDD, Conventional Commits, atomic commits).
2. **Work on a dedicated branch** created from `dev`:
   ```
   git checkout dev && git checkout -b feat/backup-browser
   ```
   All implementation commits go to `feat/backup-browser`. Never commit directly to `dev` during implementation.
3. **First commit:** save this plan as `docs/plans/2026-06-12_backup_browser_point_in_time_restore.md` (if not already present) and commit it (`docs(plans): add backup browser implementation plan`).
4. **Completion signal.** When implementation is complete AND all quality gates pass (Part D), create an **empty file**:
   ```
   /tmp/sdh_ludusavi/2026-06-12_backup_browser_point_in_time_restore_finished
   ```
   (`touch` it; the directory already exists — `run.sh` uses it. If missing: `mkdir -p /tmp/sdh_ludusavi`.)
5. **Review loop.** After writing the `_finished` marker, poll **every 60 seconds** for reviewer notes in the project repo at:
   ```
   docs/review/2026-06-12_backup_browser_point_in_time_restore_review_round_<N>.md
   ```
   where `<N>` is 1, 2, 3, … The presence of a new (not-yet-processed) review note is the trigger to resume work. Each review note ends with a status line:
   - `STATUS: CHANGES_REQUESTED` — address **every** finding in the note (TDD applies to behavior changes), commit the fixes on `feat/backup-browser`, then signal completion of that round by creating the empty file:
     ```
     /tmp/sdh_ludusavi/2026-06-12_backup_browser_point_in_time_restore_review_round_<N>_finished
     ```
     Then resume polling for round `<N+1>`.
   - `STATUS: APPROVED` — proceed to Finalization (step 6).
6. **Finalization (only after an APPROVED review note):**
   1. Commit any review notes / session logs not yet committed (`docs(review): record backup browser review notes`).
   2. Merge the working branch into dev and clean up:
      ```
      git checkout dev
      git merge --no-ff feat/backup-browser
      git branch -d feat/backup-browser
      ```
   3. Push dev: `git push origin dev`.
   4. Trigger a dev release: `./scripts/request_dev_release.sh 0.3.0` (base version from `plugin.json`/`package.json`, currently `0.3.0`). This is the sanctioned dev-release path (workflow dispatch); do **not** push tags or publish releases any other way.
   5. Create the final marker so the orchestrator knows everything is done:
      ```
      /tmp/sdh_ludusavi/2026-06-12_backup_browser_point_in_time_restore_release_finished
      ```
7. **Session log:** record `docs/agent_conversations/2026-06-12_backup_browser_point_in_time_restore.json` (date, objective, files modified, tests added, design decisions, results) before finalization merge.

---

## Part B — Backend Implementation (TDD: write each test first, watch it fail, then implement)

### B1. Adapter Protocol — `py_modules/sdh_ludusavi/types.py`
Add to the `LudusaviAdapter` Protocol (line 7):
```python
def list_backups(self, game_name: str) -> dict[str, object]: ...
def restore_backup(self, game_name: str, backup_id: str) -> dict[str, object]: ...
```

### B2. Adapter implementation — `py_modules/sdh_ludusavi/ludusavi.py` (`PyludusaviAdapter`, line 48)
Follow the existing `backup()`/`restore()` pattern (lines 266-287).

- `restore_backup(self, game_name, backup_id)`:
  ```python
  return cast(dict[str, object], self._client.restore(
      games=[game_name], backup_id=backup_id, force=True,
      timeout=LUDUSAVI_OPERATION_TIMEOUT_SECONDS,
  ).data)
  ```
- `list_backups(self, game_name)`:
  1. `response = self._client.backups_list(games=[game_name])` → `response.data` is `{"games": {<name>: {"backupPath": str, "backups": [ApiBackup, ...]}}}`.
  2. Look up the game entry (use the single key in `games` if exact name lookup fails; missing → return `{"game": game_name, "backup_path": None, "total_size_bytes": None, "backups": []}`).
  3. Enrich each `ApiBackup` via the disk-inspection helper (B3) and return:
     ```python
     {
       "game": game_name,
       "backup_path": backup_path,
       "total_size_bytes": int | None,   # sum of known sizes; None if all unknown
       "backups": [
         {"id": b["name"], "when": b["when"], "locked": b.get("locked", False),
          "os": b.get("os"), "comment": b.get("comment"),
          "size_bytes": int | None, "file_count": int | None},
         ...
       ],
     }
     ```
     Sort `backups` newest-first by `when`.

### B3. Disk inspection helper — module-level function in `ludusavi.py`
```python
def _backup_disk_stats(backup_path: str, backup_name: str) -> tuple[int | None, int | None]:
    """Return (size_bytes, file_count) for one snapshot, or (None, None) if undeterminable."""
```
Rules (each branch wrapped in `try/except OSError` → `(None, None)`):
- Resolve `target = Path(backup_path) / backup_name`.
- `backup_name == "."` (simple/non-versioned layout): walk `backup_path` itself, **excluding** `mapping.yaml` and any entries whose name starts with `backup-` (those are sibling snapshots).
- `target` is a directory: `os.walk` it; size = sum of `st_size`, count = number of regular files.
- `target` is a file (zip): size = `st_size`; count = `len(zipfile.ZipFile(target).namelist())` excluding directory entries (cheap central-directory read; on `BadZipFile` → count `None`, keep size).
- Neither exists: try `target.with_suffix(target.suffix + ".zip")` as a file; else `(None, None)`.

### B4. Lifecycle — `py_modules/sdh_ludusavi/lifecycle.py` (`GameLifecycleManager`)
Mirror `force_restore` (line 407) exactly:

- `list_backups(self, game_name)`:
  - `sanitize_game_name`, `registry.match_game`; unmatched → `dependencies.skip("backups_list", game_name, "unmatched_game")`.
  - Run through the coordinator to serialize CLI access:
    `self.dependencies.run_locked("backups_list", game.name, lambda: self.dependencies.gateway.get_adapter().list_backups(game.name))`
  - No history entry (read-only). Return the adapter dict.
- `restore_backup_version(self, game_name, backup_id)`:
  - Sanitize/match; skip `unmatched_game`; skip `no_backup` if `not game.has_backup`.
  - Validate `backup_id` is a non-empty string; reject anything containing path separators (`/`, `\\`, `..`) — it is passed to a CLI.
  - `run_locked("restore", game.name, lambda: ...get_adapter().restore_backup(game.name, backup_id))`, with the same try/except shape as `force_restore`: on failure `record_history(game.name, "restore", "point_in_time_restore", "failed", message=...)` and re-raise.
  - On success: `record_history(..., "point_in_time_restore", "restored")`, `registry.refresh_after_operation(game.name)`, `log("info", f"Restored {game.name} from backup {backup_id}", "restore", game.name)`.
  - Return `{"status": "restored", "game": game.name, "backup_id": backup_id, "result": result}`.

Note: `OperationLockedError` propagates as it does for force operations — frontend surfaces it.

### B5. Service facade — `py_modules/sdh_ludusavi/service.py`
Next to `force_restore` (line 292), add thin delegations:
```python
def list_backups(self, game_name: str) -> dict[str, object]: ...      # -> self._lifecycle.list_backups
def restore_backup_version(self, game_name: str, backup_id: str) -> dict[str, object]: ...
```

### B6. RPC endpoints — `main.py` (`Plugin`)
Next to `force_restore` (line 293), same `_call` pattern:
```python
async def list_backups(self, game_name: str) -> dict[str, Any]:
    return await self._call("list_backups", lambda: self._service().list_backups(game_name))

async def restore_backup_version(self, game_name: str, backup_id: str) -> dict[str, Any]:
    return await self._call("restore_backup_version",
        lambda: self._service().restore_backup_version(game_name, backup_id))
```

### B7. Backend tests (write FIRST, in `tests/`)
New file `tests/test_backup_browser.py` (follow mock patterns from `tests/test_ludusavi.py`, `tests/test_lifecycle.py`, `tests/test_main_rpc.py`):
1. Adapter `list_backups`: fake pyludusavi client returning a canned `backups_list` payload (incl. multi-snapshot, `locked`, `comment: None`); assert response shape, newest-first sort, missing-game → empty list.
2. `_backup_disk_stats`: build real layouts under `tmp_path` — a directory snapshot, a zip snapshot (use `zipfile` to create), the `"."` simple layout with a sibling `backup-*` dir and `mapping.yaml` excluded, and a nonexistent target → `(None, None)`.
3. Adapter `restore_backup`: assert the fake client's `restore` was called with `games=[game]`, `backup_id=<id>`, `force=True`.
4. Lifecycle `restore_backup_version`: unmatched game → skip; no backup → skip; invalid `backup_id` (empty, `../x`) → rejected; success records `point_in_time_restore` history and refreshes registry; failure records `failed` history and re-raises; lock contention raises `OperationLockedError`.
5. Lifecycle `list_backups`: runs via `run_locked`, no history written.
6. RPC: `Plugin.list_backups` / `Plugin.restore_backup_version` delegate to the service (pattern of `tests/test_main_rpc.py:75`).

---

## Part C — Frontend Implementation

### C1. Types — `src/types/index.ts`
```ts
export type BackupSnapshot = {
  id: string; when: string; locked: boolean;
  os: string | null; comment: string | null;
  size_bytes: number | null; file_count: number | null;
};
export type BackupListResult = {
  game: string; backup_path: string | null;
  total_size_bytes: number | null; backups: BackupSnapshot[];
};
```
Skip results reuse the existing `RpcResult`/`OperationResult` handling (a skip returns `{status: "skipped", ...}` like force ops).

### C2. RPC wrappers — `src/api/ludusaviRpc.ts`
```ts
export const listBackupsCall = callable<[gameName: string], RpcResult<BackupListResult>>("list_backups");
export const restoreBackupVersionCall = callable<[gameName: string, backupId: string], RpcResult<OperationResult>>("restore_backup_version");
```

### C3. Size formatter — new `src/formatting/fileSize.ts` (+ vitest `fileSize.test.ts`, written first)
`formatFileSize(bytes: number | null | undefined): string` → `"—"` for null/undefined, else B/KB/MB/GB with one decimal (e.g. `1.4 MB`). Reuse `formatDateMDY`/`formatTime12h` from `src/formatting/dateTime.ts` for dates — do not write new date code.

### C4. Modal — new `src/components/modals/BackupBrowserModal.tsx`
Follow `src/components/modals/ConflictResolutionModal.tsx` (uses `ConfirmModal` from `@decky/ui`) and the `showModal(<LudusaviLogModal …/>)` pattern (`src/components/qam/LudusaviContent.tsx:570`).

- Props: `{ gameName: string; closeModal?: () => void; onRestoreSnapshot: (backupId: string, whenLabel: string) => void }`.
- On mount: `listBackupsCall(gameName)`; states: loading spinner / error text (incl. `RpcStatus` via existing `isRpcStatus` helper) / empty ("No backups found") / list.
- Header: game name, snapshot count, `Total: {formatFileSize(total_size_bytes)}`.
- Each row (`Focusable`/`ButtonItem`, gamepad-navigable): date+time (`formatDateMDY`/`formatTime12h`), `file_count` files, `formatFileSize(size_bytes)`, a lock indicator when `locked`, comment if present.
- Activating a row closes the browser and opens a nested `ConfirmModal`: title "Restore Backup", body "Restore {gameName} to the backup from {date time}? Current save data will be overwritten.", `onOK` → `onRestoreSnapshot(id, whenLabel)`, `onCancel` → reopen nothing (just dismiss).

### C5. Wiring — `src/components/qam/LudusaviContent.tsx` and `GameSettingsSection.tsx`
- `GameSettingsSection.tsx`: add prop `onOpenBackups: () => void`; render a third `SpinnerButton` row "Backups" after Force Restore, `disabled={isBusy || selectedStatus?.status !== "has_backup"}` (same gate as Force Restore).
- `LudusaviContent.tsx`:
  - `onOpenBackups={() => showModal(<BackupBrowserModal gameName={selectedGame} onRestoreSnapshot={runSnapshotRestore} />)}`.
  - `runSnapshotRestore(backupId, whenLabel)`: clone the `runForceOperation` flow (line 623) with label "Restore" — `setBusyLabel("Restore running")`, start/success/failure `notify(...)` toasts (mention the snapshot date in the body), call `restoreBackupVersionCall(selectedGame, backupId)`, then the same post-op refresh: `refreshGamesCall(false)`, `getOperationStatus()`, `getRecentLogs()`, `applyRefreshResult`, `setBusyLabel(null)` in `finally`. Reuse `summarizeOperationResult` for the result toast. (Extracting a shared helper from `runForceOperation` is preferred over copy-paste if the refactor stays small.)

### C6. Frontend tests (vitest, written first where logic is testable)
- `src/formatting/fileSize.test.ts` — formatter cases incl. null.
- A pure view-model helper test if any non-trivial transformation is added (e.g., snapshot row label builder). Do not attempt full React component rendering tests; the repo has no component-render test setup.

---

## Part D — Quality Gates (all must pass before the `_finished` marker)

```
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
pnpm run test          # vitest + tsc typecheck
```
Pre-commit hook also runs `scripts/check_tdd.sh` and frontend supply-chain checks — commit early/atomically so failures stay cheap. Update `README.md` (feature list/usage) since user-facing behavior changed.

## Verification

1. All new backend tests in `tests/test_backup_browser.py` fail before implementation (RED) and pass after (GREEN).
2. Full suite green via the commands above.
3. Manual sanity (no ludusavi binary on this dev box, so this is mock-level): RPC layer returns the documented JSON shapes; `pnpm run build` (rollup) succeeds so the plugin bundle compiles.
4. After dev release is triggered, confirm the `release.yml` dispatch run started: `gh run list --workflow=release.yml --limit 1`.

## Commit sequence (suggested, Conventional Commits, atomic)

1. `docs(plans): add backup browser implementation plan`
2. `test(backend): add failing tests for backup listing and point-in-time restore`
3. `feat(backend): add list_backups and restore_backup_version endpoints`
4. `test(frontend): add file size formatter tests`
5. `feat(frontend): add backup browser modal with point-in-time restore`
6. `docs(readme): document backup browser feature`
7. (per review round) `fix(...)` / `docs(review): ...`
