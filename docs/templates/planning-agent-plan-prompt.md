/plan write a detailed and thorough implementation plan for your findings.

Include in the plan where work should be combined and where work should be done separately.

The plan will be consumed by a low-context implementing agent, so make it explicit, operational, and detailed.

Determine the plan metadata yourself from the task and findings. Do not ask the user to provide these values unless the task is genuinely ambiguous.

Derive:

```text
TITLE=<short human-readable task title>
SLUG=<short lowercase kebab-case identifier>
PLAN_PATH=docs/plans/<YYYY-MM-DD>_<SLUG>.md
```

Use these rules:

- `TITLE` should be concise and specific, for example `Increase Cloud X Icon Size`.
- `SLUG` should be lowercase kebab-case, for example `increase-cloud-x-icon-size`.
- `SLUG` should omit filler words and stay stable throughout the task.
- `PLAN_PATH` should use today’s date and the slug.
- If the user already provided a plan path, slug, title, or branch, preserve the user’s choice.
- If a title exists and you need a deterministic slug, use:

  ```bash
  scripts/orchestration/slugify-title "$TITLE"
  ```

Use the following implementation protocol:

- The implementing agent must use the `implementer` skill.
- The implementing agent must develop on a separate branch from `dev`.
- The implementation branch must be `feat/<SLUG>`.
- The plan must be written as direct instructions for the implementer only.
- The `docs/plans` copy is the implementer’s copy. Do not include two-party/orchestrator meta in it.
- The implementing agent must not write its own review.
- The implementing agent must not create files under `docs/review/`.
- The implementing agent must not delete files under `docs/review/`.
- Review notes are durable audit records and must be committed.

The plan must include a clear orchestration contract with these exact path patterns, replacing `<SLUG>` and `<PLAN_PATH>` with the values you determined:

Plan path:

```text
<PLAN_PATH>
```

Implementation branch:

```text
feat/<SLUG>
```

Round-complete marker:

```text
/tmp/sdh_ludusavi/<SLUG>_finished
```

Finalized marker:

```text
/tmp/sdh_ludusavi/<SLUG>_finalized
```

Review notes:

```text
docs/review/<SLUG>-review-*.md
```

Each review note will end with exactly one of:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

When the implementing agent completes an implementation or review round, it must:

1. run the project quality gates;
2. ensure the working tree is clean;
3. commit all relevant changes;
4. write the round-complete marker by running:

   ```bash
   scripts/orchestration/mark-finished <SLUG>
   ```

Then it must either continue polling for review notes or exit cleanly. If it exits, the orchestrator will resume it with `agy -c -p` through `scripts/orchestration/continue-implementer <SLUG>`.

If it remains active, it must continue polling for review notes in:

```text
docs/review/<SLUG>-review-*.md
```

Review notes are the trigger for the implementing agent to resume work. On every resume, the implementing agent must scan existing review notes before waiting for future file events.

When a review note with `STATUS: CHANGES_REQUESTED` appears, the implementing agent must:

1. clear the round-complete marker:

   ```bash
   scripts/orchestration/clear-finished <SLUG>
   ```

2. read the review note;
3. implement every requested change;
4. run quality gates;
5. commit the implementation fixes;
6. commit the review note itself if it has not already been committed;
7. recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished <SLUG>
   ```

8. either continue polling for more review notes or exit cleanly so the orchestrator can resume it again later.

When a review note with `STATUS: APPROVED` appears, the implementing agent must:

1. confirm all review notes are committed;
2. confirm the working tree is clean;
3. finalize by running:

   ```bash
   scripts/orchestration/finalize <SLUG>
   ```

4. confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/<SLUG>_finalized
   ```

5. stop polling and exit cleanly.

Finalization must include:

- commit any review note if it has not already been committed;
- merge the working branch into `dev`;
- clean up the working branch;
- push `dev` to GitHub;
- request/push a new dev release using the project release script.

Also note that Steam Deck/user testing is deferred until after the dev push to GitHub.

Make the plan concrete: include exact files to inspect, tests to add or update, commands to run, expected verification, and known risks.


## Orchestrator Resume Ordering

The orchestrator resumes the implementer only after review notes are written and committed.

Correct order:

```bash
scripts/orchestration/add-review-note <SLUG> CHANGES_REQUESTED
# edit and commit docs/review/<SLUG>-review-NN.md
scripts/orchestration/continue-implementer <SLUG>
```

Do not require the implementer to rely on a future review-note file creation event. On resume, it must scan existing review notes first.
