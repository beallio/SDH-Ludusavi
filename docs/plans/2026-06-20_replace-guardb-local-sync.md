# Plan: Replace Guard B CI Job With Local Post-Release Sync Script (replace-guardb-local-sync)

## Context

Guard B (post-release dev sync) was just implemented as a GitHub Actions job
(`post-release-dev-sync` in `.github/workflows/release.yml`) that opens a PR into `dev`
after a stable release. That CI/PR design is the wrong shape for this project's workflow:
**releases are cut locally** (the maintainer merges `dev`→`main`, tags, and pushes by hand),
so the post-release sync is just another local step. A CI-opened PR adds machinery — it
requires the repo's "Allow GitHub Actions to create and approve pull requests" setting
(currently OFF), and produces a PR the maintainer then has to click-merge — to do something
they could do in one local command. The merge half is also nearly redundant: because the
release direction is `dev`→`main`, `main` never holds anything `dev` lacks except the merge
commit, so "Guard B" effectively reduces to "bump `dev` to the next patch after a release".

**Decision:** replace the CI job with a **local post-release sync script**. Guards A
(`request_dev_release.sh` / `dev-release.yml` refuse a stale base) and C
(`tests/test_version_config.py` CI not-behind assertion) remain as the detection safety net;
this change only swaps the prevention mechanism from CI/PR to a local script.

**Intended outcome:** running one local script after a stable release brings `dev` to the
next patch dev version (and merges `main`→`dev` if `main` is ever ahead), with quality gates
run before the commit — no GitHub Actions PR machinery and no special repo permission.

Relevant files (verified):
- `.github/workflows/release.yml` — contains the `post-release-dev-sync:` job (added after
  the `build-and-release` job, ~lines 104-189). **Remove that job**; leave the
  `build-and-release` job untouched.
- `tests/test_release_workflows.py` — contains `test_post_release_dev_sync_job_content`
  asserting that job. **Remove that test** (it asserts a job that will no longer exist).
- `scripts/version_guard.py` — keep `next_patch_version()` and the `next-patch` CLI (the
  local script reuses them). Keep their unit tests in `tests/test_version_guard.py`.
- `scripts/request_dev_release.sh` — reference pattern for a local release-tooling script
  (bash, `set -euo pipefail`, clear errors, tested via subprocess with mocked `git` in
  `tests/test_release_workflows.py`).
- `scripts/set_release_version.py` — stdlib-only; updates `package.json` + `plugin.json`.
- `DEVELOPMENT.md` — "Prerelease (Dev) Release Process" / release section; document the new
  local post-release step.
- `docs/plans/2026-06-19_dev-release-auto-merge-back.md` — the Guard B scoping doc; update its
  status note to record that the CI/PR approach was replaced by a local script.

**Slug used throughout this plan:** `replace-guardb-local-sync`

---

## Orchestration Contract

**Slug:** `replace-guardb-local-sync`

**Plan file:**

```text
docs/plans/2026-06-20_replace-guardb-local-sync.md
```

**Implementation branch:**

```text
feat/replace-guardb-local-sync
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/replace-guardb-local-sync_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/replace-guardb-local-sync_finalized
```

**Review notes:**

```text
docs/review/replace-guardb-local-sync-review-*.md
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
git checkout -b feat/replace-guardb-local-sync
```

Commit this plan first:

```bash
git add docs/plans/2026-06-20_replace-guardb-local-sync.md
git commit -m "docs(plan): add replace-guardb-local-sync implementation plan"
```

---

## Implementation Tasks

Strict TDD where testable. No new third-party deps. Use `./run.sh` for tooling.

### Task 1 — Remove the CI Guard B job and its test

- In `.github/workflows/release.yml`, delete the entire `post-release-dev-sync:` job. Leave
  the `build-and-release` job and the publish step exactly as they are.
- In `tests/test_release_workflows.py`, delete `test_post_release_dev_sync_job_content`.
- Keep `next_patch_version()` / the `next-patch` CLI in `scripts/version_guard.py` and their
  unit tests in `tests/test_version_guard.py` — the local script reuses them.

### Task 2 — Add the local post-release sync script

Create `scripts/post_release_sync.sh` (bash, `set -euo pipefail`, mark executable). Behavior:

1. Determine the just-released stable version: default to the highest stable `vX.Y.Z` tag
   (`git tag -l 'v*'` filtered to stable), or accept it as `$1`. Compute the next patch via
   `./run.sh uv run python scripts/version_guard.py next-patch "<version>"` (or `python3` —
   the helper is stdlib-only).
2. Require a clean working tree; check out `dev` and `git pull --ff-only origin dev`.
3. If `origin/main` has commits `dev` lacks, merge `main` into `dev` non-interactively
   (`GIT_EDITOR=true git merge --no-ff origin/main -m "..."`). On conflict: stop with a
   clear message telling the maintainer to resolve and re-run — do **not** force or auto-
   resolve. (In the normal `dev`→`main` flow this is usually a no-op / fast clean merge.)
4. No-op guard: if `dev`'s declared version is already `>= next` AND `dev` already contains
   `main`, print "already synced" and exit 0 without committing.
5. Bump `dev` to the next patch via `./run.sh uv run python scripts/set_release_version.py
   "<next>"`.
6. Run quality gates (`./run.sh bash scripts/quality_gates.sh check`) before committing; abort
   on failure.
7. Commit `chore(release): bump dev to <next> after <released-tag>`.
8. Push `dev` (`git push origin dev`) — the maintainer is running this deliberately, so the
   push is the point. (If you prefer to leave the push to the maintainer, instead print the
   exact `git push origin dev` command and exit; pick one and document it. Default: push.)

Keep it idempotent (safe to re-run; the no-op guard handles the already-synced case) and
self-explanatory on every error path.

### Task 3 — Test the script (subprocess, mocked git)

Add a test (e.g. in `tests/test_release_workflows.py`) mirroring the existing
`request_dev_release.sh` pattern: put a mock `git` (and a stub for `./run.sh` / the bumped
files as needed) on `PATH` and assert the script:
- computes the correct next patch and refuses/aborts cleanly on the conflict path;
- never pushes to `main` and never creates a tag (scope check: assert no `push origin main`,
  no `git tag`);
- exits non-zero with a helpful message on a dirty tree / merge conflict.
If fully driving the script is impractical (it shells into gates), at minimum add a content
+ smoke test: the script exists, is executable (`os.access(..., os.X_OK)`), uses
`version_guard.py next-patch` and `set_release_version.py`, and contains no `git tag` /
`push origin main`. Prefer the behavioral subprocess test where feasible.

### Task 4 — Docs

- `DEVELOPMENT.md`: in the release section, document running `scripts/post_release_sync.sh`
  immediately after cutting a stable release (what it does, that it bumps `dev` and pushes).
- `docs/plans/2026-06-19_dev-release-auto-merge-back.md`: append a short status note that the
  CI/PR Guard B was superseded by the local `scripts/post_release_sync.sh` for this project's
  local release workflow.

### Out of scope (do NOT do here)

- Do NOT touch Guard A (`request_dev_release.sh`) or Guard C
  (`tests/test_version_config.py` / `version_guard.is_version_behind_stable`).
- Do NOT change the `build-and-release` job or the stable publish behavior.
- Do NOT make the script perform the stable release itself (merge dev→main / tag / publish);
  it only does the post-release `dev` bump/sync.
- Do NOT trigger any release.

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

- `.github/workflows/release.yml` no longer contains `post-release-dev-sync`; the
  `build-and-release` job is unchanged.
- `tests/test_release_workflows.py` no longer references the removed job; its other tests
  pass unchanged.
- `scripts/post_release_sync.sh` exists, is executable, and its test(s) pass (correct
  next-patch, clean conflict/dirty-tree handling, no `git tag` / `push origin main`).
- `next_patch_version` unit tests still pass.
- Full quality gates green: `./run.sh bash scripts/quality_gates.sh check`.
- `git status --short` clean of caches.
- Manual dry-read of the script: on the current repo state (`dev` = 0.3.4, stable = v0.3.3)
  it would compute next = 0.3.4 from v0.3.3, see `dev` already `>= 0.3.4`, and **no-op** —
  confirm the guard prevents a spurious bump.

Deferred: real end-to-end use is observed the next time a stable release is cut locally
(run the script right after). No release is triggered as part of this work.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished replace-guardb-local-sync
```

This writes:

```text
/tmp/sdh_ludusavi/replace-guardb-local-sync_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer replace-guardb-local-sync`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/replace-guardb-local-sync-review-*.md
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
   scripts/orchestration/clear-finished replace-guardb-local-sync
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
   git add docs/review/replace-guardb-local-sync-review-*.md
   git commit -m "docs(review): record replace-guardb-local-sync review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished replace-guardb-local-sync
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer replace-guardb-local-sync` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed replace-guardb-local-sync
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize replace-guardb-local-sync
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/replace-guardb-local-sync_finalized
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
scripts/orchestration/finalize replace-guardb-local-sync
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/replace-guardb-local-sync_finished
/tmp/sdh_ludusavi/replace-guardb-local-sync_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
