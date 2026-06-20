# Review — replace-guardb-local-sync (round 01)

Branch reviewed: `feat/replace-guardb-local-sync`
Commit reviewed: `8c07265` (round-complete marker stamped at this SHA)
Plan reviewed against: `docs/plans/2026-06-20_replace-guardb-local-sync.md`

## Verdict

APPROVED. The CI Guard B job is cleanly removed and replaced with a focused local
`scripts/post_release_sync.sh`; Guards A + C are untouched; gates green. Two non-blocking
observations noted below. Cleared to finalize.

## Gate status

All green at `8c07265` (`./run.sh bash scripts/quality_gates.sh check`): ruff, ty, pytest,
`pnpm run verify` (vitest 228 passed across 28 files, tsc clean).

## What was delivered (atomic commits)

- `665ac66` — removed the `post-release-dev-sync` job from `release.yml` (the
  `build-and-release` job and the Publish step are untouched) and deleted the now-obsolete
  `test_post_release_dev_sync_job_content`.
- `6aa26af` — added `scripts/post_release_sync.sh` (executable): resolves the released tag
  (arg or highest stable tag), computes next patch via `version_guard.py next-patch`,
  requires a clean tree, checks out/pulls `dev`, merges `main` only if `dev` lacks it,
  no-ops when already synced, bumps `dev` via `set_release_version.py`, runs quality gates
  before committing, commits, and pushes `dev`. Uses `./run.sh uv run` (correct for a local
  script, unlike the CI job which needed bare `python3`).
- `8c07265` — docs: `DEVELOPMENT.md` release section documents running the script; the Guard
  B scoping doc records the CI→local swap.
- `next_patch_version()` + its unit tests retained.

## Constraints verified

- Removal is surgical: `build-and-release` job + Publish step intact; no other workflow
  changes.
- Script scope is correct: behavioral tests cover the dirty-tree abort and the
  merge-conflict abort; content tests assert it is executable, uses `next-patch`, and
  contains no `git push origin main` and no tag creation.
- Guard A (`request_dev_release.sh`) and Guard C (`test_version_config.py` /
  `is_version_behind_stable`) untouched; no release triggered.

## Non-blocking observations (no action required)

1. **No-op guard requires both `contains-main` AND `version >= next`.** Right after a normal
   release (release direction is `dev`->`main`), `main`'s merge commit is not yet in `dev`,
   so `contains-main` is false and the script performs a content-empty merge-back of `main`
   into `dev` before the (already-satisfied) version bump. This is standard "merge the release
   back to dev" practice and is idempotent (a second run no-ops), so it is correct behavior —
   but it means the plan's verification note ("would no-op on the current state") is
   optimistic; the first run will actually create a merge-back commit. Flagging so the
   expectation is accurate, not as a defect.
2. `git fetch origin main:main || true` followed by `origin/main` comparisons relies on the
   fetch also refreshing the `origin/main` remote-tracking ref (it does in current Git). A
   future hardening could fetch `origin` plainly and compare against `origin/main` explicitly.

## Finalization instructions

1. Confirm all review notes are committed and the tree is clean.
2. Run `scripts/orchestration/finalize replace-guardb-local-sync`.
3. Confirm `/tmp/sdh_ludusavi/replace-guardb-local-sync_finalized` exists.
4. Stop polling and exit. Finalize merges `feat/replace-guardb-local-sync` into `dev`, cleans
   up the branch, pushes `dev`, and requests a dev release (`dev` is `0.3.4`, ahead of stable
   `v0.3.3`).

Deferred: real end-to-end use is observed the next time a stable release is cut locally — run
`scripts/post_release_sync.sh` right after.

STATUS: APPROVED
