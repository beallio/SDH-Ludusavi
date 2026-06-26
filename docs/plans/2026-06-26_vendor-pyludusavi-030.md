# Plan: Vendor pyludusavi 0.3.0 and Cut Dev Release (vendor-pyludusavi-030)

## Context

`pyludusavi` 0.3.0 was published to PyPI on 2026-06-26. The plugin currently pins and
**vendors** 0.2.6. `pyludusavi` is consumed two ways:

1. A normal uv dependency (`pyproject.toml` / `uv.lock`), used in tests/dev.
2. **Vendored** into `py_modules/pyludusavi/` plus `py_modules/pyludusavi-0.2.6.dist-info/`
   so the Decky runtime can import it (Decky loads backend Python from `py_modules/`).

Goal: re-vendor 0.3.0, bump every hard-coded `0.2.6` reference, re-lock, and pass all
quality gates. The dev release that follows is **not your job** — the orchestration
`finalize` step merges this branch into `dev`, pushes, and its `finalize-release` hook
runs `scripts/request_dev_release.sh` automatically using the existing `0.3.5` version in
`package.json`. Do not bump `package.json`/`plugin.json` and do not call
`request_dev_release.sh` yourself.

### What changed in 0.3.0 (verified by diffing the 0.2.6 vs 0.3.0 wheels)

- `main.py`: removed the `add_game_alias(...)` method and its `import json`.
- `discovery.py`: collapsed the two env-conditional `subprocess.run("--version")` calls
  into a single call that always passes `env`; removed the `path is None ->
  shutil.which` early return. The `_DISCOVERY_VERIFY_TIMEOUT_SECONDS = 15.0` constant and
  the `subprocess.TimeoutExpired` handling are retained.
- `models.py`: `ApiErrorDetails` switched from `total=False` to explicit `NotRequired[...]`.
- **No public API the plugin relies on changed.** `py_modules/sdh_ludusavi/` never calls
  `add_game_alias` — its `aliases` concept (`registry.py`, `matcher.py`) is an unrelated
  internal cache. So **no `py_modules/sdh_ludusavi/` adapter code changes are needed.**

### Relevant existing procedure

`docs/plans/2026-06-13_review_findings_remediation.md` (section "Re-Vendor pyludusavi
0.2.6") documents the prior re-vendor steps; reuse them swapping 0.2.6 -> 0.3.0. The
global `~/.config/uv/uv.toml` already sets `exclude-newer-package = { pyludusavi = false }`,
so 0.3.0 resolves **without** any `--exclude-newer-package` flag.

**Slug used throughout this plan:** `vendor-pyludusavi-030`

---

## Orchestration Contract

**Slug:** `vendor-pyludusavi-030`

**Plan file:**

```text
docs/plans/2026-06-26_vendor-pyludusavi-030.md
```

**Implementation branch:**

```text
feat/vendor-pyludusavi-030
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/vendor-pyludusavi-030_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/vendor-pyludusavi-030_finalized
```

**Review notes:**

```text
docs/review/vendor-pyludusavi-030-review-*.md
```

Each review note ends with exactly one status trailer:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

---

## Required Agent Protocol

1. Use the **implementer** skill.
2. Work from the repository root.
3. Branch from `dev`.
4. Commit this plan as the first commit on the implementation branch.
5. Follow TDD where behavior changes are testable.
6. Run quality gates before marking any round complete.
7. Do not write your own review.
8. Do not create files under `docs/review/`.
9. Do not delete files under `docs/review/`.
10. Review notes are durable audit records and must be committed.
11. Resolving a review note means:
    - implement the requested changes;
    - run quality gates;
    - commit the code/docs changes;
    - commit the review note itself if it is not already committed;
    - recreate the round-complete marker.
12. After finalization, stop polling and exit cleanly.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/vendor-pyludusavi-030
```

Commit this plan first:

```bash
git add docs/plans/2026-06-26_vendor-pyludusavi-030.md
git commit -m "docs(plan): add vendor-pyludusavi-030 implementation plan"
```

---

## Implementation Tasks

### Task 1 — TDD (RED): update version-asserting tests to expect 0.3.0

Change these tests first so they fail against the still-vendored 0.2.6, then pass after
re-vendoring. Run `./run.sh uv run pytest` after editing to confirm they fail.

- `tests/test_vendored_pyludusavi.py` — in `test_upstream_timeout_behavior_present`,
  change the assertion
  `content.count("timeout=_DISCOVERY_VERIFY_TIMEOUT_SECONDS") == 2` to `== 1`.
  0.3.0 has a single subprocess call, so the constant is passed once. Leave the other
  assertions in that test unchanged (constant present, `subprocess.TimeoutExpired`
  handled, no `SDH-Ludusavi local patch` marker) — all still hold in 0.3.0.
- `tests/test_ludusavi.py` — `assert pyludusavi.__version__ == "0.2.6"` ->
  `== "0.3.0"`.
- `tests/test_validate_plugin_zip.py` — both occurrences of
  `pyludusavi-0.2.6.dist-info` (around lines 113 and 147) -> `pyludusavi-0.3.0.dist-info`.
- `tests/test_protocol.py` — `py_modules/pyludusavi-0.2.6.dist-info/licenses/LICENSE` ->
  `pyludusavi-0.3.0.dist-info`.
- `tests/test_package_plugin.py` — `py_modules/pyludusavi-0.2.6.dist-info` ->
  `pyludusavi-0.3.0.dist-info`.

### Task 2 — Re-vendor pyludusavi 0.3.0 (GREEN for source)

Download the exact wheel into a staging dir and verify the version:

```bash
VENDOR_ROOT="$(mktemp -d /tmp/sdh_ludusavi/pyludusavi-0.3.0.XXXXXX)"
./run.sh uv pip install --target "$VENDOR_ROOT" --no-deps \
  --refresh-package pyludusavi "pyludusavi==0.3.0"
grep -Fx "Version: 0.3.0" "$VENDOR_ROOT/pyludusavi-0.3.0.dist-info/METADATA"
```

Replace the vendored package source:

- Overwrite every file in `py_modules/pyludusavi/` with the staged 0.3.0 package files:
  `__init__.py`, `core.py`, `discovery.py`, `main.py`, `models.py`, `_environment.py`,
  `_version.py`, `py.typed`. Copy wheel-owned files only.
- `git rm -r py_modules/pyludusavi-0.2.6.dist-info` and create
  `py_modules/pyludusavi-0.3.0.dist-info/` containing the staged `METADATA`, `RECORD`,
  `WHEEL`, and `licenses/LICENSE`. Do **not** copy `INSTALLER`, `REQUESTED`, `.lock`,
  `__pycache__/`, or `*.pyc`.

Verify the vendored source is byte-identical to the staged wheel source, e.g.:

```bash
diff -r py_modules/pyludusavi "$VENDOR_ROOT/pyludusavi"
```

There must be exactly one `py_modules/pyludusavi-*.dist-info` directory afterward
(enforced by `test_exactly_one_dist_info`).

### Task 3 — Bump remaining hard-coded references

- `pyproject.toml` — `"pyludusavi>=0.2.6"` -> `"pyludusavi>=0.3.0"`.
- `scripts/package_plugin.py` — `py_modules/pyludusavi-0.2.6.dist-info` -> `...-0.3.0...`
  (in `REQUIRED_DIRECTORIES`).
- `scripts/validate_plugin_zip.py` — `py_modules/pyludusavi-0.2.6.dist-info/` ->
  `...-0.3.0.dist-info/`.

Do **not** hand-edit `uv.lock`; it is regenerated next.

### Task 4 — Re-lock and sync

```bash
./run.sh uv lock --upgrade-package pyludusavi --refresh-package pyludusavi
./run.sh uv sync
```

Confirm `uv.lock` now lists `pyludusavi` 0.3.0 with the 0.3.0 sdist/wheel hashes. The
global uv config exempts pyludusavi from the 7-day `exclude-newer`, so no extra flags are
needed. If an unrelated locking error about freshness appears, retry with `UV_FROZEN=1`
prefixed; do not broaden the upgrade to other packages.

---

## Quality Gates

Run before marking any round complete:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

The round is not complete unless:

1. all requested implementation work is done;
2. all relevant tests pass;
3. build/typecheck gates pass;
4. review notes have not been deleted;
5. the working tree is clean;
6. all code/docs changes are committed.

---

## Verification

1. `./run.sh uv run pytest` is fully green, including:
   - `tests/test_vendored_pyludusavi.py` — one dist-info, pin matches vendored 0.3.0,
     timeout constant passed once.
   - `tests/test_ludusavi.py::test_pyludusavi_version_is_current` — `__version__ == "0.3.0"`.
2. `grep -rn "0\.2\.6" pyproject.toml scripts/ tests/ py_modules/pyludusavi*` returns
   nothing. (Historical mentions remain only under `docs/plans/`, which is intentional and
   must be left alone.)
3. `ls py_modules/pyludusavi-*.dist-info` shows exactly `pyludusavi-0.3.0.dist-info`.
4. `./run.sh uv run python scripts/version_guard.py check-base 0.3.5` passes.
5. The full quality-gate hook passes via `scripts/orchestration/run-quality-gates`
   (frontend `pnpm test` + `pnpm run build`, plus ruff/ty/pytest).

**Deferred verification:** The actual dev prerelease (`v0.3.5-dev.SHORTSHA`) is produced
by GitHub Actions after `finalize` invokes the `finalize-release` hook; its success is
observed by the orchestrator post-finalize, not in this round. On-device Decky runtime
import of the vendored 0.3.0 package is not exercised here.

### Scope guard

Leave the untracked `docs/prompt_templates/` directory and any other unrelated
uncommitted work untouched. Stage only the files this plan changes. Do not run broad
formatting that would rewrite unrelated files.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished vendor-pyludusavi-030
```

This writes:

```text
/tmp/sdh_ludusavi/vendor-pyludusavi-030_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer vendor-pyludusavi-030`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/vendor-pyludusavi-030-review-*.md
```

When a review note exists or a new review note appears:

1. Read the full review note.
2. If the note ends with:

   ```text
   STATUS: CHANGES_REQUESTED
   ```

   then resume work.

3. Clear the round-complete marker:

   ```bash
   scripts/orchestration/clear-finished vendor-pyludusavi-030
   ```

4. Address every requested change.
5. Run quality gates:

   ```bash
   scripts/orchestration/run-quality-gates
   scripts/orchestration/check-review-notes-not-deleted
   ```

6. Commit code/docs fixes.
7. Commit the review-note file itself if it is not already committed:

   ```bash
   git add docs/review/vendor-pyludusavi-030-review-*.md
   git commit -m "docs(review): record vendor-pyludusavi-030 review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished vendor-pyludusavi-030
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer vendor-pyludusavi-030` after the next review note is created.

---

## Approval Handling

If the latest review note ends with:

```text
STATUS: APPROVED
```

then:

1. Confirm every previous review item has been addressed.
2. Confirm all review notes are committed:

   ```bash
   scripts/orchestration/check-review-notes-committed vendor-pyludusavi-030
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize vendor-pyludusavi-030
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/vendor-pyludusavi-030_finalized
   ```

6. Stop polling and exit cleanly.

---

## Review Rules

Do not write your own review.

Do not create files under:

```text
docs/review/
```

Do not delete files under:

```text
docs/review/
```

Only the orchestrator writes review notes. Your job is to read them, resolve them, commit them as audit records, and continue the loop.

---

## Finalization Rules

Only finalize after a review note with:

```text
STATUS: APPROVED
```

Finalization is performed with:

```bash
scripts/orchestration/finalize vendor-pyludusavi-030
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/vendor-pyludusavi-030_finished
/tmp/sdh_ludusavi/vendor-pyludusavi-030_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
