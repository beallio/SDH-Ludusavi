# Update Integrity, Vendored-Pin Guard, and Versioning Fix

Date: 2026-06-12
Planner Model: claude-fable-5

Plan name (used for markers/review files): `update_integrity_and_versioning`

## Context

Three items: (1) writeup item 13 — artifact signing for the self-update chain, which the user decided to **defer with a decision record** (the writeup itself calls it long-term: the key only adds security if it lives outside CI, and store distribution moots it partially); (2) writeup item 14 — a test asserting the vendored `py_modules/pyludusavi/` matches the `pyproject.toml` pin so a pin bump without re-vendoring fails loudly; (3) the previously-noted **PEP-440 versioning break**: GitHub dev-release tags (`v0.3.0-dev.g<sha>`) are not PEP-440-parseable, and hatch-vcs derives the package version from `git describe`, so any machine that fetches those tags loses `uv run` project sync AND the pre-commit hook (observed 2026-06-12; worked around by deleting 40 local dev tags — they are still on origin and any fetch re-breaks it). Plus housekeeping: the merged `fix/update-lifecycle-resilience` branch and its `/tmp` worktree are left over from a finished session.

**Verified facts (use these, not assumptions):**
- Update verification chain (for the ADR): manifest SHA-256 extracted in `py_modules/sdh_ludusavi/updater.py` (`validate_prevalidated_candidate`, lines ~166–199), asset-name pinning (lines ~188–189), pre-install revalidation SHA-256 match (lines ~787–799). Plugin constants live in `py_modules/sdh_ludusavi/constants.py` (where a public key would go). Backend is stdlib-only (`hashlib`; sole dependency `pyludusavi>=0.2.3`).
- Vendored pin: `pyproject.toml` line ~19 declares `pyludusavi>=0.2.3`; `py_modules/pyludusavi-0.2.3.dist-info/METADATA` line 3 says `Version: 0.2.3`; exactly one dist-info dir exists. The B2 local patch marker EXISTS at `py_modules/pyludusavi/discovery.py` lines 7–10: comment starting `# SDH-Ludusavi local patch` plus `_VERIFY_TIMEOUT_SECONDS = 15.0` (used at lines ~93 and ~102).
- Versioning: `[build-system] requires = ["hatchling", "hatch-vcs"]`; `[tool.hatch.version] source = "vcs"` with NO further options. The backend package is `vcs_versioning`; its default describe command is `git describe --dirty --tags --long --abbrev=40 --match "*[0-9]*"` (in `vcs_versioning/_backends/_git.py`), which matches the dev tags; `packaging.version.Version` then raises `InvalidVersion` on `0.3.0-dev.g86c69a5`. Stable tags are pure `vX.Y.Z` (validated in `.github/workflows/release.yml`); dev tags are created by `dev-release.yml` line ~150 as `v${BASE}-dev.g${SHORT_SHA}`. The runtime plugin version (`py_modules/sdh_ludusavi/_version.py` `resolve_version`) reads `plugin.json`/`package.json` and does NOT depend on the Python package version — so this fix only affects the dev toolchain, not shipped artifacts.
- **Glob subtlety**: `git describe --match` uses full-name fnmatch, but `v[0-9]*.[0-9]*.[0-9]*` still matches `v0.3.0-dev.g86c69a5` (the trailing `*` swallows the suffix). The fix MUST include `--exclude "*-dev*"`.

## Execution Protocol

- **Skill**: invoke the `implementer` skill and follow its workflow.
- **Branch**: `git checkout dev && git pull && git checkout -b chore/update-integrity-and-versioning`. Never commit to `dev`/`main` directly.
- **Baseline**: run the full gates on the fresh branch first and confirm green.
- **Quality gates (before EVERY commit)**:
  1. `pnpm run test:unit` && `pnpm run typecheck` (frontend untouched, but run them)
  2. `./run.sh uv run ruff check . --fix` && `./run.sh uv run ruff format .`
  3. `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  4. `./run.sh uv run pytest`
- Do not modify: `tests/test_protocol.py`, `tests/test_issue_8_ui_error.py`, any frontend source, `py_modules/pyludusavi/` (the vendored library itself), the workflows' tag formats.
- CLAUDE.md §9 TDD exemptions apply to commits 2, 5, 6 (housekeeping/docs); commits 3–4 include explicit red/green demonstrations described below.

---

## Commit-by-commit sequence

### Commit 1 — `docs(plans): add update integrity and versioning plan`
Copy this plan to `docs/plans/update_integrity_and_versioning.md`. Gates; commit.

### Commit 2 — `chore: remove merged update-lifecycle worktree and branch`
The branch `fix/update-lifecycle-resilience` is fully merged into dev (verify: `git merge-base --is-ancestor fix/update-lifecycle-resilience dev` exits 0 — if it does NOT, STOP and flag in the session log instead of deleting).
1. Verify the worktree is clean: `git -C /tmp/sdh_ludusavi-update-lifecycle status --porcelain` must be EMPTY. If not empty, STOP — do not remove; note it for review.
2. `git worktree remove /tmp/sdh_ludusavi-update-lifecycle` (no --force needed when clean).
3. `git branch -d fix/update-lifecycle-resilience` (lowercase -d only — it must succeed because the branch is merged; never use -D).
4. Nothing to commit in the repo for this step UNLESS `git worktree prune` changes tracked state (it does not) — so this "commit" may be a no-op; if there is genuinely nothing to commit, skip the commit and note it in the session log. Gates anyway.

### Commit 3 — `build(version): restrict vcs version discovery to stable release tags`
Fixes: fetched `v*-dev.g<sha>` tags break `uv run` project sync and the pre-commit hook.

1. RED (do this BEFORE editing pyproject — the broken state also breaks the commit hook, so sequence carefully):
   - `git fetch --tags origin` (restores the dev tags locally — this is the real-world breaking state).
   - Confirm broken: `./run.sh uv run python -c "print('ok')"` must FAIL with a hatchling/vcs_versioning build error mentioning a `v0.3.0-dev.*` tag. Capture the error line for the session log.
2. VERIFY THE OPTION NAME before editing (CLAUDE.md §11 — no speculative config): read the installed backend's config source, e.g. `ls /tmp/sdh_ludusavi/.venv/lib/python3.12/site-packages/` then read `vcs_versioning/_config.py` and `vcs_versioning/_integration/` (or grep for how raw options map: `grep -rn "describe_command\|git_describe_command\|tag_regex" <site-packages>/vcs_versioning/ <site-packages>/hatch_vcs/`). Two candidate spellings, in order of preference:
   ```toml
   [tool.hatch.version]
   source = "vcs"
   raw-options = { git_describe_command = ["git", "describe", "--dirty", "--tags", "--long", "--abbrev=40", "--match", "v[0-9]*", "--exclude", "*-dev*"] }
   ```
   or the nested form if the flat key is rejected/ignored (the package docstrings mention `scm.git.describe_command` with the flat key deprecated-but-accepted). Use whichever the installed version actually honors — confirm by reading the source, then by the GREEN check.
   The `--exclude "*-dev*"` is MANDATORY (see glob subtlety in Context). Keep `--match "v[0-9]*"` so only version-shaped tags are considered at all.
3. GREEN: with the dev tags still fetched, `./run.sh uv run python -c "print('ok')"` succeeds, and `./run.sh uv run python -c "import importlib.metadata as m; print(m.version('SDH-ludusavi'))"` prints a PEP-440 version derived from the nearest STABLE tag (expect something like `0.2.6.dev<N>+g<sha>` relative to `v0.2.5`).
4. Regression guard: add `tests/test_version_config.py` (protocol-test style, see `tests/test_protocol.py`): parse `pyproject.toml` (use `tomllib`) and assert `tool.hatch.version` contains a describe command that includes BOTH `"--match"` and `"--exclude"`, and that `"*-dev*"` is the exclude value — so a future simplification that re-breaks tag handling fails loudly with a comment explaining why (dev-release tags are not PEP-440).
5. Full gates (they all go through `uv run`, which now works WITH the dev tags present — that is the point); commit.

### Commit 4 — `test(vendoring): assert vendored pyludusavi matches the pyproject pin`
New `tests/test_vendored_pyludusavi.py` (writeup item 14). This is a guard test (asserts current truths — passes immediately; TDD red-first is not applicable, but each assertion must be individually exercised via `pytest -v`):
1. **Exactly one dist-info**: `dirs = sorted(Path("py_modules").glob("pyludusavi-*.dist-info")); assert len(dirs) == 1`.
2. **Pin matches vendored version**: read `Version:` from `dirs[0]/"METADATA"` (line starting `Version: `); parse the pin from `pyproject.toml` via `tomllib` — find the `project.dependencies` entry starting with `pyludusavi`, extract the version literal with a regex like `r"pyludusavi\s*[><=~!]+=?\s*([0-9][0-9a-zA-Z.]*)"`; assert extracted pin version == METADATA version (today both `0.2.3`). Also assert the dist-info directory NAME embeds the same version (`pyludusavi-{version}.dist-info`).
3. **Local patch survives re-vendor** (writeup's cross-link): read `py_modules/pyludusavi/discovery.py` and assert BOTH the marker string `"SDH-Ludusavi local patch"` and the identifier `"_VERIFY_TIMEOUT_SECONDS"` are present, with a comment in the test explaining: a re-vendor that drops the local discovery timeout patch must fail this test until the patch is re-applied or upstreamed.
4. Note: `tests/test_protocol.py` (frozen — do not edit) already hardcodes `pyludusavi-0.2.3.dist-info` in a path; this new test intentionally duplicates nothing from it (protocol asserts existence; this asserts consistency).
Gates; commit.

### Commit 5 — `docs(specs): record artifact signing decision (deferred)`
New `docs/specs/2026-06-12_artifact_signing_decision.md` — an ADR-style record (writeup item 13, user decision: defer):
- **Status**: Deferred (decision recorded 2026-06-12).
- **Current chain** (with file references from Context): manifest SHA-256 (`updater.py` `validate_prevalidated_candidate`), asset-name pinning, pre-install revalidation (`revalidate()` SHA-256 match), hash handed to Decky's installer. Strong against tampered downloads; manifest and ZIP share one trust root (the GitHub account).
- **Proposal considered**: minisign/Ed25519 — embed public key in `py_modules/sdh_ludusavi/constants.py`, sign the manifest at release time (it contains the ZIP hash, so the artifact is transitively covered), verify `manifest.minisig` in the updater before trusting anything.
- **Why deferred (the honest costs)**: (a) the Decky runtime is stdlib-only Python with no Ed25519 primitive — a small pure-Python verifier would have to be vendored; (b) the key only adds security if it lives OUTSIDE CI — a signing key in GitHub Actions secrets collapses back to account-equals-trust-root, so releases would gain a manual offline signing step.
- **Revisit triggers**: distribution outside the Decky Store at scale; partially moot if shipping through the store (its own review/distribution integrity).
Gates; commit.

### Commit 6 — `docs: record session log for update integrity and versioning`
`docs/agent_conversations/2026-06-12_update_integrity_and_versioning.json` (date, objective, files modified, tests added, design decisions — including the verified raw-options spelling and the captured RED error line — results). Gates; commit.

---

## Verification checklist (after every commit; full pass at the end)
1. `./run.sh uv run pytest` — all green (with the dev tags fetched locally — do NOT delete them again; surviving them is the fix).
2. `./run.sh uv run ruff check . --fix && ./run.sh uv run ruff format .` — clean.
3. `./run.sh uv run ty check py_modules/sdh_ludusavi/` — clean.
4. `pnpm run test:unit && pnpm run typecheck` — clean.
5. `git tag -l 'v*-dev.*' | wc -l` is > 0 AND `./run.sh uv run python -c "print('ok')"` succeeds — proves the fix under breaking conditions.
6. `git worktree list` shows only the main working tree; `git branch` no longer lists `fix/update-lifecycle-resilience`.
7. `pytest tests/test_vendored_pyludusavi.py tests/test_version_config.py -v` — every assertion ran.
8. `git log --oneline dev..HEAD` → the commits above, conventional, atomic — ONE concern per commit (review note WILL flag bundling).

---

## Completion & Review Loop Protocol

**File-based signaling — exact names matter:**
- Agent → reviewer ("my side is complete"): write an EMPTY file at exactly
  `/tmp/sdh_ludusavi/update_integrity_and_versioning_finished`
  (`touch /tmp/sdh_ludusavi/update_integrity_and_versioning_finished`). Re-touch the same file after addressing each review round.
- Reviewer → agent ("my review is finished"): the reviewer writes notes INTO THE REPO at
  `docs/review/update_integrity_review_<n>.md` (n = 1, 2, ...). The appearance of a new file matching
  `docs/review/update_integrity_review_*.md` that you have not yet processed IS the signal that the review round is done.

**Loop:**
1. After the final commit and a full verification pass, touch the finished marker.
2. Poll `docs/review/` every ~60 seconds for an unprocessed `update_integrity_review_<n>.md` (track the highest n handled; the file is untracked when it appears — expected).
3. When a new note appears, read it:
   - **Contains findings**: address each finding on the working branch with TDD (failing test → fix → gates → atomic conventional commit). Append a short per-finding resolution section to the note file, `git add` it, commit as `docs(review): record update integrity review round <n>` (its own commit — do not bundle with the fixes). Re-touch the finished marker. Continue polling for round n+1.
   - **States the review passed** (contains "PASS"): proceed to the endgame.
4. **Endgame** (only after a PASS note):
   a. Commit the passing review note if not already committed (`docs(review): record passing review for update integrity and versioning`).
   b. `git checkout dev && git merge --no-ff chore/update-integrity-and-versioning`; run the full gate suite once on dev.
   c. `git branch -d chore/update-integrity-and-versioning` (delete the remote branch only if it was pushed — and do NOT push the working branch before review).
   d. `git push origin dev`.
   e. `./scripts/request_dev_release.sh 0.3.0` (defaults to HEAD of dev; requires authenticated `gh`). Note: the new dev tag this creates (`v0.3.0-dev.g<sha>`) is exactly the shape commit 3 makes survivable — after the release, run verification item 5 once more as the final proof.
