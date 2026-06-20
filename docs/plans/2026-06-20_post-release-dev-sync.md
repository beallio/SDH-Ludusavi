# Plan: Post-Release Dev Sync (Guard B) (post-release-dev-sync)

## Context

This is **Guard B**, the prevention half of the dev-release version-drift work (Guards A + C
already shipped as detection: `scripts/version_guard.py`, `request_dev_release.sh`,
`dev-release.yml`, and `tests/test_version_config.py`). Background/scoping:
`docs/plans/2026-06-19_dev-release-auto-merge-back.md`.

**Problem:** when a stable release publishes, nothing propagates the released state and the
next-version bump back to `dev`. `dev` then drifts behind `main` and emits dev builds on a
stale base. This actually happened twice recently: (1) `v0.3.2` shipped on `main` but `dev`
stayed at `0.3.1`, producing a `v0.3.1-dev.*` build that sorted *below* stable; (2) after
`v0.3.3` shipped, `dev` had to be manually bumped to `0.3.4` to keep dev releases working.
Guards A + C only *detect* drift; this plan *prevents* it.

**Intended outcome:** after a stable release publishes, automation opens (or updates) a
pull request into `dev` that, when merged, leaves `dev` (a) containing the released `main`
state and (b) declaring the next patch version (`X.Y.(Z+1)`). A human merges the PR and
resolves any conflicts — automation must **never** push directly to `dev` or auto-merge.

**Hard design constraints (learned the hard way):**
- **PR, never auto-merge.** A `main`→`dev` merge can conflict (e.g. the
  `tests/test_package_plugin.py` literals-vs-derived conflict hit during the v0.3.3 work).
  CI must open a PR and let a human resolve conflicts at merge time — never force-merge or
  push to `dev`.
- **Idempotent.** Re-running for the same release must update the existing branch/PR, not
  create duplicates. Use a deterministic branch name (e.g. `auto/post-release-sync`).
- **No-op when already synced.** If `dev` is already ahead of the released version (next
  bump already present and `dev` not behind `main`), do nothing / don't open an empty PR.
- **Scope:** do NOT change the stable-release publish behavior, and do NOT alter Guard A
  (`request_dev_release.sh` strict-ahead) or Guard C (`test_version_config.py` not-behind).

Relevant files (verified):
- `.github/workflows/release.yml` — single job `build-and-release` on tag push
  (`refs/tags/v*`); top-level `permissions: contents: write`; the last meaningful step is
  "Publish Stable Release to GitHub" (`softprops/action-gh-release@v3`). Guard B hooks in
  after a successful publish.
- `scripts/version_guard.py` — already has `parse_semver`, `highest_stable_version`,
  `is_base_ahead_of_stable`, `is_version_behind_stable`, and a `check-base` CLI. Add the
  next-patch computation here.
- `scripts/set_release_version.py` — updates `package.json` + `plugin.json` versions.
- `tests/test_release_workflows.py` — asserts workflow YAML content by substring; home for
  the workflow-content tests. `tests/test_version_guard.py` — home for the pure unit tests.

**Slug used throughout this plan:** `post-release-dev-sync`

---

## Orchestration Contract

**Slug:** `post-release-dev-sync`

**Plan file:**

```text
docs/plans/2026-06-20_post-release-dev-sync.md
```

**Implementation branch:**

```text
feat/post-release-dev-sync
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/post-release-dev-sync_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/post-release-dev-sync_finalized
```

**Review notes:**

```text
docs/review/post-release-dev-sync-review-*.md
```

Each review note ends with exactly one status trailer:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

---

## Required Agent Protocol

1. Use the **implementer** skill.
2. Work from the repository root.
3. Branch from `dev`.
4. Commit this plan as the first commit on the implementation branch.
5. Follow TDD where behavior changes are testable.
6. Run quality gates before marking any round complete.
7. Do not write your own review.
8. Do not create files under `docs/review/`.
9. Do not delete files under `docs/review/`.
10. Review notes are durable audit records and must be committed.
11. Resolving a review note means:
    - implement the requested changes;
    - run quality gates;
    - commit the code/docs changes;
    - commit the review note itself if it is not already committed;
    - recreate the round-complete marker.
12. After finalization, stop polling and exit cleanly.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/post-release-dev-sync
```

Commit this plan first:

```bash
git add docs/plans/2026-06-20_post-release-dev-sync.md
git commit -m "docs(plan): add post-release-dev-sync implementation plan"
```

---

## Implementation Tasks

Strict TDD where testable. No new third-party Python deps. Use `./run.sh` for tooling.

### Task 1 — Pure next-patch helper (red-first unit tests)

Add to `scripts/version_guard.py`:
- `next_patch_version(version: str) -> str` — given `X.Y.Z` (accepts a leading `v`), returns
  `X.Y.(Z+1)` as a plain `X.Y.Z` string. Reuse `parse_semver`. Reject non-stable input.
- Extend the `__main__` CLI with a subcommand `next-patch <version>` that prints the result
  to stdout and exits 0 (non-zero + stderr on invalid input), so the workflow can call
  `python3 scripts/version_guard.py next-patch "$TAG"`.

Tests first in `tests/test_version_guard.py`: `next_patch_version("0.3.3") == "0.3.4"`,
`"v0.3.3" → "0.3.4"`, `"1.2.9" → "1.2.10"`, and `ValueError` on `"0.3.3-dev"` / non-semver.

### Task 2 — Post-release sync job in `release.yml` (workflow-content tests first)

Add a new job to `.github/workflows/release.yml`, e.g. `post-release-dev-sync`:
- `needs: build-and-release` and `if: success() && startsWith(github.ref, 'refs/tags/v')`
  so it runs only after a successful stable tag release.
- Job-level `permissions: { contents: write, pull-requests: write }` (the workflow's
  top-level `contents: write` may need broadening to include `pull-requests: write` — set
  it at the job level to keep the publish job's permissions unchanged).
- Steps:
  1. Checkout with full history (`fetch-depth: 0`) and fetch tags.
  2. Compute `NEXT=$(python3 scripts/version_guard.py next-patch "${TAG#v}")` from the
     release tag (use `python3`, not bare `python`, consistent with the Guard A fix — runs
     before any toolchain setup).
  3. Create/reset a deterministic branch (e.g. `auto/post-release-sync`) from `origin/dev`.
  4. Merge `origin/main` (the released commit) into that branch **non-interactively**
     (`-m`, `GIT_EDITOR=true`). If the merge conflicts, do **not** force it: abort the merge,
     and still open the PR from the branch carrying only the version bump (next step), with a
     PR body that clearly flags that a manual `main`→`dev` merge is also required and lists
     the conflicting paths. (A clean merge is the common case right after release, since
     `dev`→`main` was the release merge direction.)
  5. Bump the branch to `$NEXT` via `./run.sh uv run python scripts/set_release_version.py
     "$NEXT"` (or a direct edit if the toolchain isn't set up in this job — keep it simple),
     and commit `chore(release): bump dev to $NEXT after $TAG`.
  6. No-op guard: if, after fetching, `dev` already declares `>= $NEXT` and is not behind
     `main`, skip (don't push an empty branch or open a PR).
  7. Push the branch and open/update a PR into `dev` (use `gh pr create`/`gh pr edit` or
     `peter-evans/create-pull-request`-style behavior — but if you use a third-party action,
     pin it by major tag consistent with the repo's existing pins; otherwise prefer `gh`
     with `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}`). Idempotent: reuse the existing PR if one
     is already open for the branch.
  - Title: `chore(release): sync dev after <TAG>`; body explains it brings `dev` up to the
    released `main` and bumps to `$NEXT`, and notes any conflict that needs manual resolution.

Workflow-content tests first, in `tests/test_release_workflows.py` (extend the existing
file-content style): assert `release.yml` contains the `post-release-dev-sync` job gated on
`needs: build-and-release` and the tag condition, that it references
`version_guard.py next-patch`, `set_release_version.py`, opens a PR into `dev` (e.g. asserts
`gh pr create` / `--base dev` or the create-pull-request action), declares
`pull-requests: write`, and does **not** push directly to `dev` (assert no
`git push origin dev` / `HEAD:dev` in the job).

### Out of scope (do NOT do here)

- Do NOT auto-merge or push directly to `dev`; the PR is merged by a human.
- Do NOT modify the stable-release publish step, Guard A (`request_dev_release.sh`), or
  Guard C (`test_version_config.py` / `is_version_behind_stable`).
- Do NOT trigger any actual release or PR as part of implementation; only add the workflow +
  helper + tests.
- Do NOT delete the scoping doc `docs/plans/2026-06-19_dev-release-auto-merge-back.md`.

---

## Quality Gates

Run before marking any round complete:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

The round is not complete unless:

1. all requested implementation work is done;
2. all relevant tests pass;
3. build/typecheck gates pass;
4. review notes have not been deleted;
5. the working tree is clean;
6. all code/docs changes are committed.

---

## Verification

- New `next_patch_version` unit tests pass; `python3 scripts/version_guard.py next-patch
  0.3.3` prints `0.3.4` (exit 0) and a bad input exits non-zero.
- New workflow-content tests pass and the existing `tests/test_release_workflows.py` tests
  still pass unchanged.
- Full quality gates green: `./run.sh bash scripts/quality_gates.sh check`.
- `git status --short` clean of caches.
- Manual reasoning check on `release.yml`: the new job runs only after a successful stable
  release, opens a PR into `dev` (never pushes to `dev`), is idempotent, and no-ops when
  `dev` is already ahead.

Deferred (cannot be exercised without an actual stable release): the end-to-end behavior —
that publishing a real `vX.Y.Z` opens a `sync dev` PR bumping `dev` to `X.Y.(Z+1)`. This will
be observed on the next real release; note it as deferred rather than triggering a release to
test it.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished post-release-dev-sync
```

This writes:

```text
/tmp/sdh_ludusavi/post-release-dev-sync_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer post-release-dev-sync`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/post-release-dev-sync-review-*.md
```

When a review note exists or a new review note appears:

1. Read the full review note.
2. If the note ends with:

   ```text
   STATUS: CHANGES_REQUESTED
   ```

   then resume work.

3. Clear the round-complete marker:

   ```bash
   scripts/orchestration/clear-finished post-release-dev-sync
   ```

4. Address every requested change.
5. Run quality gates:

   ```bash
   scripts/orchestration/run-quality-gates
   scripts/orchestration/check-review-notes-not-deleted
   ```

6. Commit code/docs fixes.
7. Commit the review-note file itself if it is not already committed:

   ```bash
   git add docs/review/post-release-dev-sync-review-*.md
   git commit -m "docs(review): record post-release-dev-sync review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished post-release-dev-sync
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer post-release-dev-sync` after the next review note is created.

---

## Approval Handling

If the latest review note ends with:

```text
STATUS: APPROVED
```

then:

1. Confirm every previous review item has been addressed.
2. Confirm all review notes are committed:

   ```bash
   scripts/orchestration/check-review-notes-committed post-release-dev-sync
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize post-release-dev-sync
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/post-release-dev-sync_finalized
   ```

6. Stop polling and exit cleanly.

---

## Review Rules

Do not write your own review.

Do not create files under:

```text
docs/review/
```

Do not delete files under:

```text
docs/review/
```

Only the orchestrator writes review notes. Your job is to read them, resolve them, commit them as audit records, and continue the loop.

---

## Finalization Rules

Only finalize after a review note with:

```text
STATUS: APPROVED
```

Finalization is performed with:

```bash
scripts/orchestration/finalize post-release-dev-sync
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/post-release-dev-sync_finished
/tmp/sdh_ludusavi/post-release-dev-sync_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
