# Repo Hygiene + Small Correctness Fixes

Date: 2026-06-11
Planner Model: claude-fable-5
Plan name (used for markers/review files): `repo_hygiene_and_correctness`

## Execution Skill

Execute this plan with the `implementer` skill (environment discovery → branch → strict TDD → atomic conventional commits → session log).

## Problem Definition

Six independent, small items: three hygiene chores (orphaned codegen script at repo root, 196 committed agent-session JSON logs bloating the working tree, coverage collected but never enforced) and three correctness fixes (naive local-time history timestamps, session-lifetime gateway caches that go stale if Ludusavi is installed/moved mid-session, and a hardcoded `XDG_RUNTIME_DIR=/run/user/1000` that is wrong for any non-stock user).

**Verified facts (use these, not assumptions):**
- `expand_tests.py` (repo root) is orphaned — zero references in CI, scripts/, docs, hooks; its generated output `src/utils/steamRuntime.test.ts` is already committed. Decision: delete.
- `docs/agent_conversations/` is **784K / 196 files** of structured JSON summaries. Packaging already excludes it implicitly (`scripts/package_plugin.py` allowlist). `tests/test_protocol.py` does NOT assert the directory exists, but the agent protocol (§15) requires future session logs there — the directory must remain, with a README pointer. Decision: archive existing files to orphan branch `docs-archive`.
- Coverage: `pyproject.toml` `[tool.pytest.ini_options]` addopts has `--cov=py_modules/sdh_ludusavi --cov-report=term`; NO `--cov-fail-under` anywhere; CI runs `./run.sh uv run pytest`. Current measured total: **85%**. Floor: **83**.
- History timestamps: `py_modules/sdh_ludusavi/history.py:59` uses `datetime.now().isoformat(timespec="microseconds")` (naive local). Sorting at `history.py:152` is a **lexicographic string sort** (`key=lambda x: str(x["timestamp"])`) — switching new entries to aware UTC (`+00:00` suffix) while old naive entries persist makes string sorting unreliable; the sort key must become a tolerant datetime parse. The recency/restore-direction logic in `py_modules/sdh_ludusavi/lifecycle.py:18-52` (`_parse_iso_timestamp`, `_timestamp_direction`) already tolerates naive/aware mixing (naive assumed UTC) and reads Ludusavi metadata, not history — it is unaffected and its parser pattern should be mirrored.
- Gateway: `py_modules/sdh_ludusavi/gateway.py` `LudusaviGateway` caches `_adapter` (lazy, under `_adapter_lock`), `_versions`, `_ludusavi_command`, `_diagnostics_logged`; no invalidation exists. Adapter-level caches (`_cached_config_path`, `_cached_versions`, `_cached_diagnostics`, aliases) live on the adapter instance and vanish when it is dropped. `refresh_games(force)` is in `py_modules/sdh_ludusavi/registry.py` (~line 151, "Forcing refresh_games" debug log); the registry reaches the gateway via `self._gateway.get_adapter()` (lines 212/237).
- `_ludusavi_env` at `py_modules/sdh_ludusavi/ludusavi.py:28-42` hardcodes `"/run/user/1000"` (line 37) when `XDG_RUNTIME_DIR` is unset. `tests/test_ludusavi.py:55-65` asserts that exact value — it is the natural red test to update. Linux-only plugin; `os.getuid()` is always available.
- `dev` already contains the merged syncthing refactor; branch off current `dev`.

## Execution Protocol

- **Branch**: `git checkout dev && git pull && git checkout -b chore/repo-hygiene-and-correctness`. Never commit to `dev`/`main` directly during development.
- **Baseline**: run the full gates on the fresh branch first and confirm green.
- **Quality gates (before EVERY commit)**:
  1. `pnpm run test:unit` && `pnpm run typecheck` (frontend untouched by this plan, but run them)
  2. `./run.sh uv run ruff check . --fix` && `./run.sh uv run ruff format .`
  3. `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  4. `./run.sh uv run pytest`
- Strict TDD for behavior-changing code (commits 4–6); chores/config (commits 2, 3, 7) are exempt per protocol §9 but still gate-checked.
- Do not modify: `tests/test_protocol.py`, `tests/test_issue_8_ui_error.py`, any frontend source. Existing history/recency tests (`tests/test_recency_direction.py`, `tests/test_history*.py`) must stay green unmodified except where a step explicitly says to update one.

## Architecture Overview

All changes are additive or localized: a deleted script, an orphan archive branch + README pointer, one pytest addopts flag, one timestamp call + tolerant sort key in `history.py`, one `invalidate()` method on `LudusaviGateway` plus a one-line call in `registry.refresh_games(force=True)`, and one f-string in `_ludusavi_env`. No public interface changes other than the new `LudusaviGateway.invalidate()`.

## Commit-by-commit sequence

### Commit 1 — `docs(plans): add repo hygiene and correctness plan`
This file. Gates; commit.

### Commit 2 — `chore: remove one-shot expand_tests codegen script`
`git rm expand_tests.py`. Gates (vitest confirms `src/utils/steamRuntime.test.ts` still passes); commit.

### Commit 3 — `chore(docs): archive agent conversation logs to orphan branch`
Goal: existing 196 files move to orphan branch `docs-archive`; the directory stays in the working tree with a README pointer for future session logs.

Follow EXACTLY this recipe (it never leaves the main working tree in a dangerous state — do NOT use `git checkout --orphan` in the main working tree, and NEVER run `git clean`):

1. `SRC_SHA=$(git rev-parse --short HEAD)`
2. `git worktree add --detach /tmp/sdh_ludusavi/archive_wt HEAD`
3. In the worktree (`cd /tmp/sdh_ludusavi/archive_wt`):
   - `git checkout --orphan docs-archive`
   - `git rm -rf --cached .` (worktree files become untracked — expected; it is a disposable worktree)
   - `git add docs/agent_conversations`
   - Write `ARCHIVE_README.md` (one paragraph: this orphan branch snapshots `docs/agent_conversations/` from `dev@${SRC_SHA}` on 2026-06-11, kept out of the main working tree for hygiene); `git add ARCHIVE_README.md`
   - `git commit -m "docs: archive agent conversation session logs (snapshot from ${SRC_SHA})"`
4. `cd /home/beallio/Dropbox/Scripts/SDH-ludusavi && git worktree remove --force /tmp/sdh_ludusavi/archive_wt`
5. Verify: `git log --oneline docs-archive -1` and `git ls-tree --name-only docs-archive | head`
6. On the working branch: `git rm docs/agent_conversations/*` (all 196 tracked files).
7. Create `docs/agent_conversations/README.md`: "Historical session logs (196 files through 2026-06-11) are archived on the `docs-archive` orphan branch (`git show docs-archive:docs/agent_conversations/<file>` or check out the branch). New session logs continue to be added here per the agent protocol." `git add` it.
8. Gates; commit. Do NOT push `docs-archive` now — it is pushed in the endgame.

### Commit 4 — `fix(history): record timezone-aware UTC timestamps with tolerant ordering`
1. RED — add to `tests/test_history_fixes.py` (or a new `tests/test_history_utc_timestamps.py`):
   - `record_history` writes an aware UTC timestamp: record an entry, `datetime.fromisoformat(entry["timestamp"])` has `tzinfo` not None and `utcoffset() == timedelta(0)`.
   - Mixed-era sorting: seed history with a legacy naive entry (e.g. `"2026-06-10T12:00:00.000001"`) and a newer aware entry (`"2026-06-11T12:00:00.000001+00:00"`); the `last_operation`/latest-entry logic must pick the aware (newer) one and must not raise. Also include an unparseable-timestamp entry to confirm it is tolerated (inspect `_coerce_history_entry` behavior before asserting whether it is skipped or sorted last).
   - `./run.sh uv run pytest` — confirm the new tests FAIL.
2. GREEN — in `py_modules/sdh_ludusavi/history.py`:
   - Line 59: `datetime.now().isoformat(...)` → `datetime.now(timezone.utc).isoformat(timespec="microseconds")` (import `timezone`).
   - Line 152 sort: replace the string key with a tolerant parse key. Add a small module helper mirroring `lifecycle._parse_iso_timestamp` (`lifecycle.py:18-32` — naive parsed as UTC; unparseable → `None`); sort key maps `None` to `datetime.min.replace(tzinfo=timezone.utc)` so unparseable entries sort oldest. Do NOT import lifecycle into history (layering) — duplicate the ~12-line helper with a comment referencing lifecycle's version.
   - Do NOT migrate stored naive entries (legacy entries may misorder by up to the local UTC offset relative to new entries; accepted).
3. All existing history/recency tests must stay green unmodified (especially `tests/test_recency_direction.py::test_backup_differs_conflict_when_timestamps_mix_naive_and_aware` and the high-res sorting tests). Gates; commit.

### Commit 5 — `fix(gateway): add cache invalidation wired to forced refresh`
1. RED — add to `tests/test_gateway.py`:
   - `invalidate()` drops all gateway caches: with a counting fake adapter factory, call `get_adapter()`, `get_versions()`, `get_ludusavi_command()`; call `gateway.invalidate()`; call the getters again and assert the factory/discovery ran a second time (mock `find_ludusavi` like the existing discovery test at `tests/test_gateway.py:47`).
   - `invalidate()` on a fresh gateway does not raise.
   - In the registry/service tests: `refresh_games(force=True)` calls `gateway.invalidate()` exactly once; `refresh_games(force=False)` does not (stub/mock gateway).
   - Confirm FAIL (`AttributeError: invalidate`).
2. GREEN:
   - `py_modules/sdh_ludusavi/gateway.py` — add to `LudusaviGateway`:
     ```python
     def invalidate(self) -> None:
         """Drop the adapter and all session caches so the next call re-discovers Ludusavi."""
         with self._adapter_lock:
             self._adapter = None
             self._versions = None
             self._ludusavi_command = None
             self._diagnostics_logged = False
     ```
     Dropping `_adapter` discards all adapter-level caches with it; resetting `_diagnostics_logged` makes the new binary's diagnostics get logged once.
   - `py_modules/sdh_ludusavi/registry.py` — in `refresh_games`, when `force` is true, call `self._gateway.invalidate()` BEFORE running the refresh (verify the gateway attribute name; match the surrounding locking style — keep the call outside `_run_locked`'s critical section unless inspection shows the gateway is only touched under that lock).
3. Gates; commit.

### Commit 6 — `fix(env): derive XDG_RUNTIME_DIR from the current uid`
1. RED — update `tests/test_ludusavi.py:55-65` (`test_ludusavi_env_uses_flatpak_defaults_without_mutating_os_environ`): monkeypatch `os.getuid` to return `1234` and assert `env["XDG_RUNTIME_DIR"] == "/run/user/1234"`. Keep `test_ludusavi_env_preserves_existing_xdg_runtime_dir` unchanged. Run — FAILS.
2. GREEN — `py_modules/sdh_ludusavi/ludusavi.py:37`: `"/run/user/1000"` → `f"/run/user/{os.getuid()}"`.
3. Gates; commit.

### Commit 7 — `test(coverage): enforce coverage floor in pytest addopts`
Ordered last among code changes so the floor reflects the final state.
1. Measure: `./run.sh uv run pytest` → note the TOTAL percentage.
2. Sanity-check the mechanism: `./run.sh uv run pytest --cov-fail-under=99` must FAIL (the "red" demonstration).
3. Edit `pyproject.toml` `[tool.pytest.ini_options]`: `addopts = "--cov=py_modules/sdh_ludusavi --cov-report=term --cov-fail-under=<measured minus 2, rounded down — 83 if measurement is 85>"`.
4. `./run.sh uv run pytest` passes with the floor active. Gates; commit. Commit body: floor is a ratchet — raise deliberately, never lower casually.

### Commit 8 — `docs: record session log for repo hygiene and correctness fixes`
`docs/agent_conversations/2026-06-11_repo_hygiene_and_correctness.json` (date, objective, files modified, tests added, design decisions, results) — also proves the directory still works post-archive. Gates; commit.

## Dependency Requirements

No new dependencies. `pytest-cov` is already in use (addopts has `--cov`).

## Verification checklist (after every commit; full pass at the end)
1. `./run.sh uv run pytest` — all green; coverage floor active after commit 7.
2. `./run.sh uv run ruff check . --fix && ./run.sh uv run ruff format .` — clean.
3. `./run.sh uv run ty check py_modules/sdh_ludusavi/` — clean.
4. `pnpm run test:unit && pnpm run typecheck` — clean.
5. `ls expand_tests.py` → gone; `git ls-files docs/agent_conversations/` → only `README.md`; `git log docs-archive -1` → archive commit exists.
6. `grep -n "datetime.now()" py_modules/sdh_ludusavi/history.py` → no naive `datetime.now()` remains.
7. `grep -rn "run/user/1000" py_modules/sdh_ludusavi/` → no hits.
8. `git log --oneline dev..HEAD` → 8 conventional commits.

## Completion & Review Loop Protocol

**File-based signaling — exact names matter:**
- Agent → reviewer ("my side is complete"): write an EMPTY file at exactly
  `/tmp/sdh_ludusavi/repo_hygiene_and_correctness_finished`
  (`touch /tmp/sdh_ludusavi/repo_hygiene_and_correctness_finished`). Re-touch the same file after addressing each review round.
- Reviewer → agent ("my review is finished"): the reviewer writes notes INTO THE REPO at
  `docs/review/repo_hygiene_review_<n>.md` (n = 1, 2, ...). The appearance of a new file matching
  `docs/review/repo_hygiene_review_*.md` that you have not yet processed IS the signal that the review round is done.

**Loop:**
1. After commit 8 and a full verification pass, touch the finished marker.
2. Poll `docs/review/` every ~60 seconds for an unprocessed `repo_hygiene_review_<n>.md` (track the highest n handled; the files are untracked when they appear — expected).
3. When a new note appears, read it:
   - **Contains findings**: address each finding on the working branch with TDD (failing test → fix → gates → atomic conventional commit). Then commit the review note itself: append a short per-finding resolution section to the note file, `git add docs/review/repo_hygiene_review_<n>.md`, commit as `docs(review): record repo hygiene review round <n>`. Re-touch the finished marker. Continue polling for round n+1.
   - **States the review passed** (contains "PASS"): proceed to the endgame.
4. **Endgame** (only after a PASS note):
   a. Commit the passing review note if not already committed (`docs(review): record passing review for repo hygiene and correctness`).
   b. `git checkout dev && git merge --no-ff chore/repo-hygiene-and-correctness`; run the full gate suite once on dev.
   c. `git branch -d chore/repo-hygiene-and-correctness` (delete remote only if it was pushed).
   d. `git push origin dev` and `git push origin docs-archive` (the archive branch push is explicitly authorized by this plan).
   e. `./scripts/request_dev_release.sh 0.3.0` (matches the current `v0.3.0-dev.*` tag series; defaults to HEAD of dev; requires authenticated `gh`).
