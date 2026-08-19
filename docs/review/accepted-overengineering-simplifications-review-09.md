# Review — accepted-overengineering-simplifications (round 09)

Branch: `feat/accepted-overengineering-simplifications`
Reviewed against: `docs/plans/2026-08-18_accepted-overengineering-simplifications.md`

## Verdict

The `stop_all` coverage gap is closed and Task 9 is complete and accurate, including its honest
correction of the plan's scoped target. One defect remains: the Task 9 commit body contains
literal backslash-n sequences instead of line breaks, and that commit body is part of the evidence
Task 10 must cite.

Fix the commit body and proceed with Task 10 in the next implementation round.

## Gate status

- Reviewed branch commit: `639f7623a515dec51565c1dd578a03c7cc4370b2`.
- Working tree was clean and the round marker was valid at the reviewed commit.
- Independent `vitest run` of the five Task 9 focused suites: 27 tests passed across 5 files.
- Independent full `vitest run`: 366 tests passed across 33 files.
- Independent `pytest tests/test_watcher.py`: 75 tests passed.
- Independent `pnpm run typecheck`: clean.

## Round-08 cleanup confirmed

`test_stop_all_stops_every_registered_watch_and_clears_registry` registers two watches, asserts
both `stop()` calls happened exactly once, and asserts the registry is empty afterward. That is the
snapshot-before-clear behavior the plan required, and it no longer rests on the single-watch lock
test.

## Task 9 confirmed

- Scoped count independently recomputed across the eleven listed files: 32 before, 0 after. The
  commit's correction of the plan's authored 31 is right — `pluginUpdateController.tsx` held two
  occurrences, not one — and recording the actual number rather than trimming to hit the target is
  the correct call.
- Repository-wide production count independently recomputed: 86 before, 54 after, matching the
  authored target exactly.
- The 54 survivors sit only in the excluded boundaries: `src/utils/steam.ts` (14),
  `src/utils/steamRuntime.ts` (13), `src/ludusaviLauncher.ts` (5),
  `src/controllers/gameLifecycleController.tsx` (5),
  `src/surfaces/autoSyncStatusBrowserView.ts` (3), and `src/types/steam-globals.d.ts` (1). No
  widening occurred.
- `isRpcStatus` is now a real type predicate (`result is RpcStatus`) in both `useGameRefresh` and
  `useInitialContent`, and the downstream `as any` and `as Settings` casts were deleted rather than
  swapped for narrower casts — the union narrows on its own.
- `unknown` is used for the Decky installer surface and its return, the browser timer uses
  `ReturnType<typeof window.setTimeout>`, and the icon and notification parameters use `ReactNode`.
- Runtime behavior is unchanged. The one place the shape of a check moved —
  `!isRpcStatus(cacheCurrentResult) && cacheCurrentResult === true` collapsing to
  `cacheCurrentResult === true` — is equivalent, because an `RpcStatus` object never satisfies
  `=== true`; the guard was redundant, not load-bearing. `clearTimeout(undefined)` in
  `syncthingMonitor` is likewise a no-op on the path where the timer never armed.
- Test doubles were tightened only as far as the stronger predicate contract required.

## Required changes

1. Record the malformed commit body of `639f762` rather than rewriting it. The message contains
   the literal two-character sequences `\n\n` where paragraph breaks belong, so it renders as one
   run-on line. Do not amend or rebase: this review note now sits on top of that commit, and review
   notes are durable audit records that must not be rewritten. Instead, note the defect and the
   intended paragraph breaks in the Task 10 session record, and use real newlines in every
   remaining commit body this round.

2. Implement Task 10, "Reconcile the accepted set and record the implementation session." Change no
   production behavior in this round.

3. Confirm none of the three rejected prototypes is present: no nested callback grouping that
   retains the same QAM leaf dependencies, no lifecycle typed-outcome/effect wrapper, and no
   backend port of the frontend Syncthing machine.

4. Measure production and test files and lines, public RPC count, settings-runtime lines,
   logging-RPC owners, scoped and repository `any`, hidden-QAM captures, and controlled
   finalization latency against the round's actual `dev` base. Explain every drift from the
   authored targets with file-level evidence rather than restating the target. The scoped `any`
   drift from 31 to 32 is already known and must appear in the reconciliation with its cause.

5. Inspect `README.md` and `DEVELOPMENT.md` and update them only if the completed work changed a
   documented public behavior or developer workflow. No routine change is expected.

6. Create `docs/agent_conversations/2026-08-18_accepted_overengineering_simplifications.json` with
   date, objective, files modified, tests added, design decisions, task-by-task results, RED
   evidence, negative controls, final metrics, and deferred verification. Do not create or modify
   anything under `docs/review/`.

7. Run the focused suites and the required negative controls, restore every temporary mutation, run
   the positive gates, and record actual pass/fail tallies. Commit as
   `docs(session): record accepted simplification implementation`. Then run the Final full gate
   exactly as the plan writes it and require empty `git status --short` output. Do not edit tracked
   files after a clean final gate. Put the clean-tree result in the round handoff before writing the
   round-complete marker.

STATUS: CHANGES_REQUESTED
