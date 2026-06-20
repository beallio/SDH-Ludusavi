# Review — dev-release-version-drift-guards (round 01)

Branch: `feat/dev-release-version-drift-guards`
Commit reviewed: `2769387` (round-complete marker stamped at this SHA)
Reviewed against: `docs/plans/2026-06-19_dev-release-version-drift-guards.md`

## Verdict

CHANGES_REQUESTED. The design is right and almost entirely correct — Task 0 (canonical
helper), Task A (both guard sites), and Task C (CI assertion) are all implemented with
meaningful tests, and gates are green. One blocking correctness issue remains in the
workflow guard: it invokes a bare `python` in a step that runs before toolchain setup,
which can block all dev releases on a runner that lacks a `python` symlink.

## Gate status

All green at `2769387` (`./run.sh bash scripts/quality_gates.sh check`):
- ruff check + format-check: pass
- ty: pass
- pytest: pass (incl. new `tests/test_version_guard.py`, the stale-base rejection test, and
  the Task-C drift test)
- frontend `pnpm run verify`: vitest 227 passed (28 files), tsc clean

## What is correct (no action needed)

- **Task 0 — `scripts/version_guard.py`**: clean single-source-of-truth rule. `parse_semver`
  rejects non-stable input; `highest_stable_version` ignores `-dev`/pre-release tags and
  returns `None` when there are none; `is_base_ahead_of_stable` is strict-greater and treats
  "no stable tags" as allowed. `check-base` CLI prints an actionable message. Strong
  red-first unit tests in `tests/test_version_guard.py`.
- **Task A — `scripts/request_dev_release.sh`**: calls the helper via `./run.sh uv run
  python` after the existing checks, before dispatch; existing behavior preserved. New
  `test_request_dev_release_rejects_behind_stable` exercises the real helper through mocked
  `git`/`gh` (base `0.3.1` vs stable `v0.3.2` → refuses, no `gh workflow run`); the happy-
  path tests were correctly updated to mock `git tag` returning no higher stable tag so they
  still dispatch.
- **Task C — `tests/test_version_config.py::test_dev_version_ahead_of_stable`**: reads the
  declared version via `validate_package_versions`, skips cleanly when no stable tags are
  reachable, and asserts strict-ahead otherwise. Passes on the current repo (`0.3.3 > 0.3.2`).
- Both plan docs committed; Guard B correctly left unimplemented (scoping doc only).

## Required changes (blocking)

1. **`.github/workflows/dev-release.yml` (line ~79): use `python3`, not bare `python`.**
   The new check `if ! python scripts/version_guard.py check-base ...` runs inside the
   "Check if Dev Tag Already Exists" step, which executes **before** "Setup Toolchain"
   (line ~84). Every other Python call in this workflow uses `./run.sh uv run python` and
   runs *after* toolchain setup; this one relies on the runner's system interpreter. On
   GitHub `ubuntu-latest`, `python3` is guaranteed but a bare `python` symlink is not. Worse,
   because of the `! python ...` construct, a missing `python` makes the step exit non-zero —
   i.e. a missing interpreter would be indistinguishable from "drift detected" and would
   **block every dev release dispatched through the workflow**. The helper is stdlib-only, so
   `python3` is a drop-in. Change the invocation to:
   ```yaml
   if ! python3 scripts/version_guard.py check-base "${{ env.BASE_VERSION }}"; then
   ```
   (Alternatively, move the check after "Setup Toolchain" and use `./run.sh uv run python`
   for full consistency — but the simple `python3` swap keeps the desirable fast-fail
   ordering before toolchain.)

2. **Update the workflow-content assertion to match, so this can't regress.**
   `tests/test_release_workflows.py::test_workflows_trigger_and_overwrite_and_checksum_verification`
   currently asserts `"python scripts/version_guard.py check-base" in dev_content`. After the
   fix to `python3`, that substring no longer matches (the `3` breaks it). Update the
   assertion to the `python3 scripts/version_guard.py check-base` form so the guard remains
   regression-protected and the test stays green.

## How to proceed

Apply both changes, run the quality gates, ensure the tree is clean, commit, commit this
review note, then re-run `scripts/orchestration/mark-finished dev-release-version-drift-guards`.

STATUS: CHANGES_REQUESTED
