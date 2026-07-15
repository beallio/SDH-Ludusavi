# Plan: Wait for SIGSTOP delivery before verifying the launch gate (await-sigstop-delivery)

## Context

### User-visible problem

Launching a tracked game with a save conflict still skips conflict resolution. The game
does not hold at a black screen, so the user never gets to choose a save. On device with
`0.3.7-dev.g86f511c` installed:

```text
[09:43:37,076] frontend: App started: X-Men Origins Wolverine (3156562597)
[09:43:37,079] launch_gate: Unable to acquire frozen Steam app scope for root PID 8927: Launch PID is not stopped after SIGSTOP; refusing an unverified gate
[09:43:43,160] autosync_status: notify call: ... body=Launch gate unavailable; conflict resolution skipped while game is loading.
```

### What is already fixed — do not undo it

The prior `sigstop-launch-gate` work (merged as `86f511c`) fixed a real deadlock: the gate
used to `SIGSTOP` the bootstrap PID and then poll up to 500ms for that PID to appear in an
`app-steam-app<id>-<pid>.scope` cgroup, which systemd only creates once the stopped process
runs. That fix is confirmed working on device — the failure is now at 3ms instead of a 500ms
hang, and the old `Scope acquisition timed out before an exact Steam app scope appeared`
string is gone from the build. **The SIGSTOP-gate redesign is correct. This plan does not
revisit it.**

### Root cause of the remaining failure

`LaunchScopeAcquirer.acquire` sends `SIGSTOP` and then calls
`_is_stopped(self._proc_root, identity.pid)` essentially immediately. But `os.kill(pid,
SIGSTOP)` returns as soon as the signal is *queued* — the kernel delivers it
asynchronously, and the process only reaches state `T` once it is next scheduled.

Measured on the Steam Deck itself:

```text
state before SIGSTOP:            S
state immediately after kill():  R    <- _is_stopped reads here, sees "not stopped"
  after +0.5ms cumulative:       T
```

So `_is_stopped` observes `R`, returns `False`, and `acquire` raises
`"Launch PID is not stopped after SIGSTOP; refusing an unverified gate"`. The gate is
refused even though the `SIGSTOP` was about to land correctly. The verification step is
racing signal delivery.

### The distinction that must be preserved

Both the old bug and this fix involve "waiting after SIGSTOP", which makes them easy to
conflate. They are opposites:

- **Forbidden — the original deadlock:** waiting for the *Steam app scope* to appear while
  the PID is stopped. `SIGSTOP` **prevents** that event, so the wait can never succeed. This
  must never be reintroduced. It is guarded by asserting `discover` is called exactly once.
- **Required — this fix:** waiting for the *process to reach state `T`*. `SIGSTOP`
  **causes** that event, so the wait normally converges in well under a millisecond;
  otherwise it fails closed at the deadline.

Do not write that this wait "always succeeds" — that is false. A target can stay in `D`
(uninterruptible sleep), enter ptrace stop `t`, become a zombie, exit, or be continued by
another actor. The correct claim is *normally converges, otherwise fails closed*. What makes
it categorically different from the forbidden wait is causation, not certainty.

Encode this distinction in comments and docs. A future reader who removes the state-`T`
wait "because we don't poll after SIGSTOP" reintroduces this bug.

### Measured timing (Steam Deck, 2026-07-15)

Use these as the basis for the bound; do not re-derive them by guessing.

| Scenario | SIGSTOP -> state `T` |
|---|---|
| Idle single-threaded child | ~0.5ms |
| 5-thread child (4 busy spinners) | 0.16ms, all 5 threads `T` together |
| Child under continuous `fsync` disk I/O, 8 trials | 0.21–0.87ms (worst 0.87ms) |

The 100ms bound is ~115x the worst observed case. Treat it as a generous production default,
not a proof of headroom: `time.sleep` can overshoot arbitrarily under load, so the bound must
be a named constant that can be tuned from device evidence.

### Thread-group stop: what is and is not proven

`/proc/<pid>/stat` reports the *thread group leader's* state. In principle Linux completes a
group stop through per-thread participation, so a leader could read `T` while a sibling has
not yet stopped — and any thread can `fork`.

Measured: 60 trials of a 9-thread process found **zero** cases where the leader read `T` while
any sibling was not `T`. That is evidence the window is not reachable in practice, not proof
it cannot exist — the probe needs ~50us to snapshot all threads, so a shorter window would be
invisible to it.

Given the cost of checking every thread is ~one `/proc` read per thread, this plan requires
the stronger invariant rather than relying on the measurement. Note also that `_has_children`
already globs `task/*/children`, so it covers forks by *any* thread, not just the leader.

### Known limits, accepted deliberately

Record these in the spec rather than silently assuming them:

1. **`children` is first-level only.** `/proc/<pid>/task/*/children` does not list
   grandchildren, so a child that spawns a grandchild and immediately exits would reparent
   away and go unseen. Escaping this way requires fork -> fork -> exit inside the sub-millisecond
   delivery window, in a process we have strong evidence has not forked at all (its `SIGSTOP`
   demonstrably blocks Steam's own scope creation). The check is fail-closed best effort, not
   proof. Document the assumption; do not weaken the check.
2. **A plugin-owned freezeable cgroup was considered and rejected.** Migrating the stopped
   reaper into our own cgroup would contain descendants atomically. This is *not* the same as
   the original deadlock (that was waiting on Steam's scope), but Steam moves the reaper into
   `app-steam-app<id>-<pid>.scope` moments later, so a plugin-owned cgroup would collide with
   Steam's own placement. Out of scope here.
3. **PID reuse between `_capture_identity` and `os.kill` is not addressed by this plan.**
   There is a real pre-existing hole: if the PID is reused in that window we `SIGSTOP` an
   unrelated process, and `_release_if_same` then sees the identity mismatch and deliberately
   does **not** `SIGCONT` it, leaving an innocent process stopped forever
   (`launch_gate_acquire.py`, `_release_if_same`). The fix is `os.pidfd_open` +
   `signal.pidfd_send_signal`, retaining the pidfd through the lease. That is a separate
   concern from this plan's delivery race and must get its own plan — do not attempt it here.

### Why the test suite missed it

`tests/test_launch_gate_acquire.py` and `tests/test_launch_gate_scope.py` build synthetic
`/proc` trees whose `stat` file already contains state `T` before `acquire` runs. The fake
is instantaneous in a way the kernel is not, so it encodes the buggy assumption rather than
testing it. Any fix must add coverage that can actually fail against an instantaneous check.

### A test from the previous round now blocks the correct fix

`tests/test_launch_gate_acquire.py::test_acquirer_constructor_does_not_expose_dead_polling_hooks`
asserts `"wait" not in parameters` and `"monotonic" not in parameters` on
`LaunchScopeAcquirer.__init__`. That test over-constrains: it was written to kill *dead*
hooks left behind by removed scope polling, but as written it forbids the injectable clock
this fix legitimately needs. It must be replaced, not worked around. The real invariant is
"never poll `discover` while stopped", which
`test_scope_not_ready_does_not_poll_while_pid_is_stopped` already guards via
`controller.discover_calls == 1`.

### Diagnostic gap

The failure reason does not report the state actually observed. Diagnosing this required
reproducing the race on hardware. Since this whole bug class is only findable on device, the
error text must carry the evidence.

### Relevant files

- `py_modules/sdh_ludusavi/launch_gate_acquire.py` — `acquire`, the immediate `_is_stopped` call.
- `py_modules/sdh_ludusavi/launch_gate_process.py` — `_is_stopped`, `_has_children`.
- `tests/test_launch_gate_acquire.py` — synthetic `/proc` fakes; the over-constraining test.
- `tests/test_launch_gate_process.py` — helper unit tests.
- `docs/specs/sdh_ludusavi_launcher.md` — two-era gate documentation.

**Slug used throughout this plan:** `await-sigstop-delivery`

---

## Orchestration Contract

**Slug:** `await-sigstop-delivery`

**Plan file:**

```text
docs/plans/2026-07-15_await-sigstop-delivery.md
```

**Implementation branch:**

```text
feat/await-sigstop-delivery
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/await-sigstop-delivery_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/await-sigstop-delivery_finalized
```

**Review notes:**

```text
docs/review/await-sigstop-delivery-review-*.md
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
git checkout -b feat/await-sigstop-delivery
```

Commit this plan first:

```bash
git add docs/plans/2026-07-15_await-sigstop-delivery.md
git commit -m "docs(plan): add await-sigstop-delivery implementation plan"
```

---

## Implementation Tasks

Work in order. Follow RED-GREEN-REFACTOR: write the failing test first, run it, confirm it
fails for the stated reason, then implement.

### Task 1 — RED: a fake that is not instantaneous

The existing fakes pre-set state `T`, so they cannot fail against an immediate check. Add to
`tests/test_launch_gate_acquire.py` a synthetic `/proc` helper whose `stat` file reports
state `R` for the first N reads and then flips to `T`, emulating scheduling latency.

Add a test using it: `acquire` on a pre-scope PID must still return
`success=True, stop_only=True`. Run it and confirm it **fails** against today's code with
`"Launch PID is not stopped after SIGSTOP"`. That failure is the bug reproduced in a unit
test — do not proceed until you have seen it.

### Task 2 — State-reading primitive

The current API cannot satisfy the diagnostic requirement: a boolean `_is_stopped` cannot
also report which state was actually observed. Restructure first, in
`py_modules/sdh_ludusavi/launch_gate_process.py`:

1. Add `_read_process_state(proc_root, pid) -> str | None` — parse `/proc/<pid>/stat`, take
   the text after the last `)`, return `fields[0]`. Return `None` for a missing, unreadable,
   or malformed stat file, so "unreadable" is distinguishable from a real state. Parsing
   after the last `)` is correct and already handles commands containing parentheses; keep it.
2. Reimplement `_is_stopped` as a thin wrapper: `_read_process_state(...) == "T"`.

**Only uppercase `T` is acceptable.** Lowercase `t` is a ptrace stop: a tracer can suppress
or reinject the pending `SIGSTOP`, so `t` does not prove the group stop we require and is not
a gate this plugin owns. Add an explicit `t -> False` test.

Add named constants (do not inline these numbers):

```python
SIGSTOP_DELIVERY_TIMEOUT_SECONDS = 0.1
SIGSTOP_DELIVERY_POLL_SECONDS = 0.0005
```

Document at the constant that device measurement is 0.16–0.87ms worst case (including under
`fsync` I/O load), so 100ms is a generous default rather than a proven ceiling.

### Task 3 — Bounded waiter for a full thread-group stop

Add `_wait_until_stopped(proc_root, pid, *, timeout_seconds, poll_seconds, monotonic, wait)`
returning the final observed state string (`"T"` on success; otherwise the last state seen, or
`"unreadable"`).

Require **every** thread to be stopped, not just the leader: enumerate
`/proc/<pid>/task/*/stat` and require a non-empty snapshot with all tasks reporting `T`.
`/proc/<pid>/stat` reports only the thread-group leader, and Linux completes a group stop
through per-thread participation, so a leader can in principle read `T` while a sibling still
runs and could fork. Measurement did not reproduce that window (60 trials, 9 threads, zero
violations), but the check costs one `/proc` read per thread — take the stronger invariant.
Fail closed on an empty task list.

Use a strict monotonic deadline. Fail closed at expiry. When the final state is `t`, also read
`TracerPid` from `/proc/<pid>/status` and include it in the diagnostic — a tracer is the one
plausible cause of that outcome and it would otherwise be very hard to diagnose.

Add a comment at the wait site drawing the caused-vs-prevented distinction explicitly, and say
plainly that this **normally converges, otherwise fails closed** — do not claim it always
succeeds.

### Task 4 — Use the waiter in `acquire`

In `py_modules/sdh_ludusavi/launch_gate_acquire.py`, replace the immediate `_is_stopped` call
in the `ScopeNotReadyError` branch with the bounded waiter.

Implement exactly this order — the current code checks identity **both** before and after the
stoppedness check, and both must be preserved:

```text
capture identity
  -> SIGSTOP
  -> one discovery attempt (never retry; that is the original deadlock)
  -> wait for all tasks stopped
  -> identity check
  -> children scan
  -> final identity check
  -> gate
```

The children scan must stay **after** the full group stop is confirmed, so a fork during the
delivery window is still caught. Do not add any scope retry anywhere.

Re-add the injectable `monotonic` / `wait` constructor parameters — but this time **store them
on `self` and actually use them**. The previous round's defect was accepting these and
silently discarding them; that is what made its regression guard vacuous. Verify they are
stored.

On timeout, include the observed state in the reason:

```text
Launch PID did not stop after SIGSTOP within 100ms (state=R); refusing an unverified gate
```

### Task 5 — Bind stop-only leases to process identity

This plan makes long stop-only holds reachable for the first time. Today `pause()` never
succeeds on the pre-scope path, so no stop-only lease ever exists; once the gate works, a
lease can hold a PID for **minutes** while the user reads the conflict dialog. Over that
window a bare PID is not a safe handle — if the launch is force-quit the PID can be freed and
reused, after which `verify_gate` (`watchdog.py`) and the `SIGCONT` in `_release_gate`
(`watchdog_lease.py`) would act on an unrelated process.

Close this proportionately:

1. Store the acquired `LaunchProcessIdentity` (pid, owner uid, `start_ticks`) on `_PauseLease`
   for stop-only leases. Return it from `ScopeAcquisitionResult`.
2. `verify_gate` and `renew_pause` must re-verify that identity — not just that *some* process
   with that PID is stopped — using the same full-thread-group invariant from Task 3.
3. `_release_gate` must re-verify identity before sending `SIGCONT`, and skip the signal if it
   no longer matches. Never `SIGCONT` a PID whose identity has changed.

Add tests in `tests/test_watchdog.py` / `tests/test_watchdog_lease.py` covering: a stop-only
lease whose PID is replaced by a different `start_ticks` must fail `verify_gate`, must fail
`renew_pause`, and must **not** receive `SIGCONT` from `_release_gate`. A matching identity
must pass all three. These are the guards mutation-checked in Task 9.

**Out of scope:** the full `os.pidfd_open` / `signal.pidfd_send_signal` migration, and the
pre-existing `_release_if_same` hole where a PID reused between `_capture_identity` and
`os.kill` is stopped and then deliberately never resumed. Those need their own plan. Retaining
`start_ticks` closes the practical lease-lifetime exposure this plan creates; do not attempt
the pidfd refactor here.

### Task 6 — Replace the over-constraining test

Delete
`tests/test_launch_gate_acquire.py::test_acquirer_constructor_does_not_expose_dead_polling_hooks`.
It forbids the injectable clock this fix requires, and its intent — no vestigial scope
polling — is already covered by `test_scope_not_ready_does_not_poll_while_pid_is_stopped`
(`controller.discover_calls == 1`).

Replace it with a test asserting the opposite of the old defect: the injected `wait` and
`monotonic` **are** wired, i.e. the acquirer actually calls the injected `wait` when the
process is not yet stopped. That guards against silently discarding them again.

Record the rationale for deleting this test in the session log, as scope discipline requires.

### Task 7 — Deterministic helper coverage

The existing helper tests cover only `T` and `S` for `_is_stopped` and static child files.
Add direct fake-clock tests in `tests/test_launch_gate_process.py` for:

- immediate `T` — asserts the waiter returns **without ever calling `wait`**;
- `R...R -> T` — converges and reports `"T"`;
- perpetual `R` — times out at the deadline with the exact diagnostic state;
- `D`, `Z`, and `t` — each fails closed, with `t` recording `TracerPid`;
- missing / malformed / disappearing `stat` — reports `unreadable`, fails closed;
- multiple threads with **staggered** stops — leader `T` while a sibling is still `R` must not
  be accepted;
- empty task list — fails closed.

For the no-sleep test, pass an explicit `wait` callback that raises if invoked. Do **not**
monkeypatch `time.sleep`: if the default callable was bound at import, monkeypatching it
becomes vacuous — precisely the class of dead-hook test this plan is removing.

### Task 8 — Real-process integration test

Add `tests/test_launch_gate_signal_integration.py`. Synthetic `/proc` fakes cannot reproduce
kernel scheduling, which is exactly why this bug shipped; this test exercises real signal
semantics.

- Spawn a real child (`subprocess.Popen`), send a real `SIGSTOP` via `os.kill`.
- Because the target **is our child**, use `os.waitpid(pid, os.WUNTRACED)` to deterministically
  confirm the kernel delivered the stop before asserting. This removes scheduler-timing
  flakiness from the assertion. Note in a comment that `waitpid` works only for children and
  therefore cannot replace the `/proc` polling path used for the non-child reaper.
- Assert `_wait_until_stopped` against the real `/proc` returns `"T"`.
- Do **not** assert that an immediate `_is_stopped` is `False` — that is the race itself and
  would flake.
- Give this test a **generous test-only deadline (1–2s)**. Do not assert the production 100ms
  bound here: an oversubscribed CI runner exceeding 100ms would not disprove the code. Exact
  100ms behaviour belongs in the Task 7 fake-clock tests.
- Add a multithreaded variant that stops a child with several busy threads and asserts all
  tasks reach `T`.

Cleanup must be **nested** so a failure in one step cannot skip the rest — a `SIGCONT` that
raises must not prevent `terminate`/`kill`. An infinite sleep loop does **not** exit on
`SIGCONT`, so `SIGCONT` + `wait()` alone will hang forever. Structure it as:

```text
finally:
    try: SIGCONT
    finally:
        try: terminate(); wait(timeout=...)
        finally: kill(); wait()
```

Guard with `@pytest.mark.skipif(not sys.platform.startswith("linux"), ...)` since it depends on
`/proc` and POSIX job control. CI runs Linux, so it will execute there.

### Task 9 — Mutation-verify the new guards

Every new guard must be **observed failing**, not merely green. The previous round shipped a
regression guard that was structurally incapable of failing; do not repeat that.

1. Temporarily revert Task 4 to the immediate `_is_stopped` check. Confirm the Task 1 fake
   test **fails**. Revert.
2. Temporarily make the waiter ignore its injected `wait`. Confirm the Task 6 test **fails**.
   Revert.
3. Temporarily make the waiter accept leader-only `T`. Confirm the Task 7 staggered-threads
   test **fails**. Revert.
4. Temporarily drop the identity re-verification from `verify_gate`. Confirm the Task 5
   identity test **fails**. Revert.

Record all four mutation results in the session log.

### Task 10 — Documentation

Update `docs/specs/sdh_ludusavi_launcher.md` with a subsection on signal-delivery timing:

- `os.kill(SIGSTOP)` returns before the target reaches state `T`; measured on Steam Deck at
  0.16–0.87ms including under `fsync` I/O load. Gate verification must wait for the transition.
- State the caused-vs-prevented distinction explicitly, and that the wait **normally
  converges, otherwise fails closed** — never "always succeeds".
- Only uppercase `T` is accepted; `t` is a ptrace stop the plugin does not own.
- The full thread group must be stopped, not just the leader.
- Synthetic `/proc` fakes cannot reproduce kernel scheduling, which is why the real-process
  test exists.
- Record the accepted limits from Context: `children` is first-level only; a plugin-owned
  freezeable cgroup was rejected because Steam relocates the reaper into
  `app-steam-app<id>-<pid>.scope` moments later; pidfd-based identity-safe signalling is
  deferred to a separate plan.

Record a session log under `docs/agent_conversations/` per the repo protocol, including the
Task 6 deletion rationale and the Task 9 mutation results.

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

Frontend gates (unchanged by this plan, but must stay green):

```bash
pnpm test
pnpm run build
```

Targeted:

```bash
./run.sh uv run pytest tests/test_launch_gate_acquire.py tests/test_launch_gate_process.py tests/test_launch_gate_signal_integration.py tests/test_watchdog.py
```

Run the integration test repeatedly to prove it is not flaky before handing off:

```bash
./run.sh uv run pytest tests/test_launch_gate_signal_integration.py --count=20 -q
```

If `pytest-repeat` is unavailable, loop the command 20 times instead. Any single failure means
the test is timing-fragile — fix the test, do not raise the production waiter timeout to mask
it. The integration test uses its own generous deadline precisely so it never becomes a
referendum on CI load.

Confirm no stopped processes leak:

```bash
ps -eo pid,stat,comm | awk '$2 ~ /T/'
```

### Deferred: on-device verification (required, cannot run in CI)

The previous round shipped with a green suite and still failed on hardware, because the
synthetic `/proc` fakes could not reproduce kernel scheduling. **A green suite is not
evidence this works.** State clearly in the session log that on-device verification is
deferred and outstanding.

Steps for the device run:

1. Build and install a dev release on the Steam Deck.
2. Confirm the installed build is the new one before drawing any conclusion:

   ```bash
   ssh deck@steamdeck 'grep -o "\"version\": *\"[^\"]*\"" /home/deck/homebrew/plugins/SDH-Ludusavi/plugin.json'
   ```

   The prior round's "issues persist" report was the old build still being installed. Always
   verify the version first.
3. Launch `X-Men Origins: Wolverine - Uncaged Edition` (appID `3156562597`) with a genuine
   save conflict.
4. Confirm the game **holds at a black screen**, the conflict prompt is reachable, and the
   game does not start until a choice is made.
5. Choose restore-backup and confirm files are copied **before** the game starts.
6. Confirm cancelling resumes the game cleanly, and that unloading the plugin mid-hold
   resumes it rather than leaving a permanent black screen.
7. Check the newest log under `/home/deck/homebrew/logs/SDH-Ludusavi/`:

   - **must appear:** `Held launch PID <pid> with SIGSTOP gate (pre-scope)`
   - **must not appear:** `Launch PID is not stopped after SIGSTOP`
   - **must not appear:** `did not stop after SIGSTOP within`
   - **must not appear:** `Launch gate unavailable; conflict resolution skipped`

If `did not stop after SIGSTOP within 100ms (state=...)` appears, the waiter is working but
the bound is too tight or the PID is genuinely unstoppable; report the observed state rather
than blindly raising the timeout.

If `already has children` appears, the reaper forks earlier than current evidence suggests
and the era-1 window is narrower than assumed. That needs its own plan — do not weaken the
children check to work around it.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished await-sigstop-delivery
```

This writes:

```text
/tmp/sdh_ludusavi/await-sigstop-delivery_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer await-sigstop-delivery`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/await-sigstop-delivery-review-*.md
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
   scripts/orchestration/clear-finished await-sigstop-delivery
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
   git add docs/review/await-sigstop-delivery-review-*.md
   git commit -m "docs(review): record await-sigstop-delivery review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished await-sigstop-delivery
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer await-sigstop-delivery` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed await-sigstop-delivery
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize await-sigstop-delivery
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/await-sigstop-delivery_finalized
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
scripts/orchestration/finalize await-sigstop-delivery
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/await-sigstop-delivery_finished
/tmp/sdh_ludusavi/await-sigstop-delivery_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
