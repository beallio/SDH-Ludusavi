# Review Remediation and pyludusavi 0.2.6 Plan

## Summary

Authoritative file:

`docs/plans/2026-06-13_review_findings_remediation.md`

Plan name:

`2026-06-13_review_findings_remediation`

Working branch:

`fix/review-findings-remediation`

This plan addresses:

1. PID reuse during singleton cleanup.
2. Incorrect truncation of oversized sibling sets.
3. Re-vendoring newly published `pyludusavi==0.2.6`.

The existing user `uv.toml` safety policy must remain active. Do not add
`UV_NO_CONFIG`, `UV_CONFIG_FILE`, a repository `uv.toml`, or any equivalent
bypass.

## Implementation Protocol

The agent must:

- Use the `implementer` skill.
- Read `AGENTS.md`, `.protocol`, and this plan completely.
- Use `./run.sh` for project tooling.
- Keep caches and temporary files under `/tmp/sdh_ludusavi`.
- Use `ty` as the Python type checker.
- Follow strict Red-Green-Refactor TDD for behavior changes.
- Make atomic Conventional Commits.
- Preserve unrelated user changes.
- Never force-push or force-delete branches.

Start from the reviewed local `dev` commit `7ce6d56`:

```bash
git status --short
git switch dev
git rev-parse HEAD
git switch -c fix/review-findings-remediation
```

If `dev` no longer points to `7ce6d56`, inspect and review the additional
commits before proceeding.

Save and commit this plan before implementation:

```text
docs(plans): add review findings remediation plan
```

## Finding 1: Prevent Signals to Reused PIDs

### Problem

The current singleton cleanup retains only integer PIDs. A process may exit
after discovery, and Linux may reuse its PID before the cleanup sends
`SIGTERM` or `SIGKILL`.

Example:

1. PID `6270` is discovered with UID `1000`, start ticks `500`, and the plugin
   command line.
2. PID `6270` exits.
3. Another process receives PID `6270` with start ticks `900`.
4. Cleanup must not signal the replacement process.

### Identity Type

Add an immutable internal identity:

```python
@dataclass(frozen=True)
class SiblingProcess:
    pid: int
    uid: int
    start_ticks: int
    cmdline: bytes
```

Add:

```python
find_stale_siblings(...) -> list[SiblingProcess]
```

Keep:

```python
find_stale_sibling_pids(...) -> list[int]
```

as a compatibility wrapper only. The actual cleanup path must pass complete
`SiblingProcess` records.

Change:

```python
terminate_stale_siblings(pids: list[int], ...)
```

to operate on:

```python
terminate_stale_siblings(siblings: list[SiblingProcess], ...)
```

### Stable Identity Capture

Capture identities using this order:

1. Read start ticks from `/proc/<pid>/stat`.
2. Read UID.
3. Read command-line bytes.
4. Read process state.
5. Read start ticks again.
6. Accept the snapshot only if both start-tick reads match.

Reject entries when:

- Any required file is missing or malformed.
- Command line is empty.
- UID or start ticks cannot be read.
- Start ticks changed during capture.
- The process is already a zombie.

### Signal Rules

Immediately before every signal:

1. Re-read the complete identity.
2. Require matching PID, UID, start ticks, and command-line bytes.
3. Require a non-zombie state.
4. Signal only when every check passes.

The wait loop must track identities, not bare PIDs.

Classify each identity during polling as:

- `running`: exact identity still exists and is non-zombie.
- `gone`: the original identity disappeared or became a zombie.
- `changed`: the PID exists but the identity differs or cannot be safely
  verified.

Never send `SIGKILL` to a `changed` identity.

Do not add pidfd emulation, `ctypes`, raw system calls, or new dependencies.

### Cleanup Report

Return:

```python
{
    "terminated": list[int],
    "killed": list[int],
    "skipped": list[int],
    "failed": list[int],
    "refused": list[int],
}
```

Meanings:

- `terminated`: original identity disappeared after `SIGTERM`.
- `killed`: original identity disappeared after `SIGKILL`.
- `skipped`: identity changed or became unverifiable before a signal.
- `failed`: signaling failed unexpectedly or the same identity survived
  `SIGKILL`.
- `refused`: cleanup was rejected by the safety limit.

Each PID must appear at most once in each list.

`enforce_single_instance` must preserve its never-raise contract and must never
block plugin startup.

### Required Tests

Write failing tests before implementation for:

- PID reused before `SIGTERM`.
- PID reused between `SIGTERM` and `SIGKILL`.
- UID changes while waiting.
- Start ticks change while waiting.
- Command line changes while waiting.
- Malformed identity data while waiting.
- Unchanged identity receives `SIGTERM`, then `SIGKILL`.
- A process exiting on `SIGTERM` is not killed.
- Zombie and vanished processes are treated as gone.
- Existing older/newer ordering remains unchanged.
- Equal start ticks continue using PID as the tie breaker.
- The public PID-list wrapper remains compatible.
- `enforce_single_instance` never raises.

Capture RED output in:

`/tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_red.log`

## Finding 2: Refuse Oversized Match Sets

### Problem

The documented maximum is eight siblings, but the implementation currently
slices the list and signals the first eight.

Nine suspicious matches must result in zero signals, not eight signals.

### Required Behavior

Before applying the limit:

- Exclude PID values `<= 1`.
- Exclude incomplete identities.
- Deduplicate by `(pid, start_ticks)`.
- Sort deterministically by PID.

Then:

- Zero through eight valid identities may be processed.
- More than eight identities must all be refused.
- Do not call `kill_fn`.
- Do not call `sleep_fn`.
- Return every candidate PID in `refused`.
- Leave all other report lists empty.
- Log the count and complete PID list.
- Return `status: "failed"` and `reason: "too_many_stale_siblings"`.
- Continue plugin startup.

### Required Tests

Cover:

- Exactly eight identities are allowed.
- Nine identities are all refused.
- No signal or sleep occurs when refused.
- Invalid PIDs do not consume the limit.
- Duplicate identities do not consume the limit twice.
- The refusal report includes every valid candidate.
- The logger receives the count and PIDs.
- Plugin startup remains non-blocking.

## Re-Vendor pyludusavi 0.2.6

### Confirmed State

`pyludusavi 0.2.6` was published on June 13, 2026. The user's seven-day
`exclude-newer` policy intentionally filters it.

The override must therefore be:

- Explicit.
- Limited to `pyludusavi`.
- Limited to commands performing this requested upgrade.
- Retained in the generated lock metadata as needed.
- Never generalized to other dependencies.

### Temporary Wheel Retrieval

Create a unique staging directory:

```bash
VENDOR_ROOT="$(mktemp -d /tmp/sdh_ludusavi/pyludusavi-0.2.6.XXXXXX)"
```

Download the exact wheel:

```bash
./run.sh uv pip install \
  --target "$VENDOR_ROOT" \
  --no-deps \
  --refresh-package pyludusavi \
  --exclude-newer-package "pyludusavi=2026-06-14T00:00:00Z" \
  "pyludusavi==0.2.6"
```

Verify before copying:

```bash
grep -Fx "Version: 0.2.6" \
  "$VENDOR_ROOT/pyludusavi-0.2.6.dist-info/METADATA"
```

### Vendor Replacement

Replace:

```text
py_modules/pyludusavi/
py_modules/pyludusavi-0.2.5.dist-info/
```

with:

```text
py_modules/pyludusavi/
py_modules/pyludusavi-0.2.6.dist-info/
```

Copy only wheel-owned package and dist-info contents.

Do not copy:

```text
.lock
INSTALLER
REQUESTED
__pycache__/
*.pyc
```

After copying, compare the vendored source to the downloaded source. There
must be no source differences.

### Upstream Timeout Fix

Version `0.2.6` upstreamed the local discovery timeout using:

```python
_DISCOVERY_VERIFY_TIMEOUT_SECONDS = 15.0
```

The clean upstream source:

- Passes the timeout to both discovery verification subprocesses.
- Catches `subprocess.TimeoutExpired`.

Therefore:

- Do not reapply the old local patch.
- Remove the `SDH-Ludusavi local patch` marker naturally by using the clean
  wheel.
- Replace the local-patch guard test with an upstream-behavior guard.
- Assert the 15-second constant exists.
- Assert both subprocess calls use it.
- Assert `TimeoutExpired` is handled.
- Assert the old local patch marker is absent.

### Version Updates

Update all current hard-coded `0.2.5` references, including:

- `pyproject.toml`
- `uv.lock`
- `scripts/package_plugin.py`
- `scripts/validate_plugin_zip.py`
- `tests/test_ludusavi.py`
- `tests/test_protocol.py`
- `tests/test_package_plugin.py`
- `tests/test_validate_plugin_zip.py`

Set:

```toml
"pyludusavi>=0.2.6"
```

Ensure exactly one vendored dist-info directory remains.

### Lock Update

Do not alter `run.sh`, `.envrc`, `[tool.uv]`, or the user's uv configuration.

Generate the lock with the narrow override:

```bash
./run.sh uv lock \
  --upgrade-package pyludusavi \
  --refresh-package pyludusavi \
  --exclude-newer-package "pyludusavi=2026-06-14T00:00:00Z"
```

The lock must:

- Resolve `pyludusavi==0.2.6`.
- Contain the correct wheel and source hashes.
- Update the project requirement to `>=0.2.6`.
- Contain no `0.2.5` package entry.
- Retain only the package-specific exception needed for `pyludusavi`.
- Avoid unrelated dependency upgrades.

Do not remove or bypass the global seven-day policy.

Until `0.2.6` naturally passes the seven-day cutoff, use:

```bash
UV_FROZEN=1 ./run.sh uv run ...
```

For commits whose hooks invoke uv, use:

```bash
UV_FROZEN=1 git commit ...
```

This allows the existing lock to be consumed without asking uv to re-resolve
it against the still-active cutoff.

### Required Re-Vendor Tests

Verify:

- `pyludusavi.__version__ == "0.2.6"`.
- Exactly one dist-info directory exists.
- It is `pyludusavi-0.2.6.dist-info`.
- `METADATA` reports `Version: 0.2.6`.
- The pyproject requirement matches the vendored version.
- Packaging requires the `0.2.6` dist-info directory.
- ZIP validation accepts `0.2.6`.
- `0.2.5` is absent from the package.
- `py.typed` remains included.
- The clean upstream discovery timeout remains intact.
- The old local patch marker is absent.

## Validation

Run the final gates with the lock frozen while the seven-day policy still
excludes `0.2.6`:

```bash
UV_FROZEN=1 ./run.sh uv sync
UV_FROZEN=1 ./run.sh uv run ruff check . --fix
UV_FROZEN=1 ./run.sh uv run ruff format .
UV_FROZEN=1 ./run.sh uv run ty check py_modules/sdh_ludusavi/
UV_FROZEN=1 ./run.sh uv run pytest
./run.sh pnpm run test
./run.sh pnpm run build
./run.sh pnpm run verify
UV_FROZEN=1 ./run.sh bash scripts/check_tdd.sh
git diff --check
```

Build and validate a release ZIP. Confirm:

- `pyludusavi-0.2.6.dist-info` is included.
- `pyludusavi-0.2.5.dist-info` is absent.
- `py.typed` is included.
- No installer metadata, caches, or bytecode are included.
- Release `plugin.json` has the debug flag removed.

Create:

`docs/agent_conversations/2026-06-13_review_findings_remediation.json`

Record:

- Objective and branch.
- Process-identity design.
- Safety-limit behavior.
- `pyludusavi 0.2.6` upload-age override.
- Confirmation that the user uv policy was preserved.
- Removal of the obsolete local discovery patch.
- RED and GREEN commands.
- Full validation results.
- Commit SHAs.

Suggested commits:

```text
docs(plans): add review findings remediation plan
fix(singleton): bind cleanup signals to process identities
fix(singleton): refuse oversized sibling match sets
chore(deps): re-vendor pyludusavi 0.2.6
docs(agent): record review findings remediation session
```

## Completion Markers

After implementation is committed, all validation passes, and the branch is
clean, create this exact zero-byte file:

```text
/tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_finished
```

Use:

```bash
mkdir -p /tmp/sdh_ludusavi
: > /tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_finished
test ! -s /tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_finished
```

Do not use `echo`.

## Review Loop

After creating the marker, poll every 60 seconds for:

```text
/home/beallio/Dropbox/Scripts/SDH-ludusavi/docs/review/2026-06-13_review_findings_remediation_review_round_<N>.md
```

The reviewer writes these files inside the project repository. Review notes
must never be placed only under `/tmp`.

A review note is complete only when its final nonblank line is exactly:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

If the file is missing or incomplete, sleep for 60 seconds and check again.
Silence is not approval.

For `CHANGES_REQUESTED`:

1. Address every finding.
2. Use RED-GREEN TDD for behavior changes.
3. Run targeted and full validation.
4. Commit fixes atomically.
5. Append resolutions, tests, and commit SHAs to the review note.
6. Commit the review note if it is not already committed.
7. Create this zero-byte marker:

```text
/tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_review_round_<N>_finished
```

8. Poll for round `<N+1>`.

For `APPROVED`:

1. Commit the approval note if necessary.
2. Confirm no review note remains unresolved.
3. Begin finalization.

## Finalization

1. Confirm all review notes and the session log are committed.
2. Confirm the working branch is clean.
3. Run the complete validation suite.
4. Switch to `dev`.
5. Confirm `dev` has no unexpected changes.
6. Start a noncommitted merge:

```bash
git merge --no-ff --no-commit fix/review-findings-remediation
```

7. Run the complete validation suite against the pending merge.
8. If validation fails, abort the merge, fix the branch, and require another
   review.
9. If validation passes, create the merge commit.
10. Push `dev`:

```bash
git push origin dev
```

11. Verify local and remote `dev` SHAs match.
12. Delete the local branch using:

```bash
git branch -d fix/review-findings-remediation
```

13. Delete a remote working branch only if one was pushed. Never use force
    deletion.
14. Read matching base versions from `package.json` and `plugin.json`;
    currently `0.3.0`.
15. Trigger the dev release for the exact merged commit:

```bash
./scripts/request_dev_release.sh 0.3.0 "$(git rev-parse HEAD)"
```

16. Find and watch the matching GitHub Actions run:

```bash
gh run watch <run-id> --exit-status
```

17. Verify the expected `v0.3.0-dev.g<shortsha>` prerelease with
    `gh release view`.
18. Confirm the versioned ZIP, SHA-256 file, and manifest exist.
19. Do not manually push a tag or upload release assets.
20. Create the final zero-byte marker only after release verification:

```text
/tmp/sdh_ludusavi/2026-06-13_review_findings_remediation_release_finished
```

## Explicit Assumptions

- The implementation starts from local `dev` commit `7ce6d56`.
- Both singleton findings and the re-vendor use one working branch.
- `pyludusavi 0.2.6` is intentionally allowed despite its publication age.
- No other recently published dependency is exempted.
- The user's `uv.toml` remains active and unchanged.
- `UV_FROZEN=1` is temporary validation plumbing, not a repository
  configuration change.
- The package-specific lock exception may remain until the version naturally
  ages past the policy.
- No frontend or RPC interface changes are required.
- Singleton cleanup failure must never prevent plugin startup.
- Review approval must be explicit and repository-resident.
- Failed validation, push, workflow, or release verification means the task
  remains incomplete.
