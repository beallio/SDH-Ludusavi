# Fix Updater Post-Install UI State

## Objective

Implement the updater UI fix so that after Decky reports a successful install handoff, the Updates panel no longer remains on `Status: Update available` with the old install button. The UI should optimistically reflect the installed target version as current, while backend startup reconciliation remains the durable source of truth.

The implementing agent must use the `implementer` skill and follow this repo's `AGENTS.md` protocol: create a feature branch, write or update this plan before code changes, use strict TDD, route commands through `./run.sh`, commit atomically, record a session log, then run review cycles until clean.

## Required Workflow

1. Start from clean `main`.
   - Verify `pwd`, `ls`, `git status --short --branch`, `.protocol`, `AGENTS.md`, `pyproject.toml`, `uv.lock`, `package.json`, and `run.sh`.
   - Output the `AGENT_PROTOCOL_HANDSHAKE`.
   - Create branch: `fix/updater-post-install-ui-state`.
2. Use the `implementer` skill.
   - Read `/home/beallio/Dropbox/Scripts/agent-skills/skills/implementer/SKILL.md`.
   - Follow its discovery, TDD, atomic commit, validation, session-log, and review-gate requirements.
   - Do not implement directly on `main`.
3. Treat this file as the implementation plan artifact.
   - Update it only if repo exploration reveals a concrete mismatch.
   - Preserve the functional intent and review-cycle requirements.

## Implementation Requirements

- Scope the behavior to `PluginUpdateSection`.
- Add local frontend override state for a successfully handed-off install, including:
  - target version;
  - target channel;
  - pre-install version observed when the install started.
- Derive `effectiveCurrentVersion = installedOverride?.version ?? currentVersion`.
  - Render Installed Version from `effectiveCurrentVersion`.
  - Pass `effectiveCurrentVersion` to update-check RPCs so stale checks do not continue comparing against the old version.
- Add a shared helper for successful handoff completion, called from both installer success paths:
  - immediate success after `await installerPromise`;
  - delayed success after the handoff timeout branch eventually resolves.
- On successful handoff:
  - set the installed override to the revalidated target version;
  - set `checkResult` to `{ status: "current", checked_at: new Date().toISOString(), channel: updateChannel }`;
  - clear `candidate`;
  - clear `errorMsg`;
  - clear `isInstalling` and `isHandoffPending`;
  - keep existing success logging and toast behavior.
- Prevent stale checks from resurrecting the old candidate.
  - If an update check returns `available` for the same version as the installed override, coerce UI state to current and leave `candidate` null.
  - If the real `currentVersion` prop later changes away from the pre-install version, clear the override and trust the real loaded version.
- Do not change backend installed metadata rules.
  - `record_update_install_requested` must still only save pending install metadata.
  - `installed_release_tag` must still be promoted only by startup reconciliation when loaded version matches.
- Do not change Decky installer argument order or public RPC shapes.
- Do not add new dependencies.

## Tests

Write failing tests before implementation.

- Extend `tests/test_frontend_static.py` to assert:
  - a shared post-install success helper exists and is called from both handoff success branches;
  - successful handoff clears candidate state;
  - successful handoff writes a `current` `checkResult`;
  - Installed Version rendering uses an effective current version override;
  - update checks use the effective version;
  - stale available results matching the installed override cannot restore the install button;
  - existing assertions for handoff timeout, fixed spinner slot, elapsed logging, installer API path, SHA-prefix privacy, and argument order still pass.
- Add backend tests only if backend behavior changes; the expected implementation should not require backend changes.

## Validation Commands

Run targeted checks during development:

```bash
./run.sh uv run pytest tests/test_frontend_static.py
./run.sh pnpm run typecheck
```

Run full validation before each commit that changes behavior:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh bash scripts/check_tdd.sh
./run.sh pnpm run verify
git diff --check
```

## Commit And Session Log

- Commit only after tests and checks pass.
- Use Conventional Commits, likely:
  - `fix(updater): reflect installed state after successful handoff`
- Add session log:
  - `docs/agent_conversations/2026-06-01_fix_updater_post_install_ui_state.json`
- Include objective, files modified, tests added, validation results, and review-cycle outcome.

## Subagent Review Prompt

After implementation and before the final review cycle, spawn a review subagent using this prompt:

```text
Act as a strict Principal Software Engineer reviewing the current branch of /home/beallio/Dropbox/Scripts/SDH-ludusavi.

Scope:
- Compare the working branch against main/base.
- Review only first-party project files.
- Focus on the updater post-install UI state fix.

Requirements to verify:
- After Decky installer handoff resolves successfully, the Updates panel no longer shows "Update available" or an install button for the just-installed version.
- Installed Version uses an optimistic effective version until the real backend currentVersion changes.
- Stale update-check responses cannot resurrect the old candidate after a successful handoff.
- Backend pending-install reconciliation remains authoritative and installed metadata is not promoted from the frontend.
- Decky installer argument order, SHA privacy, handoff timeout behavior, and existing updater logging are preserved.
- Tests are meaningful and cover the behavior change.
- No unrelated refactors, broad formatting churn, or upstream/package edits were introduced.

Output format:
- Start with either [REVIEW_PASSED] or [CRITICAL_FAILURE_DETECTED].
- If issues exist, list each finding with severity, file, line, impact, and exact remediation.
- If passed, summarize why the implementation satisfies the plan and mention residual manual Deck validation risk.
```

If the subagent reports findings, fix them with tests and commit the fixes before continuing.

## Final `codex review --base` Cycle

After the final implementation commit, run:

```bash
codex review --base
```

Use the same review standard as the subagent prompt: strict Principal Software Engineer, compare branch against base, first-party files only, updater post-install UI behavior.

Cycle rules:

- If `codex review --base` reports any issue with merit:
  - create or update a failing test where applicable;
  - fix the root cause;
  - rerun targeted and full validation;
  - commit the fix with a Conventional Commit;
  - rerun `codex review --base`.
- Continue until the review passes or only explicitly non-meritorious findings remain.
- Final response must report:
  - branch name;
  - commits created;
  - validation commands and results;
  - subagent review result;
  - final `codex review --base` result;
  - any manual Steam Deck validation still recommended.

## Assumptions

- "Successful update" means the Decky installer promise resolved without rejection.
- The chosen behavior is optimistic installed state immediately after success.
- Backend reconciliation on the next plugin load remains authoritative if the actual loaded version does not match.
- Implementation must not publish releases, push branches, or create tags unless separately instructed.
