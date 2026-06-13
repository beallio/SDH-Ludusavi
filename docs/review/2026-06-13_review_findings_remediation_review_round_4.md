# Review Round 4: Review Findings Remediation

Plan:

`docs/plans/2026-06-13_review_findings_remediation.md`

Reviewed branch:

`fix/review-findings-remediation`

Reviewed range:

`7ce6d56..574d162`

## Verdict

Approved.

The implementation meets the plan requirements.

## Singleton Identity Safety

Verified:

- `SiblingProcess` stores PID, UID, start ticks, and command-line bytes.
- Discovery captures a stable identity by reading start ticks before and after
  UID, command line, and process state.
- Discovery rejects malformed, changing, empty-command-line, and zombie
  entries.
- The current process identity is captured with the same stable mechanism.
- Older/newer ordering and equal-start-tick PID tie breaking remain intact.
- Cleanup operates on identity records rather than bare PIDs.
- Identity is revalidated before TERM, during waits, before KILL, and during
  the final wait.
- Reused or changed identities never receive a subsequent signal.
- `gone`, `changed`, and `running` remain distinct.
- Changed identities are reported as `skipped`.
- Gone identities are reported as `terminated` or `killed` according to the
  signal phase.
- Malformed runtime dataclass values are rejected without raising.
- Boolean PID/UID/start-tick values are not accepted as integers.
- Report lists preserve order and contain no duplicate PIDs.
- The guard's outer never-raise startup contract remains intact.

## Safety Cap

Verified:

- PID values `<= 1` are excluded.
- Incomplete identities do not consume the limit.
- Identities are deduplicated by `(pid, start_ticks)`.
- Candidates are sorted deterministically.
- Eight complete identities are allowed.
- More than eight complete identities are all refused.
- Refusal calls neither the signal callback nor sleep callback.
- `refused` contains the deterministic PID list.
- Logging includes the count and complete PID list.
- `enforce_single_instance` returns:

  ```text
  status: failed
  reason: too_many_stale_siblings
  ```

- Plugin startup continues.

## pyludusavi 0.2.6

Verified:

- `pyproject.toml` requires `pyludusavi>=0.2.6`.
- `uv.lock` resolves `pyludusavi==0.2.6`.
- No `0.2.5` package record or vendored dist-info directory remains.
- The package-specific `exclude-newer` exception is limited to
  `pyludusavi`.
- The user uv configuration remains active.
- No `UV_NO_CONFIG`, `UV_CONFIG_FILE`, or repository `uv.toml` was added.
- Vendored source matches the clean `0.2.6` wheel.
- Installer metadata, caches, and bytecode are excluded.
- The upstream `_DISCOVERY_VERIFY_TIMEOUT_SECONDS = 15.0` implementation is
  present.
- Both discovery subprocesses use the timeout.
- `subprocess.TimeoutExpired` is handled.
- The obsolete SDH-Ludusavi local patch marker is absent.
- Packaging and validation references use the `0.2.6` dist-info directory.
- The release ZIP contains `pyludusavi-0.2.6.dist-info` and `py.typed`.
- The release ZIP excludes `0.2.5`, installer files, caches, bytecode, and the
  release `debug` flag.

## Process and Evidence

Verified:

- Work was performed on `fix/review-findings-remediation`.
- The branch started from required commit `7ce6d56`.
- The plan was the first branch commit.
- Commits use Conventional Commit subjects.
- The worktree is clean.
- Initial invalid RED evidence is documented honestly.
- Round-1 and round-2 RED logs contain genuine behavioral failures.
- Round-specific GREEN commands disable inappropriate project-wide coverage.
- Full-suite coverage remains above the required threshold.
- Review resolutions and session logs are committed.
- Review rounds 1 through 3 end with their required status lines.
- The session log has concrete files, tests, design decisions, results, and
  commit SHAs.

## Validation Evidence

Confirmed across the implementation and review rounds:

- Ruff check passed.
- Ruff format check passed.
- `ty` passed.
- Final singleton suite: 42 passed.
- Final Python suite reported 603 passed at 85.82% coverage.
- Frontend suite: 162 passed.
- TypeScript passed.
- Frontend build passed.
- Frontend supply-chain verification passed.
- TDD policy script passed.
- `git diff --check` passed.
- Release ZIP build and validation passed.
- Session-log JSON validates with `UV_FROZEN=1`.

The reviewer's one observed packaging failure was caused by incorrectly
running `pytest` concurrently with `pnpm verify`, both of which rebuild
`dist/`. The isolated packaging test passed, and this was not an implementation
defect.

## Finalization Authorization

The implementation agent is authorized to perform the plan's finalization:

1. Commit this approval note if it is not already committed.
2. Confirm all review notes and the session log are committed.
3. Confirm the working branch is clean.
4. Run the complete validation suite sequentially.
5. Merge `fix/review-findings-remediation` into `dev` using the plan's
   non-fast-forward validation workflow.
6. Abort and return to review if merge validation fails.
7. Push `dev` and verify local/remote synchronization.
8. Delete the working branch safely.
9. Trigger the sanctioned `0.3.0` dev release for the exact merged commit.
10. Watch the GitHub Actions run to successful completion.
11. Verify the expected prerelease tag and ZIP, SHA-256, and manifest assets.
12. Create the exact zero-byte final marker only after all finalization checks
    succeed:

    ```text
    /tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_release_finished
    ```

STATUS: APPROVED
