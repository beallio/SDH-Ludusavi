# Review Round 3: Review Findings Remediation

Plan:

`docs/plans/2026-06-13_review_findings_remediation.md`

Reviewed branch:

`fix/review-findings-remediation`

Reviewed range:

`d62a8e0..7f570ce`

## Verdict

Documentation changes are required. No additional production-code change is
requested.

The round-2 runtime implementation is accepted:

- Runtime identity fields are validated using exact integer checks.
- Boolean UID and start-tick values are rejected.
- Command line must be nonempty bytes.
- Malformed records do not raise or consume the cap.
- Report writes preserve first-seen order and prevent duplicate PIDs.
- The UID-change test now asserts the complete report contract.
- Round-1 status placement and concrete path/test-name corrections were made.
- The round-2 RED log contains genuine failures.
- Ruff, formatting, `ty`, 42 singleton tests, and TDD policy checks pass.

The following handoff artifacts remain incomplete.

## Finding 1: Round 2 Has No Resolution Section

Severity: Medium

File:

`docs/review/2026-06-13_review_findings_remediation_review_round_2.md`

### Problem

Round 2 explicitly required:

> Append a `## Resolution` section to this file with exact changes,
> RED/GREEN commands, final test counts, coverage, and commit SHAs.

The agent created:

`/tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_review_round_2_finished`

but the review note ends immediately after its original
`STATUS: CHANGES_REQUESTED`. It contains no resolution.

The marker therefore claimed round completion before the documented completion
contract was satisfied.

### Required Fix

Append a `## Resolution` section to the round-2 note.

For each finding, record:

1. Exact runtime or documentation change.
2. Exact tests added or corrected.
3. RED command:

   ```bash
   UV_FROZEN=1 ./run.sh uv run pytest \
     -o addopts="" \
     tests/test_singleton.py \
     -k "malformed_runtime_identity or duplicate"
   ```

4. RED failure reason.
5. GREEN command using `-o addopts=""`.
6. Full sequential validation result.
7. Implementation commit: `7f570ce`.

After the resolution, repeat this exact final line:

```text
STATUS: CHANGES_REQUESTED
```

It remains changes-requested because that was round 2's decision.

## Finding 2: Session Log Omits Completed Review Commits

Severity: Medium

File:

`docs/agent_conversations/2026-06-13_review_findings_remediation.json`

### Problem

The `commit_shas` array stops at:

```text
25673a0 fix(singleton): exact identity tracking and valid safety cap
```

It omits:

```text
d62a8e0 docs(review): record round 1 resolution and update session log
7f570ce fix(singleton): exact runtime type validation and duplicate pid prevention
```

The session log therefore does not describe the branch it claims to summarize.

### Required Fix

Add both commits to `commit_shas`.

After committing this round-3 documentation update, add that new commit to the
session log as well. Because a commit cannot contain its own final SHA before
it exists, use one of these acceptable approaches:

1. Make a documentation commit, then a final small session-log commit that
   records the preceding SHA; or
2. Record the final documentation commit as `pending/current documentation
   commit` and do not claim a false SHA.

Do not amend or rewrite existing commits.

## Finding 3: The Recorded GREEN Command Is Not a Valid Targeted GREEN Gate

Severity: Medium

File:

`docs/agent_conversations/2026-06-13_review_findings_remediation.json`

### Problem

The session log records:

```text
UV_FROZEN=1 ./run.sh uv run pytest tests/test_singleton.py
```

As demonstrated by the initial invalid RED run, running one test file with the
project's default `addopts` executes project-wide coverage and exits nonzero
because a single file cannot reach the global 83% threshold.

The command can have all singleton assertions pass while still failing the
process exit code. It is not an accurate targeted GREEN command.

### Required Fix

Replace the single string with explicit round-specific commands:

```json
"green_commands": [
  "UV_FROZEN=1 ./run.sh uv run pytest -o addopts=\"\" tests/test_singleton.py -k \"identity or reused or changes or differently or zombies or incomplete or trigger or refusal\"",
  "UV_FROZEN=1 ./run.sh uv run pytest -o addopts=\"\" tests/test_singleton.py -k \"malformed_runtime_identity or duplicate\"",
  "UV_FROZEN=1 ./run.sh uv run pytest"
]
```

The first two are targeted GREEN checks. The last is the full coverage gate.

If the exact selectors used differed, record the exact successful commands
rather than copying these examples inaccurately.

## Finding 4: Round-3 Artifact Must Be Included in the Session Log

Severity: Medium

File:

`docs/agent_conversations/2026-06-13_review_findings_remediation.json`

### Problem

The concrete `files_modified` list is currently accurate through round 2, but
this round creates:

`docs/review/2026-06-13_review_findings_remediation_review_round_3.md`

The final session log must include it.

### Required Fix

Add the exact round-3 path to `files_modified`.

Keep the list concrete and sorted. Do not reintroduce wildcards.

## Required Documentation-Only Workflow

1. Remain on `fix/review-findings-remediation`.
2. Use the `implementer` skill and preserve the clean runtime implementation.
3. Do not change:
   - `py_modules/sdh_ludusavi/singleton.py`
   - `tests/test_singleton.py`
   - Vendored pyludusavi files.
   - Dependency or lock files.
   - Frontend files.
4. Append the complete round-2 resolution.
5. Correct the session log.
6. Append a `## Resolution` section to this round-3 note documenting each
   correction and its commit SHA.
7. Repeat this file's status as its final nonblank line.
8. Validate JSON syntax:

```bash
./run.sh uv run python -m json.tool \
  docs/agent_conversations/2026-06-13_review_findings_remediation.json
```

9. Run:

```bash
git diff --check
git status --short --branch
```

10. Commit the review and session-log documentation.
11. Ensure the branch is clean.
12. Create the exact zero-byte marker:

```text
/tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_review_round_3_finished
```

13. Resume polling for round 4. Do not merge, push, clean up, or release until
    a later review note ends with `STATUS: APPROVED`.

STATUS: CHANGES_REQUESTED

## Resolution
All documentation changes have been successfully implemented:

### Finding 1
- **Fix**: Appended a full `## Resolution` section to the Round 2 review document `docs/review/2026-06-13_review_findings_remediation_review_round_2.md` containing precise details of the changes, commands, and results for Findings 1-5, along with repeating the required final `STATUS: CHANGES_REQUESTED` line.
- **Commit SHA**: pending/current documentation commit

### Finding 2
- **Fix**: Updated the `commit_shas` array in `docs/agent_conversations/2026-06-13_review_findings_remediation.json` to include the missing commits (`d62a8e0` and `7f570ce`). Added a final entry for `"pending/current documentation commit"`.
- **Commit SHA**: pending/current documentation commit

### Finding 3
- **Fix**: Replaced the single `green_commands` string in `docs/agent_conversations/2026-06-13_review_findings_remediation.json` with an array of targeted test commands and the full suite validation command used across the review rounds.
- **Commit SHA**: pending/current documentation commit

### Finding 4
- **Fix**: Added `docs/review/2026-06-13_review_findings_remediation_review_round_3.md` to the `files_modified` array in `docs/agent_conversations/2026-06-13_review_findings_remediation.json`, ensuring the list remains sorted and concrete without wildcards.
- **Commit SHA**: pending/current documentation commit

STATUS: CHANGES_REQUESTED
