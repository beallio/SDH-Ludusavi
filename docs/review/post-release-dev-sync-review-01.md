# Review — post-release-dev-sync (round 01)

Branch reviewed: `feat/post-release-dev-sync`
Commit reviewed: `35cad19` (round-complete marker stamped at this SHA)
Plan reviewed against: `docs/plans/2026-06-20_post-release-dev-sync.md`

## Verdict

APPROVED. Guard B is implemented to spec, all hard constraints are satisfied, and the
release-time interpreter risks (which CI cannot catch, since the workflow YAML is not
executed by tests) were verified clean by the reviewer. Cleared to finalize.

## Gate status

All green at `35cad19` (`./run.sh bash scripts/quality_gates.sh check`): ruff, ty, pytest,
`pnpm run verify` (vitest 228 passed across 28 files, tsc clean).

## What was delivered

- **Task 1 — `scripts/version_guard.py`**: `next_patch_version(version) -> str` (reuses
  `parse_semver`, rejects non-stable input) plus a `next-patch` CLI subcommand. Red-first
  unit tests in `tests/test_version_guard.py` (`0.3.3`/`v0.3.3` → `0.3.4`, `1.2.9` →
  `1.2.10`, `ValueError` on `-dev`/non-semver).
- **Task 2 — `.github/workflows/release.yml` `post-release-dev-sync` job**:
  - Gated `needs: build-and-release` + `if: success() && startsWith(github.ref,
    'refs/tags/v')` — runs only after a successful stable release.
  - Job-level `permissions: { contents: write, pull-requests: write }` (publish job's
    permissions unchanged).
  - Computes `NEXT` via `python3 scripts/version_guard.py next-patch`; no-op guard skips
    when `dev` already contains `main` and declares `>= NEXT`.
  - Creates/force-updates the deterministic `auto/post-release-sync` branch, attempts a
    non-interactive `main`→`dev` merge, **aborts and flags conflicts in the PR body** rather
    than forcing, bumps to `NEXT` via `set_release_version.py`, and opens/updates a single
    PR into `dev` (idempotent via `gh pr list` → edit-or-create).
  - **Never pushes to `dev` and never auto-merges.**
- Workflow-content tests in `tests/test_release_workflows.py` assert the job exists, is
  gated, declares `pull-requests: write`, uses `next-patch`, opens a PR (`gh pr create` /
  action) into `--base dev`, and that `git push origin dev` is **absent**.

## Constraints verified

- **PR, never auto-merge / no push to `dev`** — confirmed in the YAML and asserted by test.
- **Idempotent** — deterministic branch + edit-or-create PR.
- **No-op when synced** — `SKIP_SYNC` guard.
- **`python3`, not bare `python`** — consistent with the Guard A fix.
- **Release-time interpreter safety (verified manually, since gates don't run the YAML):**
  `scripts/set_release_version.py` is stdlib-only (`argparse, json, re, sys, pathlib`), so
  the bare-`python3` bump step is safe; and `from scripts.version_guard import ...` imports
  under bare `python3` from the repo root (namespace package) — confirmed by running it.
- Guard A (`request_dev_release.sh` strict-ahead) and Guard C
  (`test_version_config.py` / `is_version_behind_stable`) and the publish step are untouched.

## Minor notes (non-blocking, no action required)

- The compute step uses an inline `python3 -c "from scripts.version_guard import
  parse_semver ..."`; it works (verified) but could equivalently use the `next-patch`/
  comparison CLI. Not worth a round.
- If two stable releases happen before the sync PR is merged, the rolling
  `auto/post-release-sync` branch/PR is force-updated to the latest — acceptable and arguably
  desirable (always syncs to the newest release).

## Finalization instructions

1. Confirm all review notes are committed and the tree is clean.
2. Run `scripts/orchestration/finalize post-release-dev-sync`.
3. Confirm `/tmp/sdh_ludusavi/post-release-dev-sync_finalized` exists.
4. Stop polling and exit. Finalize merges `feat/post-release-dev-sync` into `dev`, cleans up
   the branch, pushes `dev`, and requests a dev release (`dev` is `0.3.4`, ahead of stable
   `v0.3.3`, so Guard A/C are satisfied).

Deferred (cannot be exercised without a real stable release): the end-to-end behavior that
publishing `vX.Y.Z` opens a "sync dev" PR bumping `dev` to `X.Y.(Z+1)`. Observe on the next
real release.

STATUS: APPROVED
