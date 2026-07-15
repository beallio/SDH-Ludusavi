# Review — sigstop-launch-gate (round 01)

Branch: `feat/sigstop-launch-gate`
Reviewed against: `docs/plans/2026-07-14_sigstop-launch-gate.md`
Commit reviewed: `d688721`

## Verdict

The core fix is correct and well built. The deadlock is genuinely gone: `acquire` now makes
a single `discover` call, treats `ScopeNotReadyError` as an era-1 gate after verifying the
PID is stopped and childless, and returns `stop_only=True` without sending `SIGCONT`. The
`finally` block releases only on failure, so the `SIGSTOP` is correctly held as the gate.
Polling and both timeout constants are gone.

The surrounding work is also right: `_release_gate` sends `SIGCONT` for scope-less leases,
`renew_pause` verifies `_is_stopped` for stop-only leases rather than renewing against an
empty `scopes` tuple, `verify_gate` fails closed with `_deny_gate` as the dependency
default, the copy-time check sits in the `restore_backup` branch only, and the frontend
passes `pauseHandle?.pid` / `pauseHandle?.leaseId` so a missing lease degrades to
`gate_lost`. Era-2 freezer coverage at `tests/test_launch_gate_scope.py:966` was correctly
left intact, and the session log records the test-inversion rationale as required.

One required change: the plan's explicit anti-polling regression guard does not guard
anything. Everything else below is minor.

## Gate status

Independently re-run by the reviewer, not taken on trust:

- `scripts/orchestration/run-quality-gates` — passed.
- 794 tests passed; coverage 88.33% (required 83%).
- Working tree clean; no review notes deleted.

On-device verification remains deferred and outstanding, as the plan requires. Nothing in
this review substitutes for it.

## Required changes

### 1. The anti-polling regression guard cannot fail (must fix)

`LaunchScopeAcquirer.__init__` (`py_modules/sdh_ludusavi/launch_gate_acquire.py:56-69`)
accepts `monotonic` and `wait` but never assigns them to `self`. Only `_controller`,
`_signal`, `_proc_root`, and `_uid` are stored. Verified directly:

```text
accepted params : ['controller', 'signal_sender', 'proc_root', 'uid', 'monotonic', 'wait']
stored attrs    : ['_controller', '_proc_root', '_signal', '_uid']
hasattr(a, '_wait')      -> False
hasattr(a, '_monotonic') -> False
```

Because the injected callback is discarded at construction, it can never be invoked, so
these two assertions are structurally incapable of failing:

- `tests/test_launch_gate_acquire.py::test_scope_not_ready_does_not_poll_while_pid_is_stopped`
  — `assert waits == []` is a tautology.
- `tests/test_launch_gate_scope.py::test_prescope_acquisition_does_not_wait_for_scope_to_appear`
  — its `wait` callback (which would materialise the cgroup and force the scope path) is
  never called, so the "does not wait" claim in the test name is unverified.

Plan Task 1 item 2 called for exactly this as "the regression guard — it fails if anyone
reintroduces a wait-while-stopped loop." As written it would stay green through the very
regression it exists to catch. This matters more than a normal dead-parameter smell: three
consecutive fixes (`93cb2ac`, `184a0c3`, `a3963b6`) already walked into this deadlock, and
existing tests asserting `"timed out"` are part of why they survived review. The guard is
the artefact that stops a fourth.

Required:

1. Remove the dead `monotonic` and `wait` parameters from `LaunchScopeAcquirer.__init__`,
   and drop the now-unused `time` import if nothing else needs it. Update the call sites in
   `tests/test_launch_gate_scope.py` that still pass `wait=`.
2. Replace the vacuous assertions with a guard that can actually fail. Assert on observable
   behaviour the acquirer really performs — for example, have the fake controller count
   `discover` invocations and assert it is called **exactly once** on the stop-only path (a
   reintroduced poll loop calls it repeatedly). Optionally also `monkeypatch` `time.sleep`
   to raise if invoked during `acquire`, which catches a poll loop that bypasses injection.
3. Confirm the new guard is not vacuous by mutation: temporarily reintroduce a poll loop
   in the `ScopeNotReadyError` branch, observe the test **fail**, then revert. Record that
   check in the session log.

The behavioural core is already properly covered — keep
`test_scope_not_ready_returns_stop_only_gate_without_resuming`, whose
`assert signals == [signal.SIGSTOP]` is a real assertion that proves the hold, since
`signal_sender` **is** stored as `self._signal`.

### 2. Misleading failure reason when the launch already forked (minor)

In `launch_gate_acquire.py:93-97`, when `_has_children` is true the code re-calls
`self._controller.discover(identity.pid)`, which re-raises the same `ScopeNotReadyError`
that was just caught. The broad handler turns it into
`reason="Exact Steam app scope is not ready"`.

The behaviour is correct (fails closed, no gate reported), but the reported reason
describes the scope rather than the actual condition — the launch got ahead of us and
already has children. This bug was diagnosed purely by correlating plugin-log text against
`journalctl` timestamps, so log wording here is load-bearing for the next diagnosis.

Raise a distinct, accurate error for this branch, e.g.
`"Launch PID already has children; refusing an unverified pre-scope gate"`, and drop the
redundant second `discover` call. Add a test asserting that reason.

### 3. Wording nit (minor)

`ProcessWatchdog.pause` docstring (`py_modules/sdh_ludusavi/watchdog.py:66`) still reads
"Freeze the launch PID's complete Steam app scope", which is now only one of two outcomes.
Reword to cover both the SIGSTOP gate and the scope freeze.

## Not required, recorded for the on-device run

`_has_children` fails closed, so any launch where the reaper has already forked by the time
our `SIGSTOP` lands will report no gate and skip conflict resolution — the same
user-visible symptom as the bug being fixed, via a different path. Device evidence suggests
this is unlikely (the `SIGSTOP` demonstrably blocked scope creation in all three observed
launches, meaning the reaper had not progressed). Do not change the fail-closed behaviour;
it is correct. Just watch for `refusing an unverified pre-scope gate` in the device logs
during verification — if it appears, the era-1 window is tighter than the evidence implies
and needs a separate plan.

STATUS: CHANGES_REQUESTED
