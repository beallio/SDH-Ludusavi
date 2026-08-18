# Review — fail-safe-autosync-timeouts (round 02)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 2's implementation is accepted. Commit `d04caf5` applies the requested three-minute
operation and preview ceilings, derives the four-minute watchdog boundary from the larger
timeout, changes the status cleanup boundary to 210 seconds, removes every Task 1 expected-
failure wrapper, and keeps the independent Syncthing monitoring constants unchanged. The
required 900-second negative control failed both the direct and derived assertions before
the correct implementation was restored.

One mechanical plan defect is blocking the next round: the three focused Python commands in
`## Verification` inherit `pyproject.toml`'s repository-wide `--cov-fail-under=83`. The
focused timeout suite passed all 35 assertions during review but exited nonzero because a
small subset covers only 3.76% of the whole package. The full quality gate remains the place
where the 83% project threshold must be enforced.

## Gate status

- Implementer full quality gate: passed after the module-size comment correction.
- Implementer negative control: passed by failing at `900.0`/`960.0`, then restoring GREEN.
- Reviewer Python focus: 35 assertions passed; command exit was correctly nonzero only due
  to the unrelated global coverage threshold (`3.76% < 83%`).
- Reviewer frontend focus: 1 file and 10 tests passed.
- Reviewer TypeScript typecheck: passed.
- `git diff --check`: passed; worktree was clean before this review note.
- Round marker: valid for `d04caf5c56b04a9c0a675a59f4eefacbb1f76b91`.

## Required changes

1. In the plan's three focused Python verification commands, place `-o addopts=''` after
   `pytest`, for example:

   ```bash
   ./run.sh uv run pytest -o addopts='' tests/test_constants.py tests/test_ludusavi.py tests/test_ludusavi_executor.py
   ```

   Apply the same exact option to the coordinator/watchdog and lifecycle/service/main
   focused commands. Do not change the final `scripts/orchestration/run-quality-gates`
   command or the project coverage configuration.
2. Run one currently available corrected focused command and confirm it exits zero, then
   commit the plan correction as a small review fix.
3. Continue with Task 3 only: add the managed-executor RED tests, capture their real failure,
   keep production code untouched, run the full quality gate with strict expected failures,
   commit the tests, and mark the round complete.

Do not begin Task 4 in this round.

STATUS: CHANGES_REQUESTED
