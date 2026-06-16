## Orchestration Contract

**Slug:** `REPLACE_WITH_SLUG`

**Plan file:**

```text
docs/plans/REPLACE_WITH_DATE_REPLACE_WITH_SLUG.md
```

**Implementation branch:**

```text
feat/REPLACE_WITH_SLUG
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/REPLACE_WITH_SLUG_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/REPLACE_WITH_SLUG_finalized
```

**Review notes:**

```text
docs/review/REPLACE_WITH_SLUG-review-*.md
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
git checkout -b feat/REPLACE_WITH_SLUG
```

Commit this plan first:

```bash
git add docs/plans/REPLACE_WITH_DATE_REPLACE_WITH_SLUG.md
git commit -m "docs(plan): add REPLACE_WITH_SLUG implementation plan"
```

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

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished REPLACE_WITH_SLUG
```

This writes:

```text
/tmp/sdh_ludusavi/REPLACE_WITH_SLUG_finished
```

Then either continue watching for review notes or exit cleanly. If this process exits, the orchestrator will resume you with `agy -c -p` through `scripts/orchestration/continue-implementer REPLACE_WITH_SLUG`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/REPLACE_WITH_SLUG-review-*.md
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
   scripts/orchestration/clear-finished REPLACE_WITH_SLUG
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
   git add docs/review/REPLACE_WITH_SLUG-review-*.md
   git commit -m "docs(review): record REPLACE_WITH_SLUG review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished REPLACE_WITH_SLUG
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer REPLACE_WITH_SLUG` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed REPLACE_WITH_SLUG
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize REPLACE_WITH_SLUG
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/REPLACE_WITH_SLUG_finalized
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
scripts/orchestration/finalize REPLACE_WITH_SLUG
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/REPLACE_WITH_SLUG_finished
/tmp/sdh_ludusavi/REPLACE_WITH_SLUG_finalized
```

Steam Deck/user testing is deferred until after `dev` is pushed to GitHub and the dev release is requested.


## Orchestrator Resume Ordering

The orchestrator resumes the implementer only after review notes are written and committed.

Correct order:

```bash
scripts/orchestration/add-review-note <SLUG> CHANGES_REQUESTED
# edit and commit docs/review/<SLUG>-review-NN.md
scripts/orchestration/continue-implementer <SLUG>
```

Do not require the implementer to rely on a future review-note file creation event. On resume, it must scan existing review notes first.
