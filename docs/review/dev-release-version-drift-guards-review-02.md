# Review — dev-release-version-drift-guards (round 02)

Branch reviewed: `feat/dev-release-version-drift-guards`
Commit reviewed: `c42bc3d` (round-complete marker stamped at this SHA)
Plan reviewed against: `docs/plans/2026-06-19_dev-release-version-drift-guards.md`

## Verdict

APPROVED. Guards A and C are implemented correctly on a single canonical helper, the
round-01 blocking finding is resolved, and all gates are green. Cleared to finalize.

## Gate status

All green at `c42bc3d` (`./run.sh bash scripts/quality_gates.sh check`):
- ruff check + format-check: pass
- ty: pass
- pytest: pass (incl. `tests/test_version_guard.py`, the stale-base rejection test, and the
  Task-C drift test)
- frontend `pnpm run verify`: vitest 227 passed (28 files), tsc clean

## Delivered

- **Task 0 — `scripts/version_guard.py`**: single source of truth for "version must be
  strictly ahead of the highest released stable tag". `parse_semver` rejects non-stable
  input; `highest_stable_version` ignores `-dev`/pre-release tags and returns `None` when
  none exist; `is_base_ahead_of_stable` is strict-greater and treats "no stable tags" as
  allowed; `check-base` CLI emits an actionable message. Red-first unit tests in
  `tests/test_version_guard.py`.
- **Task A — dispatch-time guards**: `scripts/request_dev_release.sh` calls the helper before
  dispatch (`test_request_dev_release_rejects_behind_stable` proves base `0.3.1` vs stable
  `v0.3.2` refuses with no `gh workflow run`; happy-path tests still dispatch).
  `.github/workflows/dev-release.yml` performs the same server-side re-check, now via
  `python3` (round-01 fix), guarded by the workflow-content assertion.
- **Task C — CI drift assertion**: `tests/test_version_config.py::test_dev_version_ahead_of_stable`
  asserts the declared version is strictly ahead of the highest stable tag, skipping cleanly
  when no stable tags are reachable.
- Guard B left unimplemented (scoping doc `docs/plans/2026-06-19_dev-release-auto-merge-back.md`
  only), as required.

## Prior findings — resolved

- **Round-01 (bare `python` before toolchain in `dev-release.yml`):** resolved in `c42bc3d`
  — line 79 now `python3 scripts/version_guard.py check-base ...`, and the workflow-content
  assertion in `tests/test_release_workflows.py` was updated to the `python3` form so the
  guard cannot silently regress.

## Finalization instructions

1. Confirm all review notes are committed and the tree is clean.
2. Run `scripts/orchestration/finalize dev-release-version-drift-guards`.
3. Confirm `/tmp/sdh_ludusavi/dev-release-version-drift-guards_finalized` exists.
4. Stop polling and exit. Finalize merges `feat/dev-release-version-drift-guards` into `dev`,
   cleans up the branch, pushes `dev`, and requests a dev release.

Note: `dev` is currently at `0.3.3` and the highest stable tag is `v0.3.2`, so the new
guards are satisfied and the finalize dev release should succeed as `v0.3.3-dev.g<sha>`.

STATUS: APPROVED
