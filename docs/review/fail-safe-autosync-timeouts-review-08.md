# Review — fail-safe-autosync-timeouts (round 08)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 5 and its review correction are accepted.  The RED suite now pins the full
backend-owned gate lifecycle, every start mutation, cross-language gate
identity, cancellation-before-thaw behavior, retained-gate shutdown failure,
unload ordering, and frontend renewal-loss acknowledgement.  Proceed with Task
6 only.

## Gate status

- Commits `5083ddc` and `a8e9dbf` have a valid round-complete marker and a clean
  tree; both are tests-only.
- Independent focused Python verification passed 176 ordinary tests with 29
  strict expected failures.
- Independent focused frontend verification passed 42 ordinary tests with two
  expected failures.
- Implementer full Python/frontend/type/build/package gates passed.

## Required changes

1. Implement Task 6's watchdog guarded-operation API and `_PauseLease` state.
   Atomically check and pin the exact frozen lease/generation, run mutation and
   cancellation callbacks outside both watchdog locks, defer every release
   cause until cancellation and worker completion, and never alter a replacement
   lease from a stale callback.
2. Open the managed executor's unique operation scope before pinning and route
   `restore_game_on_start`, conflict `keep_local`, and conflict
   `restore_backup` through the guard after coordinator acquisition.  Missing,
   malformed, expired, thawed, or replaced gate data must return structured
   `gate_lost` without an adapter mutation.
3. Propagate `pid` and `lease_id` through lifecycle, service, compatibility
   wrappers, `main.py`, TypeScript callable/RPC types, and the controller.  Keep
   transport arguments optional only for fail-closed compatibility.
4. Make service shutdown reject new executor work, cancel/reap managed work,
   wait for guarded callbacks, and only then thaw and stop Syncthing.  If exit
   cannot be confirmed, return the planned structured failure and retain the
   gate.  Preserve unload responsiveness and do not let the synchronous fallback
   bypass a retained-gate result.
5. Keep the frontend promise race as an early signal, await backend
   resume/cancellation acknowledgement during release, and publish exactly one
   visible gate-loss failure.  Do not treat JavaScript rejection as subprocess
   cancellation proof.
6. Remove each Task 5 strict expected-failure marker only after its complete
   assertion body passes.  Run the planned guard-bypass negative control,
   focused tests, and full quality gates; commit Task 6 only and do not begin
   Task 7 in this round.

STATUS: CHANGES_REQUESTED
