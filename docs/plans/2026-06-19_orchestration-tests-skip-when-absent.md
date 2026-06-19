# Skip Orchestration Script Tests When Absent

```text
TITLE=Skip Orchestration Script Tests When Absent
SLUG=orchestration-tests-skip-when-absent
PLAN_PATH=docs/plans/2026-06-19_orchestration-tests-skip-when-absent.md
```

## Context

The GitHub Actions **dev-release** workflow (and `ci.yml`, which runs the same full
pytest suite) fails on `dev` at the Pytest step with 7 `FileNotFoundError`s in
`tests/test_orchestration_scripts.py` — e.g. `scripts/orchestration/start-implementer`,
`review-status`, `mark-finished`.

Root cause: `scripts/orchestration` is a git-tracked **symlink** (mode `120000`) →
`../../agent-orchestration/orchestration`. That sibling repo exists on the developer
machine (so the suite passes locally) but is **absent on CI runners**, leaving the
symlink dangling. Those scripts are local-only developer tooling and are not part of the
shipped plugin, so there is nothing for CI to test there.

Fix: make `tests/test_orchestration_scripts.py` skip itself when the orchestration
scripts are not present, so the suite is green on CI and on any clone without the sibling
repo, while still running locally where the scripts resolve. This is a test-only change
with no runtime behavior, so strict TDD does not apply.

You are the implementer. Develop on a branch off `dev`. Do not write reviews. Do not
create, delete, or edit anything under `docs/review/` except committing review notes the
orchestrator writes there.

## Orchestration Contract

Plan path:
```text
docs/plans/2026-06-19_orchestration-tests-skip-when-absent.md
```
Implementation branch:
```text
feat/orchestration-tests-skip-when-absent
```
Round-complete marker:
```text
/tmp/sdh_ludusavi/orchestration-tests-skip-when-absent_finished
```
Finalized marker:
```text
/tmp/sdh_ludusavi/orchestration-tests-skip-when-absent_finalized
```
Review notes (audit records — committed, never deleted/edited by you):
```text
docs/review/orchestration-tests-skip-when-absent-review-*.md
```

Each review note ends with exactly one of `STATUS: CHANGES_REQUESTED` or `STATUS: APPROVED`.

**Setup:** Use the `implementer` skill. Create `feat/orchestration-tests-skip-when-absent`
off `dev`. The plan is already committed on `dev`; proceed with the change.

**On completing a round (initial implementation or a review round):**
1. Run the quality gates (below).
2. Ensure the working tree is clean.
3. Commit all relevant changes (Conventional Commits).
4. Write the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished orchestration-tests-skip-when-absent
   ```
5. Exit cleanly. The orchestrator resumes you via `continue-implementer` once the next
   review note is committed. On every resume, scan existing committed review notes first.

**When a `STATUS: CHANGES_REQUESTED` note appears:**
1. `scripts/orchestration/clear-finished orchestration-tests-skip-when-absent`
2. Read the note (use `git show HEAD:docs/review/...`); implement every requested change.
3. Run quality gates; commit the fixes.
4. Commit the review note if not already committed.
5. `scripts/orchestration/mark-finished orchestration-tests-skip-when-absent`
6. Exit cleanly.

**When a `STATUS: APPROVED` note appears:**
1. Confirm all review notes are committed and the working tree is clean.
2. `scripts/orchestration/finalize orchestration-tests-skip-when-absent`
3. Confirm `/tmp/sdh_ludusavi/orchestration-tests-skip-when-absent_finalized` exists.
4. Stop polling and exit. (Finalize merges the branch into `dev`, cleans up the branch,
   pushes `dev`, and requests a dev release.)

## The change

File: `tests/test_orchestration_scripts.py`

The module already imports `pytest` and defines
`ORCH = Path(__file__).resolve().parents[1] / "scripts" / "orchestration"` (line 17).
Add a module-level skip guard immediately after the `ORCH` definition:

```python
pytestmark = pytest.mark.skipif(
    not (ORCH / "mark-finished").exists(),
    reason="orchestration scripts are a local-only symlink (../agent-orchestration); absent on CI runners",
)
```

`(ORCH / "mark-finished").exists()` follows the symlink and returns `False` when the
target is missing (CI), so all tests in the module skip there; locally the scripts
resolve and the tests run unchanged.

Do not modify any other file. Do not vendor the scripts. Do not change the workflows.

## Quality Gates (run before every `mark-finished`)

```bash
./run.sh bash scripts/quality_gates.sh check
```

(Equivalently: `./run.sh uv run ruff check . --fix`, `ruff format .`, `ty check
py_modules/sdh_ludusavi/`, `pytest`, `./run.sh pnpm run verify`.) All must pass. Caches/
venv stay under `/tmp/sdh_ludusavi/` via `./run.sh`.

## Verification

- `./run.sh uv run pytest tests/test_orchestration_scripts.py` still passes locally
  (scripts present → tests run, not skipped).
- Simulate CI absence to confirm the guard skips rather than errors, e.g.:
  ```bash
  ./run.sh uv run python -c "import pathlib; print((pathlib.Path('scripts/orchestration/mark-finished')).exists())"
  ```
  must print `True` locally; the `skipif` triggers only when it would be `False`.
- Full suite green via the quality gate.
- The intent is that the GitHub Actions dev-release/`ci.yml` pytest step no longer fails
  on `test_orchestration_scripts.py` (verified after the dev push).

## Constraints
- One coherent commit (Conventional Commits, e.g. `test(orchestration): skip script tests when absent`).
- Test-only change; no runtime behavior, no new dependencies.
- Touch only `tests/test_orchestration_scripts.py`.
- Do not create, delete, or edit files under `docs/review/` except to commit review notes
  the orchestrator writes there.
