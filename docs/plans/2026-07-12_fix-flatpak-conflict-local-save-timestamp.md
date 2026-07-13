# Plan: Fix Flatpak Conflict Local Save Timestamp (fix-flatpak-conflict-local-save-timestamp)

## Context

### Problem Definition

When a launch-time save conflict is detected, the conflict modal can show a valid backup
timestamp but render `Keep Local Save: Unknown time`. The frontend is behaving according to
its input: `src/formatting/dateTime.ts::formatConflictTime` returns `Unknown time` only when
`LifecycleCheckResult.localModifiedAt` is absent or null. The backend should supply that
field from the newest filesystem modification time among the game's local save files.

The failure was reproduced on the Steam Deck with X-Men Origins: Wolverine. The July 12
field log records a successful restore preview with `change=Different`, followed by:

```text
direction is unknown ... (local=None, backup=2026-07-12T07:37:15.216332992Z)
```

The subsequent conflict therefore had no local timestamp. A read-only inspection of the
real Ludusavi Flatpak backup-preview API established the exact schema mismatch:

- `games[game].files` was an object with 13 entries;
- each map **key** was an absolute host path under `/run/media/deck/...`;
- each value contained `bytes`, `change`, and `redirectedPath`;
- each `redirectedPath` was an absolute Flatpak-internal path under
  `/ludusavi/heroic/prefixes/default/...`;
- `originalPath` was absent from those values.

`PyludusaviAdapter.get_conflict_metadata` currently iterates only `files.values()`, prefers
`redirectedPath`, and calls host-side `Path.stat()` on the Flatpak-internal path. Every stat
fails and is silently skipped, leaving `localModifiedAt` unset. The existing unit fixture
does not model production: it uses an opaque map key and places a host-accessible path in
`originalPath`, so it cannot catch this regression.

The intended result is that conflict metadata uses the newest mtime from statable local save
files reported by the real API, serializes it as a timezone-aware UTC ISO timestamp, and
continues to degrade safely to an unknown time when no trustworthy host path can be statted.

### Architecture Overview

Keep the fix in the Python adapter boundary where Ludusavi API paths are translated into
host filesystem metadata:

```text
Ludusavi Flatpak backup --preview --api
  -> games[game].files { host_path_key: ApiFile }
  -> PyludusaviAdapter.get_conflict_metadata
  -> newest statable host mtime as localModifiedAt (UTC ISO)
  -> LifecycleEngine conflict response
  -> ConflictResolutionModal -> formatConflictTime -> Deck-local display
```

Do not move filesystem probing into the frontend or service layer. The lifecycle/service
contracts already pass `localModifiedAt` through correctly, and the modal already converts a
valid ISO timestamp to local display time.

### Core Data Structures

- Ludusavi preview file map: `dict[str, ApiFile]`, where production Flatpak output uses the
  map key as the original host path and may use `redirectedPath` for a sandbox-only path.
- Candidate path record: a private, ordered set of absolute `Path` candidates for one file
  entry, tagged only by source (`map_key`, `originalPath`, or `redirectedPath`) for bounded
  diagnostics.
- Local timestamp scan result: newest successful `st_mtime`, plus scalar counts needed for
  diagnostics. Do not retain or log the raw file map or paths.
- Public conflict metadata remains `dict[str, object]` with optional
  `localModifiedAt`, `backupModifiedAt`, and `backupPath` fields.

### Public Interfaces

No RPC, TypeScript type, modal, or persistence schema changes are required. Preserve:

```text
localModifiedAt: timezone-aware UTC ISO string when available, otherwise absent/null
backupModifiedAt: Ludusavi backup record timestamp
backupPath: existing Ludusavi backup location
```

### Dependency Requirements

Use only the Python standard library already imported by the adapter (`pathlib.Path` and
`datetime`). Do not change `pyproject.toml`, `uv.lock`, vendored `pyludusavi`, or any upstream
package. Do not modify files outside the scope below unless a failing required quality gate
demonstrates a direct need.

**Slug used throughout this plan:** `fix-flatpak-conflict-local-save-timestamp`

---

## Orchestration Contract

**Slug:** `fix-flatpak-conflict-local-save-timestamp`

**Plan file:**

```text
docs/plans/2026-07-12_fix-flatpak-conflict-local-save-timestamp.md
```

**Implementation branch:**

```text
feat/fix-flatpak-conflict-local-save-timestamp
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/fix-flatpak-conflict-local-save-timestamp_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/fix-flatpak-conflict-local-save-timestamp_finalized
```

**Review notes:**

```text
docs/review/fix-flatpak-conflict-local-save-timestamp-review-*.md
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

## Scope discipline

- Implement only the units the plan lists. Do not modify files outside the plan's scope.
- Do not change runtime behavior beyond what the plan specifies. A `refactor` or
  `cleanup` commit must preserve observable behavior.
- Never edit a test's expected value to make a behavior change pass. If a test
  legitimately must change, that change must be required by the plan or a review
  note, and you must record the rationale in the session log.
- If you spot an unrelated improvement, do not make it here — note it in the
  session log for a separate plan.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/fix-flatpak-conflict-local-save-timestamp
```

Commit this plan first:

```bash
git add docs/plans/2026-07-12_fix-flatpak-conflict-local-save-timestamp.md
git commit -m "docs(plan): add fix-flatpak-conflict-local-save-timestamp implementation plan"
```

---

## Implementation Tasks

### 1. Reconfirm the boundary and protect unrelated work

Before editing:

1. inspect `git status --short` and preserve all unrelated user work;
2. read `py_modules/sdh_ludusavi/ludusavi.py::get_conflict_metadata` completely;
3. read the conflict-metadata tests in `tests/test_ludusavi.py` and
   `tests/test_exception_boundaries.py`;
4. confirm that `py_modules/sdh_ludusavi/lifecycle.py`,
   `py_modules/sdh_ludusavi/service.py`, `src/components/modals/ConflictResolutionModal.tsx`,
   and `src/formatting/dateTime.ts` already pass through and format a valid timestamp;
5. do not repeat SSH investigation or place raw on-device paths/logs in the repository. The
   production shape documented in this plan is the regression contract.

Files in implementation scope:

- `py_modules/sdh_ludusavi/ludusavi.py`
- `tests/test_ludusavi.py`
- `tests/test_exception_boundaries.py` only if its existing boundary assertions need a
  directly related extension
- `docs/agent_conversations/2026-07-12_fix-flatpak-conflict-local-save-timestamp.json`

Do not change the frontend, public types, service/lifecycle behavior, dependencies, release
metadata, or vendored `pyludusavi` for this fix.

### 2. RED: reproduce the real Flatpak preview shape

Add the failing regression test before implementation. Use `tmp_path` to create at least two
host-side save files with deliberately different mtimes. Construct preview data whose
`files` shape matches the observed API:

```python
{
    str(host_save_path): {
        "bytes": 123,
        "change": "Different",
        "redirectedPath": "/ludusavi/heroic/prefixes/default/...",
    }
}
```

Do not use a real user's path or save content in the fixture. Assert that:

- `localModifiedAt` is present;
- it represents the newest host-key file mtime, not the inaccessible `redirectedPath`;
- it is timezone-aware UTC and deterministic;
- existing `backupModifiedAt` and `backupPath` behavior is preserved.

Run and record the RED result:

```bash
./run.sh uv run pytest --no-cov tests/test_ludusavi.py -k conflict_metadata
```

The new production-shape test must fail against the pre-fix implementation because
`localModifiedAt` is absent. If it passes, the fixture is not reproducing the reported bug;
correct the fixture before writing implementation code.

### 3. RED: specify path selection, fallback, and failure behavior

Add focused tests for the complete compatibility boundary:

1. **Host map key wins:** an absolute, statable map key is used even when
   `redirectedPath` is absolute but inaccessible.
2. **Newest file wins:** multiple statable entries produce the maximum mtime.
3. **Legacy/synthetic fallback:** when the map key is an opaque or relative identifier,
   retain support for an absolute statable `originalPath`.
4. **Redirected fallback:** an absolute statable `redirectedPath` remains usable when neither
   the map key nor `originalPath` is a statable host path.
5. **Per-candidate recovery:** if an earlier candidate raises `OSError`, try the remaining
   candidates for that entry instead of discarding it immediately.
6. **Malformed/unstatable input:** non-dict entries, blank/non-string paths, relative keys,
   and entries whose candidates cannot be statted are ignored without crashing. If no file is
   statable, omit `localModifiedAt` and preserve any backup metadata already collected.
7. **Bounded diagnostics:** the zero-success path emits at most one useful debug summary with
   scalar entry/success/failure counts and no raw paths, save names, nested file map, home
   directory, or removable-media directory.

Avoid tests that merely restate a private helper's implementation. Assert adapter-observable
metadata and bounded log behavior. Preserve the exception boundary: expected
`LudusaviError`, `KeyError`, `TypeError`, `ValueError`, and per-path `OSError` remain
recoverable, while unrelated unexpected exceptions still propagate as existing tests require.

### 4. GREEN: resolve host paths conservatively and compute the newest mtime

Refactor only as much as needed to keep `get_conflict_metadata` readable. A small private
pure/helper boundary is acceptable. For each `files.items()` entry:

1. consider only non-empty string paths that are absolute;
2. use this stable candidate order:
   - the file-map key (the production host-path contract);
   - `originalPath` (compatible API/fixture fallback);
   - `redirectedPath` (last fallback because Flatpak output may be sandbox-internal);
3. deduplicate identical candidates;
4. call `Path.stat()` read-only until the first candidate for that entry succeeds;
5. catch `OSError` per candidate and continue to the next candidate;
6. collect one successful mtime per file entry and select the maximum across entries;
7. convert the maximum with `datetime.fromtimestamp(..., tz=timezone.utc).isoformat()`.

Do not accept relative file-map keys: treating an opaque key such as `save.dat` as relative to
the plugin working directory could produce an unrelated timestamp. Do not resolve, create,
open, modify, or delete save files. Do not fall back to current time or the backup timestamp;
an unknown local time is safer than a fabricated one.

Add a bounded debug summary for the scan outcome. It may report the game name and scalar
counts/source categories already used by project logging, but must never serialize paths or
the `files` object. Keep routine success logging low-volume.

### 5. REFACTOR: preserve the existing contracts and scope

After the new tests pass:

- keep backup-list retrieval and backup timestamp selection unchanged;
- keep the preview timeout unchanged;
- keep `localModifiedAt` optional when no stat succeeds;
- keep UTC storage and frontend-local formatting unchanged;
- do not add a new RPC or expose path-selection details publicly;
- do not edit expected values merely to make the implementation pass;
- run the existing exception-boundary tests to ensure partial backup metadata survives local
  timestamp failures.

Record exact RED/GREEN commands, observed failure, design decision, files modified, and final
results in the single session log named above. Do not claim on-device success before the
deferred hardware verification is performed.

### 6. Commit structure

After the plan-first commit generated by the orchestration contract, prefer one coherent
implementation commit:

```text
fix(conflict): use host save paths for local timestamps
```

The commit must include the regression tests, implementation, and accurate session log. Run
the repository pre-commit checks and leave the tree clean before marking the round complete.

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

### Focused RED/GREEN verification

Run the focused tests during TDD with coverage disabled so the partial selection does not
fail only because repository-wide coverage is below the global threshold:

```bash
./run.sh uv run pytest --no-cov tests/test_ludusavi.py -k conflict_metadata
./run.sh uv run pytest --no-cov tests/test_exception_boundaries.py -k conflict_metadata
```

Expected GREEN behavior:

- a real Flatpak-shaped response produces the newest host-key mtime;
- output is a timezone-aware UTC ISO timestamp;
- fallback fields remain compatible;
- malformed and unstatable entries do not crash or fabricate a timestamp;
- bounded diagnostics contain no raw path or nested save payload.

### Full local verification

Run the exact project checks through the wrapper, followed by orchestration guards:

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh pnpm run verify
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git diff --check
git status --short
```

All checks must pass, review notes must remain intact, and `git status --short` must be empty
after committing.

### Deferred Steam Deck verification

Defer hardware verification until the reviewed change has been integrated into `dev` and the
user explicitly requests packaging/deployment or a development release. Do not push, tag,
dispatch a release, or publish solely from this plan.

When a reviewed build is installed:

1. launch a disposable Ludusavi-managed game whose saves live through a Flatpak mapping (the
   reproduced SD-card/Heroic layout is representative);
2. create a safe ambiguous local/backup state and trigger the conflict modal;
3. confirm `Keep Local Save` shows a real local date/time instead of `Unknown time`;
4. independently inspect the tracked host save files and confirm the displayed value equals
   the newest filesystem mtime converted to the Deck's local timezone;
5. confirm `Restore Backup Save` still shows the newest Ludusavi backup timestamp;
6. confirm choosing either resolution preserves the existing launch-gate behavior;
7. pull only the new plugin log window under `/tmp/sdh_ludusavi/steamdeck/logs` and confirm
   conflict diagnostics no longer report `local=None`, while no raw host or Flatpak paths are
   newly logged.

If the real API shape differs from the documented evidence on another Ludusavi version, stop
and capture only a sanitized schema description for review; do not broaden path heuristics or
modify vendored dependencies speculatively.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished fix-flatpak-conflict-local-save-timestamp
```

This writes:

```text
/tmp/sdh_ludusavi/fix-flatpak-conflict-local-save-timestamp_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer fix-flatpak-conflict-local-save-timestamp`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/fix-flatpak-conflict-local-save-timestamp-review-*.md
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
   scripts/orchestration/clear-finished fix-flatpak-conflict-local-save-timestamp
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
   git add docs/review/fix-flatpak-conflict-local-save-timestamp-review-*.md
   git commit -m "docs(review): record fix-flatpak-conflict-local-save-timestamp review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished fix-flatpak-conflict-local-save-timestamp
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer fix-flatpak-conflict-local-save-timestamp` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed fix-flatpak-conflict-local-save-timestamp
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize fix-flatpak-conflict-local-save-timestamp
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/fix-flatpak-conflict-local-save-timestamp_finalized
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
scripts/orchestration/finalize fix-flatpak-conflict-local-save-timestamp
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/fix-flatpak-conflict-local-save-timestamp_finished
/tmp/sdh_ludusavi/fix-flatpak-conflict-local-save-timestamp_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
