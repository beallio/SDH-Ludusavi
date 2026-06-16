---
name: orchestrated-implementation
description: Manage a plan-driven implementation workflow by coordinating a background implementer agent, durable review notes, round-complete markers, finalization markers, dev-branch merge/push/release, and implementer shutdown. Use when the user wants an orchestrator agent to write plans, start an implementer agent, review work, issue follow-up review notes, wait for finalization, and stop the implementer session.
disable-model-invocation: true
---

# Orchestrated Implementation

Use this skill when the user wants a main/orchestrator agent to coordinate an implementer agent through a plan/review/finalization loop.

## Purpose

You are the orchestrator. You manage the implementation lifecycle.

Your responsibilities are:

1. create or update the implementation plan;
2. start the implementer in a managed background session;
3. wait for implementation completion markers;
4. review the implementation;
5. write and commit review notes;
6. keep the implementer session alive during review cycles;
7. wait for finalization after approval;
8. stop the implementer session after finalization.

Do not implement the feature yourself unless explicitly instructed.

## Per-task metadata

Infer these for each task unless the user explicitly provides them:

```text
TITLE=<short human-readable task title>
SLUG=<short lowercase kebab-case identifier derived from the title/task>
PLAN_PATH=docs/plans/<YYYY-MM-DD>_<SLUG>.md
```

Do not ask the user for `SLUG`, `TITLE`, or `PLAN_PATH` when they can be reasonably inferred from the task.

Use these rules:

- `TITLE` should be specific and concise, for example `Increase Cloud X Icon Size`.
- `SLUG` should be lowercase kebab-case, for example `increase-cloud-x-icon-size`.
- `SLUG` should omit filler words and stay stable throughout the task.
- `PLAN_PATH` should use today’s date and the slug: `docs/plans/<YYYY-MM-DD>_<SLUG>.md`.
- If the user already names a slug, plan file, or branch, preserve the user’s choice.
- If a suitable title exists but you want deterministic slugification, use:

  ```bash
  scripts/orchestration/slugify-title "$TITLE"
  ```

The slug drives:

```text
docs/plans/<date>_<slug>.md
docs/review/<slug>-review-*.md
/tmp/sdh_ludusavi/<slug>_finished
/tmp/sdh_ludusavi/<slug>_finalized
feat/<slug>
```

## Plan rule

The plan in `docs/plans/` is the implementer’s copy. It must contain direct implementer instructions only.

Do not include two-party/orchestrator meta in the plan.

Before creating the plan, determine `TITLE`, `SLUG`, and `PLAN_PATH` from the task. Then create the plan with:

```bash
scripts/orchestration/new-plan "$SLUG" "$TITLE"
```

If another planning command writes the plan, ensure the final `docs/plans/...` file includes the content from:

```text
docs/templates/implementation-plan-context.md
```

with placeholders replaced.

## Orchestrator lifecycle

### 1. Work from repo root

Before using this skill, operate from the repository root.

### 2. Determine metadata

Derive the task metadata:

```text
TITLE=<short human-readable title>
SLUG=<lowercase kebab-case slug>
PLAN_PATH=docs/plans/<YYYY-MM-DD>_<SLUG>.md
```

When in doubt, choose a concise slug from the central implementation object. Do not ask the user for these values unless the task is genuinely ambiguous.

Validate state when useful:

```bash
scripts/orchestration/validate-state "$SLUG"
```

### 3. Create or update the plan

If no plan exists:

```bash
scripts/orchestration/new-plan "$SLUG" "$TITLE"
```

Then expand the plan with task-specific implementation details.

The plan must instruct the implementer to:

- use the `implementer` skill;
- branch from `dev`;
- commit the plan first;
- follow TDD where behavior changes are testable;
- run quality gates;
- write `/tmp/sdh_ludusavi/${SLUG}_finished` when a round is complete;
- poll `docs/review/${SLUG}-review-*.md`;
- resume work when review notes appear;
- never write its own review;
- never create or delete files under `docs/review/`;
- commit review notes as durable audit records;
- finalize after an approved review;
- write `/tmp/sdh_ludusavi/${SLUG}_finalized`;
- stop polling and exit cleanly after finalization.

### 4. Start or ensure implementer session

After the plan is ready, start the implementer with the slug:

```bash
scripts/orchestration/start-implementer "$SLUG"
```

This command resolves the existing plan path before launching the implementer. It must not rely on a future `docs/plans/` create event, because the plan commonly already exists before the implementer starts.

This command is idempotent. If the session already exists, do not create a duplicate.

After the first implementation round, the implementer may stop and exit after writing the round-complete marker. That is normal.

For follow-up review notes or approval, first write and commit the review note, then resume the implementer:

```bash
scripts/orchestration/continue-implementer "$SLUG"
```

Do not resume the implementer before the review note exists. The durable trigger is the committed review note.

`continue-implementer` resumes the previous agent context with `agy -c -p` and instructs it to scan existing review notes before waiting for future file events.

### 5. Wait for round completion

Wait for the implementer’s round-complete marker:

```bash
scripts/orchestration/wait-for-finished "$SLUG"
```

Do not review until the marker exists.

The marker is:

```text
/tmp/sdh_ludusavi/${SLUG}_finished
```

### 6. Review

Review the implementation against the plan.

Check:

1. every plan item is implemented;
2. tests/build/typecheck gates passed;
3. working tree is clean;
4. review notes were not deleted;
5. the implementation is semantically correct, not merely test-green;
6. the audit trail is complete.

If changes are required:

```bash
scripts/orchestration/clear-finished "$SLUG"
scripts/orchestration/add-review-note "$SLUG" CHANGES_REQUESTED
```

Edit the generated review note under:

```text
docs/review/${SLUG}-review-NN.md
```

The review note must end with:

```text
STATUS: CHANGES_REQUESTED
```

Commit the review note:

```bash
git add docs/review/${SLUG}-review-*.md
git commit -m "docs(review): request ${SLUG} changes"
```

After the review note is written and committed, resume the implementer:

```bash
scripts/orchestration/continue-implementer "$SLUG"
```

### 7. Repeat review cycles

Repeat:

```text
wait for _finished
review
write/commit review note
ensure implementer running
```

until the work is approved.

### 8. Approve

When the implementation passes review:

```bash
scripts/orchestration/add-review-note "$SLUG" APPROVED
```

Edit the generated approval note. It must include:

1. branch reviewed;
2. commit reviewed;
3. plan reviewed against;
4. final verdict;
5. gate status;
6. confirmation that prior findings are resolved;
7. finalization instructions;
8. final status trailer:

```text
STATUS: APPROVED
```

Commit the approval note:

```bash
git add docs/review/${SLUG}-review-*.md
git commit -m "docs(review): approve ${SLUG} implementation"
```

After the approval review note is written and committed, resume the implementer so it can observe approval and finalize:

```bash
scripts/orchestration/continue-implementer "$SLUG"
```

### 9. Wait for finalization

After approval, wait for the finalized marker:

```bash
scripts/orchestration/wait-for-finalized "$SLUG"
```

The marker is:

```text
/tmp/sdh_ludusavi/${SLUG}_finalized
```

Do not stop the implementer before the finalized marker exists.

### 10. Stop implementer

After finalization:

```bash
scripts/orchestration/stop-implementer "$SLUG"
```

Stopping the implementer is the orchestrator’s responsibility.

## Hard rules

- Do not ask the user to manually manage the implementer session.
- Do not rely on the user to attach to tmux.
- Do not create duplicate implementer sessions.
- Do not stop the implementer after `STATUS: APPROVED`; wait for `_finalized`.
- Do not delete review notes.
- Do not allow the implementer to write its own review.
- Do not finalize without an approved review note.
- If the implementer session exits after marking a round complete, that is acceptable. After creating a CHANGES_REQUESTED or APPROVED review note, resume it with `scripts/orchestration/continue-implementer "$SLUG"`, which uses `agy -c -p`.

If the implementer exits early before writing the round-complete marker, restart the initial plan run with `scripts/orchestration/start-implementer "$SLUG"`. Do not regenerate the plan or depend on a new file-create event.
- If finalization fails, report the exact failure and do not stop the implementer unless the failure leaves no running work to preserve.


## Ordering constraints

### Plan startup

Write the implementation plan before starting the implementer. This is safe because `start-implementer` passes the existing plan path to `agy`; it does not depend on a future create event.

Do not start the implementer before the plan exists unless explicitly recovering from an unusual state.

### Review resume

Write and commit review notes before calling:

```bash
scripts/orchestration/continue-implementer "$SLUG"
```

Do not start `continue-implementer` before the review note exists. The resume prompt is designed to scan existing review notes first.
