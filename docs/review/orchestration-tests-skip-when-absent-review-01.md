# Review — orchestration-tests-skip-when-absent (round 01)

Branch: `feat/orchestration-tests-skip-when-absent`
Reviewed commit: `086eef1`
Reviewed against: `docs/plans/2026-06-19_orchestration-tests-skip-when-absent.md`

## Verdict

**APPROVED.** The change is correct, minimal, and exactly in scope.

`tests/test_orchestration_scripts.py` gains a module-level guard immediately after the
`ORCH` definition:

```python
pytestmark = pytest.mark.skipif(
    not (ORCH / "mark-finished").exists(),
    reason="orchestration scripts are a local-only symlink (../agent-orchestration); absent on CI runners",
)
```

`(ORCH / "mark-finished").exists()` follows the symlink, so the module's tests skip when
the orchestration scripts are absent (CI runners, clones without the sibling repo) and
run normally where they resolve.

## Scope

`git diff dev..HEAD` touches only `tests/test_orchestration_scripts.py` (+4 lines). No
runtime code, workflows, or other tests changed. Single atomic commit. No review notes
deleted.

## Gate status

- Commit `086eef1` was created through the pre-commit hook, which runs the full quality
  gate (`quality_gates.sh`) — it passed.
- Confirmed locally: `Path("scripts/orchestration/mark-finished").exists()` is `True`, so
  the guard does not skip; `pytest tests/test_orchestration_scripts.py` → 7 passed (not
  skipped). `ruff check` clean.
- Intent: the GitHub Actions dev-release / `ci.yml` pytest step will no longer fail on
  `test_orchestration_scripts.py` (verified after the dev push).

## Finalization instructions

Finalize exactly as the plan's Orchestration Contract specifies:

1. Confirm review notes are committed and the working tree is clean.
2. Run `scripts/orchestration/finalize orchestration-tests-skip-when-absent` — merges the
   branch into `dev`, cleans up the branch, pushes `dev`, and requests a dev release.
3. Confirm `/tmp/sdh_ludusavi/orchestration-tests-skip-when-absent_finalized` exists.
4. Stop polling and exit cleanly.

STATUS: APPROVED
