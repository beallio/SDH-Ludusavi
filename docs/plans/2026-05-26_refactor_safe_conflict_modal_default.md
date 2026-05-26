# Safe Default Action For Conflict Resolution Modal

## Finding Assessment

The review finding has merit. The current `ConflictResolutionModal` sets
`onOK={() => choose("restore_backup")}`, and that resolution is later passed
into `resolveGameStartConflictCall`, which can restore backup data over local
progress. Because `ConfirmModal` exposes `onOK` as the primary confirm action,
the default OK/controller-confirm path should not perform the destructive
choice.

The safe behavior is to dismiss the modal by default and let the explicit
`Keep Local Save` / `Restore Backup Save` buttons remain the only ways to choose
a save source.

## Summary

- Change `ConflictResolutionModal` so the modal's default OK action dismisses
  safely instead of choosing `restore_backup`.
- Keep the explicit in-modal buttons unchanged: `Keep Local Save` still calls
  `choose("keep_local")`, and `Restore Backup Save` still calls
  `choose("restore_backup")`.
- Do not change public APIs, backend behavior, type definitions, or third-party
  dependencies.

## Key Changes

- In `src/index.tsx`, update the `ConfirmModal` inside
  `ConflictResolutionModal` from `onOK={() => choose("restore_backup")}` to
  `onOK={dismiss}`.
- Keep `onCancel={dismiss}` so OK, cancel, and close-style dismissal all
  resolve the modal as `null`.
- Preserve existing downstream behavior: `showConflictResolutionModal(...)`
  returns `null`, `handleAppStart` records `conflict_unresolved`, and the game
  process resumes in the existing `finally` block.
- Add or update a plan artifact under `docs/plans/`, and record the
  implementation session under `docs/agent_conversations/` per repo protocol.

## Test Plan

- Add a focused static regression test in `tests/test_frontend_static.py`
  asserting:
  - The conflict modal contains `onOK={dismiss}`.
  - The conflict modal no longer contains
    `onOK={() => choose("restore_backup")}`.
  - The explicit restore button still contains
    `onClick={() => choose("restore_backup")}`.
  - The explicit keep-local button still contains
    `onClick={() => choose("keep_local")}`.
- Run the new/updated frontend static test first and confirm it fails before
  implementation.
- After implementation, run:
  - `./run.sh uv run pytest tests/test_frontend_static.py -k conflict`
  - `./run.sh uv run ruff check . --fix`
  - `./run.sh uv run ruff format .`
  - `./run.sh uv run ty check py_modules/sdh_ludusavi/`
  - `./run.sh uv run pytest`
- Let the pre-commit hook run the full protocol checks before committing.

## Assumptions

- The modal default OK action is treated as potentially reachable from
  controller confirm/A, so it must be non-destructive.
- A static source test is the correct regression fence because this repo does
  not currently include a React interaction test harness.
- No README update is needed because user-facing commands and documented APIs do
  not change.
- Use branch `refactor-safe-conflict-modal-default` if implementation follows,
  avoiding nested-ref branch naming issues seen in this checkout.
