# Archive Historical Documentation Through June 11

## Problem Definition

The active `dev` tree contains hundreds of completed implementation plans, review
artifacts, and session logs. These historical records are useful for audit and recovery,
but keeping all of them in the active documentation directories makes current work
harder to find.

The repository already has a `docs-archive` orphan branch containing 196 historical
session logs. Extend that branch with historical plans, reviews, and the remaining
June 11 session log, then remove the verified copies from the active tree.

## Architecture Overview

- Source commit: `29ca44bc79e9c8e66d840491aadef5b560647a79`.
- Working branch: `docs/archive-historical-docs`, created from `dev`.
- Archive branch: the existing `docs-archive` orphan branch.
- Temporary archive worktree: `/tmp/sdh_ludusavi/docs_archive_wt`.
- Cutoff: a tracked file's latest commit date is on or before `2026-06-11`.
- Included roots: `docs/plans/`, `docs/review/`, and
  `docs/agent_conversations/`.
- Archive paths remain unchanged so historical references continue to identify the
  original repository locations.

The candidate manifest is generated from the pinned source commit. Each entry records
the source path and Git blob object ID. The archive commit is accepted only when every
archived path resolves to the same blob object ID.

## Core Data Structures

The archive manifest is a sorted text file with one entry per archived path:

```text
<blob-object-id> <path>
```

Expected candidate set before execution:

- 186 plans
- 33 review artifacts
- 1 session log
- 220 files total
- 1,284,057 source bytes

The following files are excluded from the date-based archive:

- `docs/agent_conversations/README.md`
- `docs/plans/cloud_sync_conflict_resolution_flow.html`
- `docs/plans/repo_hygiene_and_correctness.md`
- `docs/plans/update_lifecycle_resilience.md`

The conflict-flow HTML is read directly by the test suite. The two retained plans are
referenced by post-cutoff review or session records that remain active.

All `docs/specs/`, `docs/archive/`, and post-cutoff files remain in the active tree.

## Public Interfaces

No runtime API, RPC, TypeScript interface, package format, dependency, or user-facing
behavior changes.

Documentation retrieval gains these stable interfaces:

- `docs/ARCHIVE.md` describes how to inspect historical files.
- `docs-archive:ARCHIVE_MANIFEST.txt` lists archived paths and source blob IDs.
- `docs-archive:ARCHIVE_README.md` records the archive snapshots and source commits.

## Dependency Requirements

No dependency changes.

The workflow uses Git worktrees and standard Git object inspection. Project commands
continue to run through `./run.sh`, with caches under `/tmp/sdh_ludusavi`.

## Implementation Plan

1. Revalidate that the working branch still descends from the pinned source commit and
   has no unrelated changes.
2. Generate the candidate manifest from the pinned source commit using the cutoff and
   exclusions above. Abort if the expected count or byte total differs.
3. Add `/tmp/sdh_ludusavi/docs_archive_wt` for the existing `docs-archive` branch.
4. Restore each manifest path from the pinned source commit into the archive worktree.
5. Write `ARCHIVE_MANIFEST.txt`, update `ARCHIVE_README.md`, and verify every archive
   blob matches the source blob before committing the archive snapshot.
6. Remove the temporary worktree and prune stale worktree metadata. The
   `docs-archive` branch and its new commit remain.
7. Delete the manifest paths from the feature branch only after archive verification.
8. Add `docs/ARCHIVE.md`, update `docs/agent_conversations/README.md`, and add the
   required session log.
9. Run the full repository quality gates, commit the active-tree cleanup, and
   fast-forward local `dev`.
10. Do not push `dev` or `docs-archive`.

## Testing Strategy

This is documentation-only repository maintenance, so strict behavioral TDD does not
apply.

Validation must include:

1. Verify all manifest source blobs exist at the pinned source commit.
2. Verify every archived path has the same blob object ID before active deletion.
3. Verify `docs/plans/cloud_sync_conflict_resolution_flow.html` remains present.
4. Verify retained post-cutoff documentation references resolve.
5. Verify the expected active documentation count after adding this plan,
   `docs/ARCHIVE.md`, and the session log.
6. Run:

```text
./run.sh uv run ruff check .
./run.sh uv run ruff format --check .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
./run.sh bash scripts/check_tdd.sh
git diff --check
```

7. Run the repository pre-commit hook for active-tree commits.
8. Confirm the feature branch, updated `docs-archive`, and local `dev` are clean after
   integration, and confirm `/tmp/sdh_ludusavi/docs_archive_wt` no longer exists.
