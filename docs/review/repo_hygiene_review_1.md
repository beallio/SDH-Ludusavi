# Review 1 — repo_hygiene_and_correctness — FINDINGS (not passing yet)

Reviewed branch: `chore/repo-hygiene-and-correctness` at commit 479ec04.
Overall: good. All gates pass (518 pytest with the coverage floor active — 85.11% vs floor 83; 151 vitest; tsc, ruff, ty clean). Verified: `expand_tests.py` deleted; `docs-archive` orphan branch exists with all 196 archived files + `ARCHIVE_README.md`; working-tree `docs/agent_conversations/` holds only the README pointer and the new session log; history timestamps are aware UTC with a tolerant parse-based sort key and the prescribed mixed-era/unparseable tests; `gateway.invalidate()` is lock-guarded and wired to `refresh_games(force=True)` with factory-recall and registry tests; frozen files untouched; production gateway construction (`main.py` → no injected adapter) confirms invalidation creates a genuinely fresh adapter.

There is ONE must-fix finding, then two recorded notes that need no code change.

Fix the finding with TDD, run all quality gates, commit, append a resolution section to this file, commit this file (`docs(review): record repo hygiene review round 1`), then re-touch `/tmp/sdh_ludusavi/repo_hygiene_and_correctness_finished`.

Gates reminder:
`pnpm run test:unit && pnpm run typecheck && ./run.sh uv run ruff check . --fix && ./run.sh uv run ruff format . && ./run.sh uv run ty check py_modules/sdh_ludusavi/ && ./run.sh uv run pytest`

---

## Finding 1 (MUST FIX — regression risk): XDG_RUNTIME_DIR must fall back when `/run/user/{uid}` does not exist

**File:** `py_modules/sdh_ludusavi/ludusavi.py`, `_ludusavi_env()`, line ~37 (currently `env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"`).

**Problem:** Decky Loader has historically run plugin backends as root (and could again if a `root` flag is ever added to plugin.json). Under root, `os.getuid()` is `0` and `/run/user/0` does not exist on SteamOS — pointing the Ludusavi/Flatpak subprocess at a nonexistent runtime dir. The old hardcoded `/run/user/1000` was accidentally correct in that scenario (it pointed at the deck user's session). The uid-derived value is only safe when the directory actually exists.

**Required behavior (ordered fallbacks):**
1. If `XDG_RUNTIME_DIR` is already set in `os.environ`: keep it (current behavior, unchanged).
2. Else if `/run/user/{os.getuid()}` exists as a directory: use it.
3. Else: use `/run/user/1000`.

**Fix (TDD — write the failing tests FIRST):**

1. RED — in `tests/test_ludusavi.py`:
   - UPDATE the existing `test_ludusavi_env_uses_flatpak_defaults_without_mutating_os_environ` (it currently patches `os.getuid` → 1001 and expects `/run/user/1001`, but `/run/user/1001` does not exist on the test machine, so under the new logic the expectation changes). Make it patch BOTH `os.getuid` → `1001` AND `os.path.isdir` → `True` (patch `os.path.isdir` via `unittest.mock.patch("os.path.isdir", return_value=True)` — patch where it is looked up; `_ludusavi_env` should call `os.path.isdir`), and keep asserting `env["XDG_RUNTIME_DIR"] == "/run/user/1001"`.
   - ADD `test_ludusavi_env_falls_back_when_uid_runtime_dir_missing`: monkeypatch-delete `XDG_RUNTIME_DIR`, patch `os.getuid` → `0` and `os.path.isdir` → `False`; assert `env["XDG_RUNTIME_DIR"] == "/run/user/1000"`.
   - Keep `test_ludusavi_env_preserves_existing_xdg_runtime_dir` unchanged.
   - Run `./run.sh uv run pytest tests/test_ludusavi.py` — the new test must FAIL (current code returns `/run/user/0`).
2. GREEN — implement in `_ludusavi_env()`:
   ```python
   if "XDG_RUNTIME_DIR" not in os.environ:
       candidate = f"/run/user/{os.getuid()}"
       # Decky may run the backend as root; /run/user/0 does not exist on
       # SteamOS, so fall back to the stock deck user's runtime dir.
       env["XDG_RUNTIME_DIR"] = candidate if os.path.isdir(candidate) else "/run/user/1000"
   else:
       env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
   ```
3. Full gates; commit as `fix(env): fall back to /run/user/1000 when uid runtime dir is missing`.

---

## Note A (recorded, NO action required): commit d7d25aa bundles three plan commits

`d7d25aa fix(service): clear gateway cache during forced refresh` contains plan commits 5, 6 AND 7 (gateway invalidation, the XDG env change, and the pyproject coverage floor), and its message describes only the first. This violates the atomic-commit policy and the plan's 8-commit sequence. Because the branch is already pushed to origin, rewriting history would require a force-push, which is prohibited — so this stands as a process note. Going forward: one coherent change per commit, and never push the working branch before review unless asked.

## Note B (informational, NO action required): injected-adapter gateways survive `invalidate()` with the same instance

The constructor change (`if adapter is not None and adapter_factory is None: self._adapter_factory = lambda: adapter`) means a gateway constructed with a direct adapter instance and no factory will get the SAME adapter back after `invalidate()` — its adapter-level caches (config path, versions, aliases) are not dropped. Only tests construct gateways this way; production (`main.py` → `SDHLudusaviService(settings_store=..., cache_path=...)`) uses the default factory, so real invalidation is complete. Optionally add one docstring line on `invalidate()` noting this; no behavior change required.

---

## After fixing

1. Run the full gate suite plus `pnpm run build`.
2. Commit the fix (conventional commit as above).
3. Append a "## Resolutions" section to THIS file describing the fix, `git add docs/review/repo_hygiene_review_1.md`, commit as `docs(review): record repo hygiene review round 1`.
4. Re-touch `/tmp/sdh_ludusavi/repo_hygiene_and_correctness_finished` to request re-review.

## Resolutions

- **Finding 1**: Updated `tests/test_ludusavi.py` to mock `os.path.isdir` and test both branches of the fallback. Updated `_ludusavi_env` in `py_modules/sdh_ludusavi/ludusavi.py` to fall back to `/run/user/1000` if the directory computed from `os.getuid()` does not exist on disk.
