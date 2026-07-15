# Plan: Hold launches with a SIGSTOP gate instead of a scope freeze (sigstop-launch-gate)

## Context

### User-visible problem

When a tracked game launches with a save conflict, the plugin is supposed to hold the
game at a black screen, prompt the user to choose a save, copy the chosen files, and
only then let the game start. Instead every launch logs:

```text
launch_gate: Unable to acquire frozen Steam app scope for root PID 5334: Scope acquisition timed out before an exact Steam app scope appeared
autosync_status: notify call: ... body=Launch gate unavailable; conflict resolution skipped while game is loading.
```

The conflict is never resolved and the game starts with whichever save was already on disk.

### Root cause: the gate deadlocks against itself

`LaunchScopeAcquirer.acquire` (`py_modules/sdh_ludusavi/launch_gate_acquire.py`) sends
`SIGSTOP` to the Steam bootstrap PID, then polls up to
`SCOPE_ACQUISITION_TIMEOUT_SECONDS` (0.5s) for that PID to appear inside an
`app-steam-app<id>-<pid>.scope` cgroup. That scope is only created once the stopped
process is allowed to run. The gate waits for something its own `SIGSTOP` prevents.

Device evidence, correlating `journalctl --user` scope creation against the plugin log
across three launches on 2026-07-14:

| Launch | App started | SIGCONT (gate gives up) | Scope created | After app-start | After SIGCONT |
|---|---|---|---|---|---|
| 19:45 (pid 4099) | 57.346 | 57.349 (~3ms hold) | 57.356 | +10ms | +7ms |
| 22:13 (pid 5334) | 10.435 | 10.937 (~502ms hold) | 10.991 | +556ms | +54ms |
| 22:21 (pid 6074) | 19.498 | 19.999 (~501ms hold) | 20.052 | +554ms | +53ms |

Measured from app-start the delay is meaningless (10ms, 556ms, 554ms). Measured from
`SIGCONT` it is tight and consistent (7ms, 54ms, 53ms). Scope creation is gated on the
stopped PID resuming. In the 22:13 launch the scope appeared 54ms **after** the plugin
had already given up.

**Do not "fix" this by raising `SCOPE_ACQUISITION_TIMEOUT_SECONDS`.** A longer timeout
holds the game hostage for longer and still fails. The wait can never succeed while the
`SIGSTOP` is held.

### This is a regression

Commit `93cb2ac` ("fix(launch-gate): freeze the complete Steam app scope") replaced a
working tree-walking `SIGSTOP` gate with the scope-freeze design. The prior
implementation is a useful reference:

```bash
git show 93cb2ac^:py_modules/sdh_ludusavi/watchdog.py
```

Two follow-ups (`184a0c3`, `a3963b6`) then moved toward the deadlock rather than out of
it. `a3963b6` correctly found that the launch PID sits in `steam-launcher.service` at
launch and added a 500ms poll loop, converting a 3ms hard failure into a 500ms timeout
failure — a wait for an event it is itself blocking.

### Why SIGSTOP is the correct gate, not just the achievable one

The scope cannot exist until the reaper runs, so by the time there is a scope to freeze
the runtime has already begun executing and may hold open save file handles or have read
the save into memory. `SIGSTOP` at the App-started notification catches the launch before
the process tree exists at all. That is the only point in the lifecycle where "copy the
files, then start the game" is actually true. The same evidence that proves the deadlock
also proves the reaper has not forked, not loaded the runtime, and not touched a save.

The launch gate has two eras. The current code demands era-2 machinery during era 1:

- **Era 1 (pre-scope):** nothing has forked. `SIGSTOP` on the bootstrap PID is a complete
  gate. The cgroup does not exist and cannot.
- **Era 2 (post-scope):** the tree exists and can escape a single-process `SIGSTOP`.
  The cgroup freeze is correct and achievable here.

### The conflict flow is already built and correct

`src/controllers/gameLifecycleController.tsx:286-298` already runs both `resolveConflict`
(the dialog) and `resolveGameStartConflict` (the copy) under `withLease`. The lease renews
every 5s against a 30s TTL and `runProtected` rejects on lease loss. None of that needs
rework. The entire flow is dead for exactly one reason: `state.paused` is `false`, because
`ProcessWatchdog.pause` (`watchdog.py:99`) hard-requires a scope that cannot exist yet.

### Second defect in scope: the watchdog ceiling exposure

`WATCHDOG_ABSOLUTE_RESUME_SECONDS` (`constants.py:50`) is 960s and is **not** renewable —
the lease TTL renews, the ceiling does not. Once the gate works, a user who leaves the
conflict dialog open for 16 minutes gets force-resumed by the watchdog. The game starting
is itself safe (it just uses local saves), but the forced resume drops the lease and the
frontend only notices on its next renew up to 5s later. In that window a late dialog click
copies files under a running game — the exact corruption the gate exists to prevent.

Today the conflict path is dead code, so this is unreachable. Shipping the gate fix is
what makes it reachable, so both fixes ship together. The robust fix is a backend
re-verification at copy time rather than trusting the client's view of the lease.

### Relevant files

- `py_modules/sdh_ludusavi/launch_gate_acquire.py` — acquisition and the deadlock.
- `py_modules/sdh_ludusavi/launch_gate.py` — `ScopeNotReadyError`, scope discovery.
- `py_modules/sdh_ludusavi/watchdog.py` — `_PauseLease`, `pause`, `renew_pause`, `_resume_locked`.
- `py_modules/sdh_ludusavi/lifecycle.py:260` — `resolve_game_start_conflict`.
- `py_modules/sdh_ludusavi/service.py:330` — RPC wiring.
- `src/controllers/launchGateLease.ts` — `PauseLeaseHandle`.
- `scripts/analyze_plugin_logs.py:23` — launch-gate success regex.

**Slug used throughout this plan:** `sigstop-launch-gate`

---

## Orchestration Contract

**Slug:** `sigstop-launch-gate`

**Plan file:**

```text
docs/plans/2026-07-14_sigstop-launch-gate.md
```

**Implementation branch:**

```text
feat/sigstop-launch-gate
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/sigstop-launch-gate_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/sigstop-launch-gate_finalized
```

**Review notes:**

```text
docs/review/sigstop-launch-gate-review-*.md
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
git checkout -b feat/sigstop-launch-gate
```

Commit this plan first:

```bash
git add docs/plans/2026-07-14_sigstop-launch-gate.md
git commit -m "docs(plan): add sigstop-launch-gate implementation plan"
```

---

## Implementation Tasks

Work the tasks in order. Each task is independently verifiable. Follow RED-GREEN-REFACTOR:
write the failing test first, run it, confirm it fails for the stated reason, then implement.

### Task 1 — RED: encode the deadlock as a test

Add to `tests/test_launch_gate_acquire.py`:

1. A test using a fake controller whose `discover` **always** raises `ScopeNotReadyError`
   (simulating a launch PID parked in `steam-launcher.service`). Assert that `acquire`:
   - returns `success is True`;
   - returns `scope is None` and `stop_only is True`;
   - leaves the PID stopped — no `SIGCONT` was sent.
2. A test asserting `acquire` does **not** poll when `discover` raises `ScopeNotReadyError`:
   inject a `monotonic`/`wait` pair and assert `wait` is never called. This is the
   regression guard — it fails if anyone reintroduces a wait-while-stopped loop.

Run `./run.sh uv run pytest tests/test_launch_gate_acquire.py` and confirm both fail.

Three existing tests encode the buggy behavior as the contract and must be inverted, not
deleted. In `tests/test_launch_gate_scope.py`, the assertions at approximately lines 337,
588, and 726 assert `"timed out"` in the failure reason for pre-scope paths. Change each to
assert the new SIGSTOP-only success contract. Record the rationale in the session log, as
the scope-discipline rules require. Do not touch the `"verification timed out"` assertion
near line 990 — that one covers era-2 freeze verification and is still correct.

### Task 2 — Process-state helpers

In `py_modules/sdh_ludusavi/launch_gate_acquire.py`, add two helpers with unit tests
against a temp `proc_root` (the existing tests already inject `proc_root`, follow that
pattern):

- `_is_stopped(proc_root, pid) -> bool` — read `/proc/<pid>/stat`, parse the state field.
  Reuse the parsing approach in `_parse_start_ticks`: take the text after the last `)`,
  split, and read `fields[0]`. State is `T` when stopped. Any read failure returns `False`
  (fail closed).
- `_has_children(proc_root, pid) -> bool` — read `/proc/<pid>/task/*/children`; any
  non-empty content means the launch already forked. Any read failure returns `True`
  (fail closed — assume children if we cannot prove otherwise).

### Task 3 — SIGSTOP-only acquisition

In `launch_gate_acquire.py`:

1. Add `stop_only: bool = False` to `ScopeAcquisitionResult`. Update `__post_init__`: a
   successful result requires `scope is not None` **or** `stop_only is True`, and it is an
   error for both `scope` and `stop_only` to be set.
2. In `acquire`, replace the `_wait_for_scope` call with a single `discover` attempt. When
   it raises `ScopeNotReadyError`:
   - verify `_is_stopped` is true; if not, fail closed with a clear reason;
   - verify `_has_children` is false; if it has children the launch got ahead of us, so
     fall through to the existing scope path rather than reporting a gate we do not hold;
   - re-run `_require_same_identity` to confirm the PID did not recycle;
   - return `ScopeAcquisitionResult(True, scope=None, stop_only=True)`.
3. **Do not send `SIGCONT` on the stop-only success path.** The existing `SIGCONT` at
   approximately line 106 exists because the scope freeze was meant to take over the hold.
   With no scope, the `SIGSTOP` *is* the hold. Ensure the `finally` block does not release
   it either — it currently releases only when `failed` is true, which is correct, but
   verify it with a test.
4. Delete `_wait_for_scope` and `SCOPE_ACQUISITION_TIMEOUT_SECONDS` /
   `SCOPE_ACQUISITION_POLL_SECONDS` along with the constructor's
   `acquisition_timeout_seconds` / `poll_seconds` parameters, unless a remaining caller
   needs them. Era 2 discovery is immediate and needs no polling. Removing the constant
   makes the "just raise the timeout" non-fix structurally unavailable.

Keep every existing identity check. The `uid` and `start_ticks` verification in
`_capture_identity` is correct and still applies.

### Task 4 — Lease model supports a scope-less gate

In `py_modules/sdh_ludusavi/watchdog.py`:

1. `_PauseLease.scope` becomes `SteamAppScope | None`. The `scopes` property returns `()`
   when `scope is None`, so era-2 loops iterate nothing for a stop-only lease.
2. `pause` — accept `acquired.stop_only` as success. Drop the `acquired.scope is None`
   rejection at approximately line 99. Log a distinct message for the stop-only path, e.g.
   `Held launch PID <pid> with SIGSTOP gate (pre-scope)`.
3. `renew_pause` — a stop-only lease has no scopes, so the `lease.scopes` loop verifies
   nothing and the lease would renew unconditionally. Add an explicit check: for a
   stop-only lease, verify `_is_stopped` is still true and fail the lease if not. This is
   safety-critical — the frontend calls this every 5s and treats success as "the gate still
   holds".
4. `_resume_locked` — for a stop-only lease send `SIGCONT` instead of thawing. Preserve the
   existing `retained`/failure reporting shape for the scope path.
5. `_check_and_resume_stuck_pids` — the log line dereferences `lease.scope.unit` and will
   raise `AttributeError` on a stop-only lease. Handle `None`.
6. `resume_all` and `stop` — ensure stop-only leases are `SIGCONT`ed on plugin unload.
   A stopped game that never resumes is a permanently black screen, so this path matters.

Consult `git show 93cb2ac^:py_modules/sdh_ludusavi/watchdog.py` for the prior
`_send_signal_tree` implementation. Reuse its identity-checked signalling approach where it
fits, but do not restore tree-walking for era 1 — at launch there is only the root PID, and
Task 2's `_has_children` check enforces that.

### Task 5 — Re-verify the gate at copy time

Close the watchdog-ceiling exposure described in Context. The copy must not trust the
client's view of the lease.

1. `watchdog.py` — add `verify_gate(pid, lease_id) -> bool`. Returns `True` only when a
   lease exists for `pid`, its `lease_id` matches, it has not expired, and the gate is
   verifiably still held (stop-only: `_is_stopped`; scope: existing frozen verification).
2. `service.py` — expose it and thread `gate_pid` / `gate_lease_id` through
   `resolve_game_start_conflict` (`service.py:274`).
3. `lifecycle.py:260` — add optional `gate_pid` / `gate_lease_id` parameters. In the
   `restore_backup` branch only (the branch that writes into the game's save directory),
   call `verify_gate` immediately before the restore. On failure return
   `self.dependencies.skip("start", game.name, "gate_lost")`. Leave the `keep_local` branch
   alone — it copies local saves outward and is not the corruption risk.
4. `src/controllers/launchGateLease.ts` — expose `readonly pid: number` and
   `readonly leaseId: string` on `PauseLeaseHandle` and return them from `createPauseLease`.
5. `src/controllers/gameLifecycleController.tsx:298` — pass `pauseHandle.pid` and
   `pauseHandle.leaseId` into `resolveGameStartConflict`.

Test the fail-closed path: a `restore_backup` with a missing, mismatched, or expired lease
must skip with `gate_lost` and must not invoke the restore adapter.

### Task 6 — Log analyzer and fixtures

`scripts/analyze_plugin_logs.py:23` matches launch-gate success with a regex that already
accepts the legacy `Paused game process tree rooted at` phrasing alongside
`Froze Steam app scope`. Add the Task 4 stop-only success phrasing so a SIGSTOP-gated
launch is classified as success, not as a missing gate.

Add a fixture covering a successful stop-only launch alongside
`tests/fixtures/plugin_logs/launch-gate-acquisition-success.log`, and extend
`tests/test_analyze_plugin_logs.py` to assert it reports no
`launch_gate.scope_acquisition_failed` incident.

### Task 7 — Documentation

Update `docs/specs/sdh_ludusavi_launcher.md` to describe the two-era gate: `SIGSTOP` on the
bootstrap PID before the scope exists, cgroup freeze for an already-running game. State
explicitly that the app scope cannot be created while the bootstrap PID is stopped, and
that waiting for it while holding `SIGSTOP` is a deadlock. Include the timing table from
Context — it is the evidence that keeps this from being re-broken.

Record the session log under `docs/agent_conversations/` per the repo protocol, including
the rationale for inverting the three `"timed out"` assertions in Task 1.

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

### Automated

```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

Frontend gates:

```bash
pnpm test
pnpm run build
```

Targeted suites, all must pass:

```bash
./run.sh uv run pytest tests/test_launch_gate_acquire.py tests/test_launch_gate_scope.py tests/test_watchdog.py tests/test_analyze_plugin_logs.py
```

`tests/test_module_size_budgets.py` covers `watchdog.py`; if Task 4 or 5 pushes it past
budget, extract helpers rather than raising the budget.

### Deferred: on-device verification (required, cannot run in CI)

This fix is only provable on hardware. The bug is a real-time race between systemd cgroup
creation and a signal, and no unit test can prove the deadlock is gone — the unit tests
prove the logic, the device proves the fix. Do not treat a green suite as verification of
this plan.

Hand off to the user for a Steam Deck run. State clearly in the session log that on-device
verification is deferred and outstanding.

Steps for the device run:

1. Build a dev release and install it on the Deck.
2. Pick a tracked game with a genuine save conflict (`X-Men Origins: Wolverine - Uncaged
   Edition`, appID `3156562597`, reproduced the failure three times on 2026-07-14).
3. Launch it and confirm: the game **holds at a black screen**, the conflict dialog is
   reachable, and the game does not start until a choice is made.
4. Choose "restore backup" and confirm the files are copied **before** the game starts —
   the game must load the restored save, not the local one.
5. Confirm the plugin log shows the stop-only gate success line and **no**
   `Unable to acquire frozen Steam app scope` and no
   `Launch gate unavailable; conflict resolution skipped`.

Log locations and the timing correlation that diagnosed this:

```bash
ssh deck@steamdeck 'ls -t /home/deck/homebrew/logs/SDH-Ludusavi/ | head -3'
ssh deck@steamdeck 'journalctl --user -b --no-pager -o short-precise | grep app-steam-app'
```

Cross-check the `Started app-steam-app<id>-<pid>.scope` timestamp against the plugin log's
App-started line. Expected after the fix: the scope appears only **after** the gate is
released, and the gate no longer waits for it.

6. Confirm the game resumes cleanly if the user cancels the dialog, and that killing the
   plugin mid-hold (Task 4 `resume_all`) resumes the game rather than leaving a permanent
   black screen.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished sigstop-launch-gate
```

This writes:

```text
/tmp/sdh_ludusavi/sigstop-launch-gate_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer sigstop-launch-gate`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/sigstop-launch-gate-review-*.md
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
   scripts/orchestration/clear-finished sigstop-launch-gate
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
   git add docs/review/sigstop-launch-gate-review-*.md
   git commit -m "docs(review): record sigstop-launch-gate review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished sigstop-launch-gate
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer sigstop-launch-gate` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed sigstop-launch-gate
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize sigstop-launch-gate
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/sigstop-launch-gate_finalized
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
scripts/orchestration/finalize sigstop-launch-gate
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/sigstop-launch-gate_finished
/tmp/sdh_ludusavi/sigstop-launch-gate_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
