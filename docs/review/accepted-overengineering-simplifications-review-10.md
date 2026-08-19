# Review — accepted-overengineering-simplifications (round 10)

Branch: `feat/accepted-overengineering-simplifications`
Reviewed against: `docs/plans/2026-08-18_accepted-overengineering-simplifications.md`

## Verdict

All ten tasks are complete. Task 10 changed no production behavior, the reconciliation is honest
about every drift from the authored targets, the rejected prototypes are absent, and the final full
gate passes against a clean worktree. The implementation is approved.

## Gate status

- Reviewed branch commit: `91a7593074c880834f13d7873dadd7874e737543`.
- Working tree was clean and the round marker was valid at the reviewed commit.
- Independent `scripts/orchestration/run-quality-gates`: passed. 1041 backend tests passed with
  89.60% total coverage against the 83% floor; 366 frontend tests passed across 33 files;
  `ty` clean; `tsc --noEmit` clean; pnpm audit reported no known vulnerabilities before and after
  install; rollup build and plugin package both succeeded.
- Independent `scripts/orchestration/check-review-notes-not-deleted`: no deleted review notes.
- Independent `git status --short` after the session-record commit: empty.

## Metrics independently reconfirmed at HEAD

- Public plugin RPCs: 35, down from 44 on `dev`, matching the target.
- `settingsMutationRuntime.ts`: 345 lines, down from 535.
- Scoped production `any` across the eleven evaluated files: 0.
- Repository-wide production `any`: 54, down from 86, matching the target.
- Frontend logging RPC owners: 1 (`src/utils/logging.ts`).

## Reconciliation quality

The record explains each drift with file-level evidence instead of restating the target. Production
lines land 34 below the authored target because the review-requested cleanups removed 9 net lines
from `service.py`, 20 from `updater.py`, 4 from `pluginUpdateController.tsx`, and 1 from
`settingsMutationRuntime.ts`. Test lines land 180 above it because review-requested coverage was
added across seven files and removed from three. The scoped `any` baseline is reported as the
measured 32 rather than the authored 31, with the undercounted occurrence named. Every one of those
is the right direction of honesty: the numbers moved because review demanded work, and the record
says so.

## Rejected prototypes confirmed absent

- No nested QAM callback grouping: `useGameRefresh` keeps a flat dependency interface, and its only
  branch difference is type-boundary tightening.
- No lifecycle typed-outcome or effect wrapper: neither `LifecycleOutcome` nor `LifecycleEffects`
  exists in production source.
- No backend port of the frontend Syncthing machine: `syncthingMonitorMachine` remains a frontend
  import with no counterpart under `py_modules`.

## Negative controls confirmed

Each named mutation failed for its stated reason and was restored before the positive suites: the
sequential-await mutation of manual finalization produced eager-start counts of `[1, 0, 0, 0]` and
400 ms instead of 100 ms; raising the hidden-QAM sample constant to 11 was caught by the ten-sample
test; basing `update_settings` on read-then-save instead of the locked mutation lost the first
service's write; and reintroducing a debug-derived watch lifetime reproduced the `observing` status
the round removed. A no-op implementation could not have passed these.

## Accepted record-keeping exception

The body of `639f762` retains its literal `\n\n` sequences. Not rewriting it was the correct call:
a review note already sat on top of that commit, and review notes are durable audit records. The
session record preserves both the defect and the intended paragraph separation, and every later
commit body in the round uses real breaks.

## Deferred verification acknowledged

On-device observation of QAM visibility transitions, update installation, notification policy, and
post-game Syncthing status remains deferred to an explicitly authorized development install. No
backup, restore, launch-gate, or Syncthing experiment ran against real saves or live device
configuration. Out-of-tree callers of the removed undocumented aliases remain unsupported; the
bundled frontend and backend pair is the compatibility boundary.

## Finalization

The user authorized integration with push for this finalization. Merge the branch into `dev` and
push, then confirm the finalized marker exists. Publishing a release, tagging, or dispatching a
workflow is not authorized by this note and remains a separate explicit user decision.

STATUS: APPROVED
