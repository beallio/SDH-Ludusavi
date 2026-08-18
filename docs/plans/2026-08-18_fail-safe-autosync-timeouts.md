# Plan: Make Autosync Fail Safe and Cap Ludusavi at Three Minutes (fail-safe-autosync-timeouts)

## Context

### Problem Definition

The current autosync flow has three related failure modes:

1. The frontend launch lease can report that it was lost while its RPC callback continues
   in a backend worker. `PauseLeaseHandle.runProtected()` races the RPC against `onLost`,
   but rejecting the JavaScript promise does not cancel `_run_blocking()` or the Ludusavi
   subprocess. Cleanup can therefore thaw the game while a restore or conflict-resolution
   backup is still changing save data.
2. `operation_running` is a normal result of the coordinator's non-blocking lock, but both
   start and exit decisions classify it as silent. A launch can therefore continue without
   its required restore, or an exit can omit its backup, without telling the player.
3. Real Ludusavi operations are allowed to run for 15 minutes and previews for 5 minutes.
   The desired policy is a three-minute ceiling for both. If any Ludusavi command exceeds
   180 seconds, it is considered unhealthy and must fail instead of continuing to hold the
   workflow open.

### Intended outcome

- Every real backup, restore, snapshot restore, preview, and recency/status check invoked
  through `PyludusaviAdapter` has an explicit 180-second subprocess timeout.
- A timeout, lease loss, watchdog expiry, or plugin unload terminates and reaps the managed
  Ludusavi process group before the backend thaws a game whose save data may be changing.
- All automatic start mutations require the exact backend-owned launch-gate PID and lease.
  Missing, stale, mismatched, expired, or concurrently released leases fail closed before
  Ludusavi starts.
- Autosync checks wait for a currently running Ludusavi operation for at most 30 seconds.
  This preserves a 30-second safety margin when a queued check then consumes its
  full 180-second command allowance and the launch gate reaches its 240-second emergency
  ceiling. Mutating actions remain fail-fast so they cannot apply a decision made before an
  intervening operation; their contention result is also visible. If contention remains,
  the player sees an explicit skipped/failure outcome and toast; the plugin never silently
  treats the autosync as complete.
- The running-status strip uses a 210-second ceiling (180 seconds plus 30 seconds for RPC
  delivery and cleanup), while the launch gate retains a separate 240-second emergency
  ceiling (180 seconds plus 60 seconds). Syncthing's 120-second pre-game quiescence and
  independent 300/900-second post-game observation limits do not change.

### Architecture Overview

Keep the operation coordinator as the single global serializer and make waiting opt-in:
manual and mutating actions retain fail-fast behavior, while automatic lifecycle checks
may wait up to `LIFECYCLE_OPERATION_WAIT_SECONDS = 30.0` and then calculate their decision
from fresh data under the acquired lock.

Add a project-owned managed Ludusavi executor under `py_modules/sdh_ludusavi/`; do not edit
the vendored `py_modules/pyludusavi/` package. It must preserve the locally verified
`LudusaviExecutor.execute()` contract for JSON, text, stdin-JSON, and spawn modes, while
tracking non-spawn process groups by unique operation token. Normal timeout and explicit
token-scoped cancellation must terminate the complete process group, escalate to a kill
when necessary, wait for process exit, and then raise the same pyludusavi error family
expected by the adapter. Shutdown may cancel every token, but lease loss must cancel only
the command registered to that exact lease generation.

Extend the watchdog lease with one guarded-operation generation, its cancellation callback,
completion signal, and a release-requested flag. A watchdog API must atomically verify the
exact frozen lease and pin it before invoking an automatic start mutation. `resume()`, lease
expiry, absolute expiry, and `stop()` must request cancellation outside watchdog locks,
wait for confirmed operation completion, and only then release the stored scope. The
240-second emergency boundary applies to each pinned operation from the moment it is
registered; a normal lease expiry must never thaw through a live mutation. Lock ordering is:
coordinator lock, then short watchdog state/PID critical sections, then subprocess work with
no watchdog lock held.

If process-group termination or reaping cannot be confirmed, fail closed: retain the frozen
gate, emit a bounded high-severity diagnostic, and retry cancellation rather than letting the
game write concurrently. The ordinary hung-process path is still bounded because the managed
executor escalates from terminate to kill and reaps the child; the retained-gate case is only
the explicit last resort for an OS process that cannot be confirmed dead.

The frontend lease race remains useful as an early failure signal, but is no longer the
authority that protects save mutation. Both restore paths and both conflict choices pass
`pid` and `lease_id` through TypeScript types, RPC, `main.py`, the service, and the lifecycle
manager. The backend performs the authoritative check-and-pin immediately around the
adapter call. The compatibility `handle_game_start` path must not mutate without a gate;
when a restore is required and no gate is supplied, it fails closed.

### Core Data Structures

- `_PauseLease`: add private guarded-operation generation/state, cancellation callback,
  completion event, start time, and pending-release reason. Never expose process handles or
  raw command output through RPC.
- `ManagedLudusaviExecutor`: pyludusavi-compatible executor with a thread-safe registry of
  token-scoped active process groups, a token cancellation handle, and a bounded cancel-all
  shutdown path.

### Public Interfaces

- `OperationCoordinator.run_locked(...)`: add an optional keyword-only wait timeout; its
  default remains non-blocking.
- `restore_game_on_start(game_name, app_id, gate_pid, gate_lease_id)`: extend the backend and
  frontend RPC contract. Gate arguments may remain optional at the transport boundary only
  so older callers receive a structured `gate_lost` result instead of an unhandled argument
  error.
- `resolve_game_start_conflict(...)`: preserve its existing argument order, but require a
  valid gate for both `keep_local` and `restore_backup` before either mutation starts.

### Dependency Requirements

No dependency additions and no vendored-package modifications are authorized. The managed
executor uses only the Python standard library and the already-vendored pyludusavi response
and error types.

### Testing Strategy

Follow strict RED-GREEN-REFACTOR in separate reviewed rounds for timeout constants, process
cancellation, backend gate ownership, and operation contention. Use deterministic fake
clocks, events, fake scope controllers, and disposable helper process groups; never touch a
real game save. Each behavior has a negative-control mutation that must make its focused
test fail. Final verification runs the complete Python/frontend quality gates and records
the remaining on-device checks as deferred rather than treating unit mocks as device proof.

### Relevant files

```text
py_modules/sdh_ludusavi/constants.py
py_modules/sdh_ludusavi/coordinator.py
py_modules/sdh_ludusavi/ludusavi.py
py_modules/sdh_ludusavi/ludusavi_executor.py (new)
py_modules/sdh_ludusavi/gateway.py
py_modules/sdh_ludusavi/watchdog.py
py_modules/sdh_ludusavi/watchdog_lease.py
py_modules/sdh_ludusavi/lifecycle.py
py_modules/sdh_ludusavi/service.py
main.py
src/api/ludusaviRpc.ts
src/controllers/gameLifecycleRpc.ts
src/controllers/gameLifecycleController.tsx
src/controllers/gameLifecycleDecision.ts
src/controllers/launchGateLease.ts
src/surfaces/autoSyncStatusSurface.tsx
src/types/index.ts
tests/test_constants.py
tests/test_coordinator.py
tests/test_ludusavi.py
tests/test_ludusavi_executor.py (new)
tests/test_service.py
tests/test_main.py
tests/test_main_rpc.py
tests/test_compatibility.py
tests/test_rpc_pool.py
tests/test_status_flow_diagram.py
tests/test_watchdog.py
tests/test_watchdog_lease.py
src/controllers/gameLifecycleController.test.ts
src/controllers/gameLifecycleDecision.test.ts
src/controllers/launchGateLease.test.ts
src/surfaces/autoSyncStatusSurface.suppression.test.ts
README.md
DEVELOPMENT.md
docs/specs/custom_status_bar_ui.md
docs/specs/sdh_ludusavi_launcher.md
docs/status_bar_game_state_flows.html
docs/agent_conversations/
```

**Slug used throughout this plan:** `fail-safe-autosync-timeouts`

---

## Orchestration Contract

**Slug:** `fail-safe-autosync-timeouts`

**Plan file:**

```text
docs/plans/2026-08-18_fail-safe-autosync-timeouts.md
```

**Implementation branch:**

```text
feat/fail-safe-autosync-timeouts
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/fail-safe-autosync-timeouts_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/fail-safe-autosync-timeouts_finalized
```

**Review notes:**

```text
docs/review/fail-safe-autosync-timeouts-review-*.md
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
git checkout -b feat/fail-safe-autosync-timeouts
```

Commit this plan first:

```bash
git add docs/plans/2026-08-18_fail-safe-autosync-timeouts.md
git commit -m "docs(plan): add fail-safe-autosync-timeouts implementation plan"
```

---

## Implementation Tasks

Nine tasks. **Implement exactly one task per round.** Finish the task, run the quality
gates, commit, run `mark-finished`, and exit. Each task is reviewed before the next begins.
Do not combine RED and GREEN tasks across their stated boundary.

### Task 1 — Pin the three-minute policy with failing tests

Before changing production constants, add tests that require:

1. `LUDUSAVI_OPERATION_TIMEOUT_SECONDS == 180.0` and
   `LUDUSAVI_PREVIEW_TIMEOUT_SECONDS == 180.0`.
2. `WATCHDOG_ABSOLUTE_RESUME_SECONDS == 240.0`, derived from the larger Ludusavi
   command ceiling plus a 60-second emergency margin rather than from an unrelated magic
   number.
3. Every adapter path that can run backup/restore work passes the appropriate 180-second
   timeout: real backup, real restore, snapshot restore, refresh preview, exit preview,
   restore-recency preview, and conflict-metadata preview. Preserve the shorter unrelated
   pyludusavi defaults used by lightweight metadata commands unless the adapter already
   supplies one of these two constants.
4. `RUNNING_STATUS_HIDE_CEILING_MS == 210_000` and its suppression behavior still hides a
   stuck Ludusavi status, suppresses a late success, and surfaces a late failure.

Run the focused Python and frontend tests and record the expected failures in the session
log. The exact-value assertions must fail against current `900.0`, `300.0`, `960.0`, and
`930000` values. Commit tests only.

### Task 2 — Apply the timeout policy and linked user-facing boundaries

Set both Ludusavi timeout constants to 180 seconds. Derive the watchdog emergency ceiling
from `max(operation_timeout, preview_timeout) + 60` so later divergence cannot shorten it
below either legal command. Set the status-strip running ceiling to 210 seconds.

Update the adjacent source comments, `README.md`, `DEVELOPMENT.md`, and
`docs/specs/custom_status_bar_ui.md` so they say:

- real operations and previews/status checks each fail after three minutes;
- the status strip has a 210-second cleanup boundary;
- the backend launch-gate emergency boundary is four minutes;
- Syncthing's separate observation limits are unchanged.

Update the stale 15-minute comment in `src/controllers/syncthingMonitor.ts` without changing
`POST_GAME_WATCH_HARD_CEILING_MS`. Do not rewrite the distinct 900-second Syncthing watcher
boundary in `sdh_ludusavi_sync.md`; it is not a Ludusavi subprocess timeout.

Run the focused tests from Task 1. Temporarily restore one timeout to its former value and
confirm the exact-value test fails, then restore the implementation and commit the GREEN
change.

### Task 3 — Specify managed-process cancellation in RED tests

Add `tests/test_ludusavi_executor.py` for a project-owned executor. Use short-lived helper
processes and deterministic events; never invoke a real game backup. Required cases:

1. JSON, text, stdin-JSON, `--api` insertion, environment merging, non-zero exit,
   malformed JSON, and spawn-mode behavior remain compatible with the inspected
   `pyludusavi.core.LudusaviExecutor` contract.
2. Timeout terminates and reaps the entire test process group, then raises
   `LudusaviTimeoutError` with bounded diagnostics.
3. Explicit token-scoped cancellation from another thread terminates and reaps only that
   token's active process group, unblocks `execute()`, and raises a typed Ludusavi
   cancellation error. A second concurrent helper under another token remains alive.
4. A completed process is removed from the active registry, repeated cancellation is
   idempotent, and cancellation never targets a later process that reused an OS PID.
5. Adapter construction installs the managed executor without editing vendored pyludusavi;
   existing fake clients created with `__new__` continue to work.

Confirm the import/API tests fail because the project-owned implementation does not exist.
Commit tests only.

### Task 4 — Implement the managed executor and shutdown hook

Create the smallest project-owned module needed to satisfy Task 3. Use `Popen` with a new
session/process group for non-spawn commands. On timeout or cancellation, send a graceful
termination, wait for a short bounded grace, escalate to group kill, and reap before
returning control. Never include unbounded stdout, stderr, environment data, or user paths
in logs/errors. Preserve the pyludusavi response/error contract and keep GUI `SPAWN` calls
detached from cancellation tracking.

Install this executor on the `Ludusavi` instance in `PyludusaviAdapter.__init__`. Expose an
operation-scope context that yields a unique cancellation handle before a command starts;
the executor associates processes started on that scope with its token. Expose a separate
cancel-all/shutdown method, but defer service/watchdog integration to Task 6 so this round
contains only the executor and adapter boundary.

Run Task 3 tests and existing pyludusavi/adapter tests. Mutation check: temporarily bypass
group termination and prove the descendant-process assertion fails. Restore the
implementation and commit.

### Task 5 — Specify backend-owned launch mutation safety in RED tests

Add deterministic thread/event tests before editing watchdog, lifecycle, RPC, or frontend
production code. Required coverage:

1. The watchdog atomically rejects a missing, wrong, expired, thawed, or replaced lease
   before invoking the mutation callback.
2. Once a guarded mutation starts, explicit resume, lease expiry, absolute expiry, and
   `stop()` request cancellation and do not thaw until the cancellation callback has
   returned and the mutation worker has signalled completion.
3. Normal mutation success/failure clears the pin exactly once; a pending release then
   thaws exactly once. No watchdog lock or PID lock is held while the adapter or cancellation
   callback blocks.
4. A timeout/cancellation result releases the coordinator lock and records a failed
   operation; no late success is published.
5. `restore_game_on_start`, conflict `keep_local`, and conflict `restore_backup` make zero
   adapter mutation calls without the exact gate. With a valid gate, each mutates once
   through the watchdog guard.
6. Backend `main.py`, service, compatibility signature checks, TypeScript RPC types, and the
   controller all require/pass `pid` and `lease_id` for start restore as well as conflict
   resolution.
7. Simulate renewal loss after Ludusavi begins: the frontend promise rejects, cleanup sends
   resume, the backend cancels the command, and the fake game scope remains frozen until
   cancellation acknowledgement. This must fail against the current promise-race-only
   implementation.
8. Service stop and `main.py::_unload` cancel/reap an in-flight command, wait for its guarded
   callback to unwind, and only then thaw and shut down the RPC executor. Preserve the
   existing event-loop responsiveness, daemon-worker property, synchronous fallback, and
   post-shutdown failure behavior.

Commit tests only after capturing the RED results.

### Task 6 — Make the backend gate authoritative for mutations

Implement a watchdog guarded-operation API and extend `_PauseLease` only as specified in
Context. Use a unique generation so a delayed completion/cancel callback cannot release or
alter a replacement lease. Perform check-and-pin under the per-PID/state locks, run both the
adapter and cancellation callback outside locks, and re-check identity/generation before
clearing state or thawing.

Route all automatic start mutations through this guard after the coordinator lock is
acquired. Open the adapter's unique operation scope first, register that scope's cancellation
handle while atomically pinning the gate, and only then start Ludusavi. Require the gate for
`restore_game_on_start` and for both conflict resolutions, including `keep_local`. Wire the
new arguments and cancellation capability through gateway, service, `main.py`, TypeScript
RPC declarations, controller types, and `gameLifecycleController.tsx`. An older/malformed
call without gate data must return the structured fail-closed result and never mutate.
Update the compatibility wrapper accordingly.

Change `SDHLudusaviService.stop()` ordering so managed-executor shutdown atomically rejects
new commands, cancels all remaining tokens, and waits for guarded callbacks to clear before
the watchdog thaws scopes and Syncthing stops. Update `_unload` only as required to preserve
that ordering before the daemon RPC pool shuts down. A cancellation that cannot confirm
process exit must produce a failed stop result and retain the gate; it must not be converted
into an unconditional thaw by the synchronous fallback.

Keep `launchGateLease.runProtected()` as the frontend early-loss signal. Its `release()`
must await the backend resume/cancellation result, and launch error handling must publish
one visible failure for gate loss instead of only hiding the status. Do not add frontend
subprocess assumptions or treat rejection of the JavaScript promise as cancellation proof.

Run Task 5 and all existing launch-gate/lifecycle/RPC tests. Mutation check: temporarily
bypass the backend guard for one restore path and prove the in-flight lease-loss test fails;
then restore it and commit.

### Task 7 — Specify bounded contention and visible failure in RED tests

Before editing the coordinator or decisions, add tests for:

1. `OperationCoordinator.run_locked(..., wait_timeout_seconds=x)` waits for an active
   operation that releases within the injected short test deadline, then runs the queued
   callback exactly once.
2. A lock that stays busy through the deadline raises `OperationLockedError`, leaves the
   queued callback untouched, and preserves the active operation's state.
3. The default remains non-blocking for manual operations and registry refreshes.
4. Automatic start and exit checks request the bounded wait and make their decision from
   fresh data after acquiring the lock. Start restore/conflict and exit backup mutations
   remain non-blocking; if a new operation wins the lock after a check, the action returns
   `operation_running` without performing a stale mutation.
5. Start and exit decision functions no longer include `operation_running` in the silent
   reasons. A timed-out check or action completes the status and emits exactly one failure
   toast rather than hiding the status.
6. A queued start mutation revalidates/pins the gate only after acquiring the coordinator;
   lease loss during the wait produces `gate_lost` and zero adapter calls.

Use injected sub-second waits in tests. Do not sleep for 30 or 180 seconds. Commit tests
only after confirming the new cases fail and the existing manual fail-fast cases pass.

### Task 8 — Implement bounded autosync waiting and visible contention

Add `LIFECYCLE_OPERATION_WAIT_SECONDS = 30.0`. Extend coordinator/service plumbing with an
optional keyword-only wait timeout whose default is the current non-blocking behavior.
Remove the racy `is_coordinator_running` pre-check from lifecycle decisions and its injected
dependency. Automatic start/exit checks use the bounded wait and execute their preview only
after acquiring the lock. Automatic mutations, manual operations, and unrelated
refresh/version paths remain fail-fast; this prevents a queued action from applying a stale
decision after another operation changed the saves or backup.

The guarded mutation must still perform its atomic lease validation after the lock is owned.
If either a check wait or a mutation's fail-fast acquisition reports contention, retain
`reason: operation_running` for formatting compatibility but make it user-visible in start
checks, restores, conflict actions, exit checks, and exit backups. Update
`docs/status_bar_game_state_flows.html` and its structural test so they no longer describe
`operation_running` as hidden.

Run Task 7 tests plus the full lifecycle/controller/formatting suite. Mutation checks:
restore non-blocking acquisition and separately restore `operation_running` to
`SILENT_SKIPPED_REASONS`; each change must make its corresponding focused test fail. Revert
both mutations and commit.

### Task 9 — Reconcile durable documentation and complete verification

Review every timeout, launch-gate, and `operation_running` reference found with `rg`. Update
only references that describe the Ludusavi command/status/gate behavior changed here; keep
the distinct Syncthing monitoring limits intact. Ensure `README.md` remains player-facing,
while implementation and weakened-guarantee detail stays in `DEVELOPMENT.md`,
`docs/specs/sdh_ludusavi_launcher.md`, and the other specs. In particular, replace the
launcher spec's current claim that `keep_local` needs no gate: copying live saves outward is
still a save mutation relative to the launch and must use the same guarded-operation rule.

Record `docs/agent_conversations/2026-08-18_fail_safe_autosync_timeouts.json` with the task
objective, files changed, RED tests, mutation checks, design decisions, exact results, and
deferred device verification. Run the full quality gates and inspect the final diff for
vendored-package edits, unexpected dependencies, cache files, and unrelated formatting.
Commit documentation/session evidence separately.

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

Follow the repository's wrapper/cache policy and the orchestration skill's
`references/verification-standards.md`. Focused commands may be narrowed while iterating,
but every round still runs `scripts/orchestration/run-quality-gates` before completion.

Required focused verification:

```bash
./run.sh uv run pytest -o addopts='' tests/test_constants.py tests/test_ludusavi.py tests/test_ludusavi_executor.py
./run.sh uv run pytest -o addopts='' tests/test_coordinator.py tests/test_watchdog.py tests/test_watchdog_lease.py
./run.sh uv run pytest -o addopts='' tests/test_lifecycle.py tests/test_service.py tests/test_main.py tests/test_main_rpc.py tests/test_compatibility.py
./run.sh pnpm exec vitest run src/controllers/launchGateLease.test.ts src/controllers/gameLifecycleController.test.ts src/controllers/gameLifecycleDecision.test.ts src/surfaces/autoSyncStatusSurface.suppression.test.ts
./run.sh pnpm run typecheck
./run.sh pnpm run build
```

The final full gate is:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

Verification is not complete unless the RED failures and three negative-control mutations
are recorded, the post-restoration focused suites pass, vendored pyludusavi files are
unchanged, and the final worktree is clean.

Deferred verification, stated explicitly:

- Do not exercise a real backup/restore timeout against the user's saves during automated
  implementation. The managed process tree, timeout, cancellation, and thaw ordering are
  proven with disposable helper processes and fake scope controllers.
- On-device verification of a controlled hung Ludusavi Flatpak, lease-renewal loss, and
  Decky unload/update remains deferred until a development build can be installed and a
  disposable test game/save is available. That run must confirm the Ludusavi process group
  exits before `cgroup.freeze` changes to thawed and that the player receives one failure
  notification.
- Timing suitability for unusually large real saves is not claimed by unit tests. The
  three-minute value is the requested policy; a future real-world timeout should be logged
  and diagnosed as an unhealthy Ludusavi/cloud/filesystem condition, not silently extended.
- No release, tag, workflow dispatch, or GitHub publication is part of this plan.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished fail-safe-autosync-timeouts
```

This writes:

```text
/tmp/sdh_ludusavi/fail-safe-autosync-timeouts_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer fail-safe-autosync-timeouts`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/fail-safe-autosync-timeouts-review-*.md
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
   scripts/orchestration/clear-finished fail-safe-autosync-timeouts
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
   git add docs/review/fail-safe-autosync-timeouts-review-*.md
   git commit -m "docs(review): record fail-safe-autosync-timeouts review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished fail-safe-autosync-timeouts
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer fail-safe-autosync-timeouts` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed fail-safe-autosync-timeouts
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize fail-safe-autosync-timeouts
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/fail-safe-autosync-timeouts_finalized
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
scripts/orchestration/finalize fail-safe-autosync-timeouts
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/fail-safe-autosync-timeouts_finished
/tmp/sdh_ludusavi/fail-safe-autosync-timeouts_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
