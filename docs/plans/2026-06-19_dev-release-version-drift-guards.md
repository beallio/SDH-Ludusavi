# Plan: Dev Release Version-Drift Guards (dev-release-version-drift-guards)

## Context

A stable release bumps the version only on `main` (the `chore(release): vX.Y.Z` commit),
and nothing syncs it back to `dev`. `dev` therefore drifts a version behind and keeps
emitting dev prereleases tagged with the *old* base — e.g. after `v0.3.2` shipped, `dev`
still declared `0.3.1` and finalize produced `v0.3.1-dev.gSHA`, which sorts *below* the
`0.3.2` stable and looks like "no release happened". The existing guards only catch an
**exact** stable-tag match (`v${BASE_VERSION}` exists), so a base that is merely *behind*
a newer stable (`0.3.1` while `0.3.2` is released) sails through silently.

This plan adds two detection guards (prevention via auto-merge-back is deliberately **out
of scope** — that is a separate effort, scoped in
`docs/plans/2026-06-19_dev-release-auto-merge-back.md`; do not implement it here):

- **Guard A — refuse a stale dev base at dispatch.** `scripts/request_dev_release.sh` and
  the authoritative server-side re-check in `.github/workflows/dev-release.yml` must refuse
  when the requested base version is **at or below the highest released stable tag**, not
  only when it exactly matches one. Error message must be actionable (name both versions
  and tell the user to merge `main`→`dev` and bump).
- **Guard C — assert dev stays ahead in CI.** A test asserts the repo's declared version
  (`package.json` / `plugin.json`) is **strictly greater** than the highest released stable
  `vX.Y.Z` tag, so any drift fails fast on a normal `dev` push — and skips cleanly when no
  stable tags are reachable (shallow checkout / fresh clone).

Both guards encode the **same rule** ("declared/base version must be strictly greater than
the highest released stable tag"). Implement that rule once as the single source of truth
and have both guards use it (see Implementation Tasks).

Relevant files (verified):
- `scripts/request_dev_release.sh` — exact-match guard at the `git tag --list "v${BASE_VERSION}"` block.
- `.github/workflows/dev-release.yml` — server-side guard in the **"Check if Dev Tag Already Exists"** step (`git rev-parse "v${BASE_VERSION}"`).
- `scripts/package_plugin.py` — `validate_package_versions(project_root) -> str` returns the single-source-of-truth version (raises if `package.json`/`plugin.json` disagree).
- `tests/test_release_workflows.py` — already tests `request_dev_release.sh` by mocking `git`/`gh` on `PATH` (see `test_request_dev_release_rejects_already_released_stable`); also asserts workflow YAML content by substring.
- `tests/test_version_config.py`, `tests/test_version.py` — version-related test homes.

**Slug used throughout this plan:** `dev-release-version-drift-guards`

---

## Orchestration Contract

**Slug:** `dev-release-version-drift-guards`

**Plan file:**

```text
docs/plans/2026-06-19_dev-release-version-drift-guards.md
```

**Implementation branch:**

```text
feat/dev-release-version-drift-guards
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/dev-release-version-drift-guards_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/dev-release-version-drift-guards_finalized
```

**Review notes:**

```text
docs/review/dev-release-version-drift-guards-review-*.md
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
git checkout -b feat/dev-release-version-drift-guards
```

Commit this plan first, together with the companion Guard-B scoping doc (already present in
the working tree and referenced by this plan), so the tree is clean:

```bash
git add docs/plans/2026-06-19_dev-release-version-drift-guards.md \
        docs/plans/2026-06-19_dev-release-auto-merge-back.md
git commit -m "docs(plan): add dev-release-version-drift-guards implementation plan"
```

---

## Implementation Tasks

Follow strict TDD: write the failing test first for each behavior change, then implement.
Keep the full suite green throughout. No new third-party dependencies. Use `./run.sh` for
all tooling so caches stay under `/tmp/sdh_ludusavi/`.

### Task 0 — Canonical comparison helper (single source of truth)

Implement the rule **once** in Python so both guards and the CI test share it. Add a small
module, e.g. `scripts/version_guard.py`, exposing pure, importable functions:

- `parse_semver(text: str) -> tuple[int, int, int]` — parse `X.Y.Z` (reject non-stable).
- `highest_stable_version(tags: Iterable[str]) -> tuple[int,int,int] | None` — from an
  iterable of tag names, consider only stable `vX.Y.Z` tags (exclude anything containing
  `-dev` or other pre-release suffix); return the max, or `None` if there are none.
- `is_base_ahead_of_stable(base: str, tags: Iterable[str]) -> bool` — `True` iff
  `parse_semver(base)` is **strictly greater** than `highest_stable_version(tags)` (and
  `True` when there are no stable tags).
- A CLI entrypoint usable from shell, e.g.
  `python scripts/version_guard.py check-base <BASE_VERSION>`: read tags via
  `git tag --list 'v*'`, exit `0` if the base is strictly ahead of the highest stable tag,
  exit non-zero with an actionable stderr message naming the base and the highest stable
  version (e.g. `dev base 0.3.1 is not ahead of released stable 0.3.2; merge main into dev
  and bump package.json/plugin.json`) otherwise.

**Tests first** (e.g. `tests/test_version_guard.py`): table-driven cases for
`highest_stable_version` (ignores `-dev` tags; `None` when empty), `is_base_ahead_of_stable`
(`0.3.1` vs `[v0.3.2]` → False; `0.3.3` vs `[v0.3.2]` → True; equal → False; no stable tags
→ True), and `parse_semver` rejecting non-stable input. These are the red-first unit tests
that give Guard C real meaning even though the live repo is currently healthy.

### Task A — Strengthen the dispatch-time guards

1. **`scripts/request_dev_release.sh`** — after the existing format validation and the
   existing exact-match block (keep it as a fast/clear path), add a check that calls the
   canonical helper, e.g. `./run.sh uv run python scripts/version_guard.py check-base
   "$BASE_VERSION"`; on non-zero, print the helper's message and `exit 1` **before**
   dispatching `gh workflow run`. Preserve the existing usage/format/commit-resolution
   behavior and the existing successful dispatch path unchanged.
   - **Test first** in `tests/test_release_workflows.py`: mirror
     `test_request_dev_release_rejects_already_released_stable`'s `git`/`gh` mocking, but
     mock `git tag` to report a higher stable tag (`v0.3.2`) and request base `0.3.1`;
     assert the script exits non-zero, emits an actionable message, and does **not** invoke
     `gh workflow run`. Keep all existing tests in this file passing unchanged (the happy-
     path tests mock git such that no higher stable tag exists, so they must still dispatch).

2. **`.github/workflows/dev-release.yml`** — extend the **"Check if Dev Tag Already Exists"**
   step so the server-side re-check also refuses a base at/below the highest stable tag
   (after `git fetch --tags origin`). Use the same rule; you may invoke the canonical helper
   after toolchain setup, or implement the equivalent `git tag --list 'v*' | sort -V`
   comparison inline in that bash step — but the message and semantics must match the script.
   - **Test first**: extend the YAML-content assertions in `tests/test_release_workflows.py`
     (the `test_workflows_*` family that reads the workflow file) to assert the dev-release
     workflow contains the strengthened check (e.g. references the helper or the
     highest-stable comparison), so the guard cannot silently regress.

### Task C — CI assertion that dev stays ahead of stable

Add a test (e.g. `tests/test_dev_version_ahead_of_stable.py`, or extend
`tests/test_version_config.py`) that:

- reads the declared version via `validate_package_versions(Path.cwd())` (single source of
  truth; also enforces `package.json`/`plugin.json` agreement);
- collects stable tags via `git tag --list 'v*'`;
- uses the Task 0 helper to assert the declared version is **strictly ahead** of the highest
  stable tag;
- **skips cleanly** (e.g. `pytest.skip`) when no stable `vX.Y.Z` tags are reachable, so the
  test never fails on a shallow CI checkout or a tagless clone. (If you want this guard to
  run in CI reliably, note in the test docstring that it requires tags; do **not** add a
  workflow change to fetch tags as part of this plan — that is fine to leave for the
  reviewer to decide.)

This test passes on the current healthy repo (`0.3.3 > 0.3.2`); its red-first coverage lives
in the Task 0 unit tests.

### Out of scope (do NOT implement here)

- Guard B (auto-merge-back after stable release). Leave a scoping plan only — see
  `docs/plans/2026-06-19_dev-release-auto-merge-back.md` (already created). Do not modify
  `release.yml` for merge-back.
- Do not delete or alter existing releases/tags.
- Do not change the dev base version or dispatch any release as part of this work.

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

- `scripts/version_guard.py check-base 0.3.1` exits non-zero with an actionable message
  (names `0.3.1` and the highest stable `0.3.2`); `check-base 0.3.3` exits `0`.
- New `tests/test_version_guard.py` unit tests pass (drift → refuse, ahead → allow,
  no-stable-tags → allow, non-stable input → reject).
- `tests/test_release_workflows.py`: the new stale-base rejection test passes, the new
  workflow-content assertion passes, and **all pre-existing tests in the file still pass
  unchanged** (happy-path dispatch tests must still dispatch).
- Guard C test passes on this repo (`0.3.3 > 0.3.2`) and skips cleanly with no stable tags.
- Full quality gates green: `./run.sh bash scripts/quality_gates.sh check` (ruff, ty,
  pytest, `pnpm run verify`).
- `git status --short` clean of caches.

Deferred: no on-device testing applies (release-tooling-only change). Whether CI should
fetch tags so Guard C runs (vs. skips) in the pipeline is a reviewer decision, not part of
this plan.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished dev-release-version-drift-guards
```

This writes:

```text
/tmp/sdh_ludusavi/dev-release-version-drift-guards_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer dev-release-version-drift-guards`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/dev-release-version-drift-guards-review-*.md
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
   scripts/orchestration/clear-finished dev-release-version-drift-guards
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
   git add docs/review/dev-release-version-drift-guards-review-*.md
   git commit -m "docs(review): record dev-release-version-drift-guards review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished dev-release-version-drift-guards
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer dev-release-version-drift-guards` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed dev-release-version-drift-guards
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize dev-release-version-drift-guards
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/dev-release-version-drift-guards_finalized
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
scripts/orchestration/finalize dev-release-version-drift-guards
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/dev-release-version-drift-guards_finished
/tmp/sdh_ludusavi/dev-release-version-drift-guards_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
