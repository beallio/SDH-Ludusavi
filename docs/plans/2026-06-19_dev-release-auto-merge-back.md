# Scoping: Auto Merge-Back After Stable Release (Guard B)

Status: **SCOPING ONLY — not scheduled for implementation.** This is the separate follow-up
to the `dev-release-version-drift-guards` work (Guards A + C). A and C *detect* version
drift; B *prevents* it. Do not implement B until it is promoted to a full plan with its own
orchestration contract.

## Problem

A stable release bumps the version only on `main` (`chore(release): vX.Y.Z`). Nothing syncs
that back to `dev`, so `dev` drifts behind and emits dev prereleases on a stale base. This
actually happened: `v0.3.2` shipped on `main`, `dev` stayed at `0.3.1`, and finalize
produced `v0.3.1-dev.gSHA` (below the stable). Guards A + C catch the drift; B removes it.

## Intended outcome

After a stable release publishes, the version bump and release state are propagated back to
`dev` and `dev` is moved to the next unreleased dev base automatically — so a stale dev base
can never occur in normal operation.

## Proposed approach (to be validated when promoted)

- Add a post-publish job to `.github/workflows/release.yml` (or a dedicated workflow keyed
  on stable release/tag publish) that:
  1. checks out `dev`;
  2. merges `main` (the released commit) into `dev`;
  3. bumps `dev` to the next patch `-dev` base via `scripts/set_release_version.py`;
  4. **opens a pull request** rather than pushing/auto-merging directly.

## Key risks / decisions to resolve before implementing

- **Conflicts are expected.** The A+C work itself hit a real `tests/test_package_plugin.py`
  conflict (hardcoded version literals on `main` vs dynamic source-of-truth derivation on
  `dev`). Auto-merge would block on exactly this — so B must **open a PR for a human to
  resolve**, never auto-merge.
- **CI permissions:** needs a token allowed to push a branch and open a PR; interaction with
  branch protection on `dev`.
- **Next-version policy:** confirm "next patch" is the right default bump, and how it
  interacts with minor/major stable releases.
- **Idempotency:** re-running must not open duplicate PRs.

## Relationship to Guards A + C

Once B is in place and working, A and C become rarely-fired safety nets (defense in depth).
A and C should ship first (they are cheap and catch drift immediately); B follows.

## Status Update: Superseded

The CI/PR approach for Guard B outlined above was superseded by the local script `scripts/post_release_sync.sh`, because this project uses a local release workflow. The local script handles the `dev` version bump and sync immediately after a stable release is cut locally, avoiding the need for CI PR permissions.
