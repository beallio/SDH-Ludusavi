# Plan: Teardown correctness for plugin load and unload (teardown-correctness)

## Context

Plugin teardown leaves resources running. Six defects were confirmed by source
inspection and re-verified independently; they are recorded as F2, F4, F5, F10,
F11, and F12 in `docs/review/load-unload-lifecycle-review-01.md`. That review
also retracts two earlier findings (F1, F3) — do not implement anything from
those, and do not act on F6/F7/F8/F9, which are deferred to a separate
log-hygiene plan.

What is wrong today:

- `SDHLudusaviService.stop()` returns early when Ludusavi shutdown or the
  watchdog fails, skipping `_syncthing_watch_manager.stop_all()`. Retaining the
  launch gate in that situation is deliberate; stranding every Syncthing watcher
  thread is not.
- `LudusaviGateway.invalidate()` drops `_adapter` without calling the outgoing
  adapter's `shutdown()`. A forced refresh during a live probe orphans that
  adapter's executor and its subprocess outside the teardown chain.
- `invalidate()` also resets `_diagnostics_logged`, so a forced refresh re-runs
  the whole diagnostics probe — up to three managed `flatpak run` subprocesses
  plus a `--version` verify on adapter construction.
- Nothing rejects new work once unload has begun, and the frontend discards the
  promise from `lifecycleController.dispose()`. A watch-start RPC can therefore
  land after `stop_all()` has taken its snapshot and survive teardown.
- `autoSyncStatusBrowserView.sync()` creates a native BrowserView before it
  checks `state.visible`, so hiding a strip that was never shown still creates
  one.
- The post-game Syncthing watch gate omits `guardCandidate`, which the pre-game
  gate has. Untracked games allocate a watch at exit that the backend then
  rejects.

Files in scope:

```text
py_modules/sdh_ludusavi/service.py
py_modules/sdh_ludusavi/gateway.py
src/index.tsx
src/surfaces/autoSyncStatusBrowserView.ts
src/controllers/gameLifecycleController.tsx
tests/test_service.py
tests/test_gateway.py
src/surfaces/autoSyncStatusBrowserView.test.ts
src/controllers/gameLifecycleController.test.ts
src/index.dismount.test.ts
```

Decisions already made — implement these, do not revisit:

- F5 is gated, not documented. Add `guardCandidate` to the exit gate so the two
  paths match.
- F10 is fixed on both sides: a backend admission flag and a bounded frontend
  await.
- Log-hygiene findings are out of scope. `scripts/analyze_plugin_logs.py` parses
  the `frontend:` log prefix, so changing that default is a separate change with
  its own blast radius. Do not touch it here.
- T2 is fail-closed. When an outgoing adapter's `shutdown()` raises or returns
  `False`, the gateway must retain that adapter for a later retry rather than
  dropping its last reference. Dropping it would recreate F12 on the failure
  path, which is the defect T2 exists to fix.
- T5 is bounded best-effort, not a correctness boundary. Decky's installed API
  types `onDismount?(): void` and does not await a returned promise, so T5 can
  only sequence frontend cleanup against itself. The backend synchronization in
  T4 is what actually closes the race.

**Slug used throughout this plan:** `teardown-correctness`

---

## Orchestration Contract

**Slug:** `teardown-correctness`

**Plan file:**

```text
docs/plans/2026-08-25_teardown-correctness.md
```

**Implementation branch:**

```text
feat/teardown-correctness
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/teardown-correctness_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/teardown-correctness_finalized
```

**Review notes:**

```text
docs/review/teardown-correctness-review-*.md
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
git checkout -b feat/teardown-correctness
```

Commit this plan first:

```bash
git add docs/plans/2026-08-25_teardown-correctness.md
git commit -m "docs(plan): add teardown-correctness implementation plan"
```

---

## Implementation Tasks

Seven atomic tasks. Each is one behavior change, one commit, and one gate that
must pass before the next task starts. Do not batch commits.

Order per task is: RED, GREEN, gate, commit. **Run each task's gate before that
task's commit** — the gate reverts your implementation with `git stash push`,
which needs the change to still be uncommitted.

### The mutation gate

This repository currently has five pre-existing stashes belonging to unrelated
work. A bare `git stash pop` would pop `stash@{0}`, which is not yours. Every
task gate must therefore use the pattern below, which refuses to pop unless it
confirms it created the stash it is about to restore.

The gate also captures the mutation run's exit status explicitly. `cmd; echo
"exit=$?"` reports `echo`'s status, not the command's, so an unexpected pass
would go unnoticed.

Use this pattern verbatim, changing only `task_label`, `implementation_file`, and
`test_command`:

```bash
(
  set -u
  task_label="T1"
  implementation_file="py_modules/sdh_ludusavi/service.py"
  test_command=(./run.sh uv run pytest tests/test_service.py -q)

  "${test_command[@]}" || exit 1

  before_stash="$(git rev-parse -q --verify refs/stash || true)"
  git stash push -m "teardown-correctness-${task_label}-mutation" -- \
    "$implementation_file" || exit 1
  after_stash="$(git rev-parse -q --verify refs/stash || true)"

  if [[ -z "$after_stash" || "$after_stash" == "$before_stash" ]]; then
    echo "mutation gate created no stash; refusing to pop existing user work" >&2
    exit 1
  fi

  mutation_exit=0
  "${test_command[@]}" || mutation_exit=$?

  current_stash="$(git rev-parse -q --verify refs/stash || true)"
  if [[ "$current_stash" != "$after_stash" ]]; then
    echo "stash stack changed during mutation gate; refusing to pop" >&2
    exit 1
  fi

  git stash pop stash@{0} || exit 1
  printf 'mutation_exit=%s\n' "$mutation_exit"

  if (( mutation_exit == 0 )); then
    echo "mutation test unexpectedly passed" >&2
    exit 1
  fi
)
```

Per-task substitutions: `tests/test_service.py` + `service.py` for T1 and T4;
`tests/test_gateway.py` + `gateway.py` for T2 and T3; `pnpm run test:unit` plus
the relevant frontend file for T5, T6, and T7.

A non-zero `mutation_exit` is only valid evidence if the output **names the
task's new tests**. A collection error, an import error, or an unrelated failure
is not a negative control. Read the output; do not infer from the status alone.

### Baseline

Capture before starting T1, so V1 has something to compare against:

```bash
(
  set -euo pipefail
  ./run.sh uv run pytest -q 2>&1 |
    tail -3 |
    tee /tmp/sdh_ludusavi/baseline-pytest.txt
  pnpm run test:unit 2>&1 |
    tail -5 |
    tee /tmp/sdh_ludusavi/baseline-vitest.txt
)
```

Record both counts in the session log.

---

### T1 — `stop()` always stops Syncthing watches (F11)

**File:** `py_modules/sdh_ludusavi/service.py`

**Change:** in `stop()`, `_syncthing_watch_manager.stop_all()` must run on every
path, including both `cancellation_unconfirmed` early returns. Wrap the body in
`try` / `finally` and call `stop_all()` from the `finally`. Do not change either
return dict — the retained-gate contract stays exactly as it is.

**RED:** add to `tests/test_service.py` a test where the gateway's `shutdown()`
returns `False`, asserting `stop_all()` was still called on the watch manager,
and a second test with the watchdog's `stop()` returning `False` asserting the
same. Run:

```bash
./run.sh uv run pytest tests/test_service.py -q
```

Record the failure output. Both must fail on the `stop_all` assertion, not with a
collection or import error — an import error means the test never reached the code.

**GREEN:** make the change. Re-run and record the pass/fail tallies.

**Gate:** the mutation gate above with `task_label="T1"`.

**Commit:** `fix(service): stop Syncthing watches even when shutdown is unconfirmed`

---

### T2 — `invalidate()` shuts down the outgoing adapter (F12)

**File:** `py_modules/sdh_ludusavi/gateway.py`

**Change:** in `invalidate()`, capture the current adapter, clear `_adapter`, then
call the captured adapter's `shutdown()` **outside** `_adapter_lock` so a slow
reap cannot block a concurrent `get_adapter()`.

Fail closed. If `shutdown()` returns `False` or raises, append that adapter to a
`_retired_adapters` list and log at `warning` with operation `"init"`. Extend
`gateway.shutdown()` to also reap everything in `_retired_adapters`, and to
report failure if any of them still cannot be confirmed. Simply dropping a
reference to an adapter whose executor was never confirmed stopped would recreate
F12 on the failure path. `invalidate()` itself must never raise.

**RED:** add to `tests/test_gateway.py`:

1. A success test asserting `invalidate()` called the outgoing adapter's
   `shutdown()` exactly once and cleared the caches.
2. A failure test where `shutdown()` raises, asserting `invalidate()` returns
   normally, logs exactly one `warning` with operation `"init"`, and that a later
   `gateway.shutdown()` retries the retired adapter.
3. A lock-ordering test: a fake whose `shutdown()` signals it has entered and
   then blocks on an event. Run `invalidate()` in a worker, wait until shutdown
   is blocked, then call `get_adapter()` in a second worker and assert with a
   bounded timeout that it is **not** blocked by `_adapter_lock`. Release the
   fake in a `finally` so a failing test cannot strand either worker, and bound
   every join.

Run:

```bash
./run.sh uv run pytest tests/test_gateway.py -q
```

Record the failure output. Test 3 must fail if `shutdown()` is called while
holding `_adapter_lock`.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T2"`, `gateway.py`,
`tests/test_gateway.py`.

**Commit:** `fix(gateway): shut down the outgoing adapter on invalidate`

---

### T3 — `invalidate()` no longer re-arms the diagnostics probe (F2)

**File:** `py_modules/sdh_ludusavi/gateway.py`

**Change:** remove `self._diagnostics_logged = False` from `invalidate()`. Leave
the rest of `invalidate()` and all of `get_adapter()` alone.

Confirm the control flow before writing the test: `get_adapter()` enters its
branch because `_adapter is None`, builds a new adapter, calls
`_log_ludusavi_diagnostics()`, and that method early-returns because
`_diagnostics_logged` is still `True`. No second diagnostics thread starts and
none of the diagnostics-probe subprocesses run.

Adapter construction still performs pyludusavi discovery verification with its
own `--version` subprocess. **This task does not eliminate that subprocess** —
do not claim it does, and do not write a test that asserts zero subprocesses.

If your reading of the source disagrees with the above, stop and record the
discrepancy in the session log rather than forcing the test to pass.

**RED:** add to `tests/test_gateway.py` a purpose-built factory returning a new
fake adapter per construction, where every returned adapter increments one
**shared** counter from `get_diagnostics()`. Call `get_adapter()`, wait with a
bounded timeout until the counter reaches one, call `invalidate()`, call
`get_adapter()` again, then poll for a bounded interval and assert the counter is
still exactly one.

Do not count emitted `"Ludusavi version:"` log lines as the primary signal: a
wrongly started second thread that raises before logging would produce a false
pass. Diagnostics run on a background thread, so never assert immediately after
the call.

Run:

```bash
./run.sh uv run pytest tests/test_gateway.py -q
```

Record the failure output. At RED the counter must reach **two**. Zero or one
means the fake never wired up and the test is not measuring what it claims.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T3"`, `gateway.py`,
`tests/test_gateway.py`.

**Commit:** `fix(gateway): keep diagnostics logged once per process across invalidate`

---

### T4 — Backend drains and rejects watch starts once stopping (F10, backend half)

**File:** `py_modules/sdh_ludusavi/service.py`

A bare boolean flag does **not** close this race: a worker can pass the check,
block inside `get_diagnostics()` or Syncthing discovery, and register its watch
after `stop_all()` has already run. Sequential tests would pass that wrong
implementation. Implement the drain.

**Change:** add a condition-protected stopping state and an in-flight
watch-start counter to `SDHLudusaviService`.

`start_syncthing_activity_watch()` must, under the condition, atomically either
reject admission when stopping is set, or increment the in-flight counter before
releasing. It must decrement and notify waiters in a `finally` that covers
diagnostics failures and every Syncthing result path.

At the top of `stop()`, under the same condition, set stopping before any other
teardown work, then wait until every already-admitted watch start has left its
in-flight section. Only then continue to gateway shutdown and T1's `stop_all()`.

Rejected starts return exactly:

```python
{
    "status": "skipped",
    "reason": "unloading",
    "message": "Plugin unload is in progress.",
}
```

The `message` key is required — the frontend's `SyncthingWatchStartResult` type
expects it on skipped results. Verify that against the current type before
implementing rather than trusting this plan.

This establishes the happens-before relationship the fix needs: every admitted
watch is registered before `stop_all()` takes its snapshot, and every later
request is rejected.

**RED:** add to `tests/test_service.py`:

1. Before stopping, a watch start reaches diagnostics and returns the watch
   manager's normal result. (Negative control — fails if stopping defaults set.)
2. After stopping, a watch start returns the exact unloading dict **without**
   calling gateway diagnostics or the watch manager.
3. A deterministic race test: admit a watch start and block it inside
   diagnostics; start `stop()` on another worker; assert `stop()` has not
   completed; release diagnostics; then assert the admitted start completed
   before `stop_all()` ran, and that no registered watch remains after `stop()`
   returns.

Release every blocking fake in a `finally` and bound every join.

Run:

```bash
./run.sh uv run pytest tests/test_service.py -q
```

Record the failure output. At RED tests 2 and 3 must fail; test 1 must pass.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T4"`, `service.py`,
`tests/test_service.py`.

**Commit:** `fix(service): drain and reject Syncthing watch starts once stopping`

---

### T5 — Frontend waits for lease release before disposing the runtime (F10, frontend half)

**File:** `src/index.tsx`

Scope note: Decky types `onDismount?(): void` and does not await a returned
promise. This task sequences frontend cleanup against itself; it does **not**
create an ordering edge with Python's `Plugin._unload()`. T4 is the correctness
boundary. Describe it that way in the session log.

**Change:** `lifecycleController.dispose()`'s promise is currently discarded by
`void`, and `runtime.dispose()` plus the stylesheet removal run immediately
after. Move both cleanup actions so they run after that promise settles or a
2000 ms timeout fires, whichever comes first. Log at `warning` when the timeout
wins. Keep `onDismount` synchronous — chain off the promise rather than changing
the signature. Both cleanup actions must run exactly once regardless of path.

**RED:** create `src/index.dismount.test.ts`. Do **not** add these to
`src/runtime/pluginRuntime.test.ts` — that file imports only
`createPluginRuntime` and cannot reach the plugin's `onDismount`.

There is no vitest DOM environment configured, and `src/index.tsx` calls
`document.createElement` at module scope, so importing it bare will throw. Mock
`definePlugin` to capture the plugin factory, mock
`createGameLifecycleController` and `createPluginRuntime`, and provide the
minimal `document` / `document.head` / style-element fakes the module needs.

With fake timers, assert:

1. While disposal is pending, neither `runtime.dispose()` nor stylesheet removal
   has run.
2. On resolution, both run exactly once and the timeout is cleared.
3. On rejection, both still run exactly once and the rejection is logged.
4. With a never-resolving disposal, both run after 2000 ms and the timeout is
   logged.
5. Resolving the deferred promise *after* the timeout does not run either
   cleanup a second time.

Run:

```bash
pnpm run test:unit
```

Record the failure output.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T5"`, `src/index.tsx`,
`pnpm run test:unit`.

**Commit:** `fix(ui): await lease release before disposing plugin runtime`

---

### T6 — `sync()` does not create a BrowserView to hide nothing (F4)

**File:** `src/surfaces/autoSyncStatusBrowserView.ts`

**Change:** move the `if (!state.visible)` handling above the
`ensureAutoSyncStatusBrowserView()` call. When the state is not visible **and no
view exists yet**, clear any pending show timeout, reset `loadedAutoSyncStatus`
to `null`, and return without creating anything. When a view already exists, the
existing hide path is unchanged: `SetVisible(false)`, navigate to `about:blank`,
reset `loadedAutoSyncStatus`.

**RED:** add to `src/surfaces/autoSyncStatusBrowserView.test.ts`:

1. A fresh-surface test asserting a `sync({visible: false, ...})` never invokes
   the BrowserView factory.
2. A preservation test, with fake timers and a valid BrowserView fake. Do a
   visible sync, then **clear** the fake's `SetVisible` and `LoadURL` call
   histories — the visible path already calls `SetVisible(false)` while loading,
   so without clearing, a test that merely checks "was it ever called" passes
   even if the hide became a no-op. Then do the hiding sync and assert: the
   factory call count did not increase; `SetVisible(false)` was called by the
   hiding sync; `LoadURL("about:blank")` was called. Then clear `LoadURL`, show
   the same status again, and assert the data URL loads again — proving
   `loadedAutoSyncStatus` was reset.

Run:

```bash
pnpm run test:unit
```

Record the failure output. Test 2 must fail if the implementation returns early
for *every* invisible state rather than only the no-view case.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T6"`,
`src/surfaces/autoSyncStatusBrowserView.ts`, `pnpm run test:unit`.

**Commit:** `fix(ui): stop creating a BrowserView to hide an unshown status strip`

---

### T7 — Post-game watch gate matches the pre-game gate (F5)

**File:** `src/controllers/gameLifecycleController.tsx`

**Change:** the exit-path gate reads `if (autoSyncEnabledExit && !gameSyncDisabledExit)`.
Add `&& guardCandidate` so it matches the start path's
`autoSyncEnabled && !gameSyncDisabled && guardCandidate`. `guardCandidate` is
already computed on the exit path — use it, do not recompute.

`guardCandidate` is `tracked || !isTrackingReady`, so when tracking is not ready
an untracked game still allocates on both paths. Only the tracking-ready-and-untracked
case changes.

**RED:** an existing test encodes the behavior being removed.
`src/controllers/gameLifecycleController.test.ts:191`,
`"starts the buffered post-game watch when the frontend tracking cache is stale"`,
sets `isTracked` to `false` but inherits the shared fixture's
`trackingReadiness: "ready"` (line 39). Its title describes a stale cache but its
state says ready, so T7 would break it.

First correct that fixture so its snapshot explicitly sets
`trackingReadiness: "failed"`, keeping its existing expectation that the watch
starts. That makes the test match its own name.

Then add three exit-path tests:

1. tracked, tracking ready → watch starts;
2. untracked, tracking ready → watch does **not** start;
3. untracked, tracking **not** ready → watch starts. (Negative control: fails if
   you gate on bare `tracked` instead of `guardCandidate`.)

Run:

```bash
pnpm run test:unit
```

Record the failure output. At RED only test 2 should fail. If the corrected
stale-cache test or tests 1 or 3 fail, repair the fixture before touching
production code.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T7"`,
`src/controllers/gameLifecycleController.tsx`, `pnpm run test:unit`.

**Commit:** `fix(lifecycle): gate the post-game Syncthing watch on tracking state`

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

This section is self-contained. The orchestration engine's authoring references
are not present in this repository, so do not try to open them — everything you
need is stated here.

Two rules govern every step below:

- **Propagate unexpected failure.** `cmd; echo "exit=$?"` reports `echo`'s
  status. Capture with `cmd || rc=$?` instead, and make the block exit non-zero
  when a result contradicts what the step is asserting.
- **Output is evidence only when it names the expected tests** or gives the
  requested pass/fail tallies. A non-zero exit caused by an unrelated failure is
  not proof of anything.

Each task above carries its own gate and mutation check; those are not repeated
here. The steps below run once, after T7.

### V1 — Full suite

```bash
scripts/orchestration/run-quality-gates
```

Record the actual pass/fail tallies from `pytest` and `vitest`, and the exit
code. Do not report "gates passed" without the counts.

Compare against `/tmp/sdh_ludusavi/baseline-pytest.txt` and
`/tmp/sdh_ludusavi/baseline-vitest.txt`. Both counts must have grown by the
number of tests you added. A count that did not grow means your new tests were
never collected — investigate rather than proceeding.

If either baseline file is missing, stop and report V1 as failed. A pre-change
count cannot be reconstructed after the fact: by this point the implementation
and the new tests are both committed, so stashing implementation files would
still leave the new tests present and give a wrong number.

### V2 — Cross-task regression on the shared functions

T2 and T3 both edit `invalidate()`; T1 and T4 both edit `stop()`. Run those two
files together and record the tallies:

```bash
./run.sh uv run pytest tests/test_gateway.py tests/test_service.py -q
```

This fails if T3 undid T2's shutdown call, or if T4's stopping-state placement
broke T1's `finally`.

### V3 — Negative control: the whole change set is load-bearing

Run after V1 and V2, not before.

Every task is committed by now, so `git stash` has nothing to stash. Roll the
five implementation files back to the branch's merge base instead — an immutable
SHA, so this does not depend on local `dev` staying stationary during
implementation — leaving all your new tests in place:

```bash
(
  set -u
  base_sha="$(git merge-base HEAD dev)"

  git checkout "$base_sha" -- \
    py_modules/sdh_ludusavi/service.py \
    py_modules/sdh_ludusavi/gateway.py \
    src/index.tsx \
    src/surfaces/autoSyncStatusBrowserView.ts \
    src/controllers/gameLifecycleController.tsx

  git status --short

  python_exit=0
  frontend_exit=0
  ./run.sh uv run pytest -q || python_exit=$?
  pnpm run test:unit || frontend_exit=$?

  printf 'python_exit=%s\n' "$python_exit"
  printf 'frontend_exit=%s\n' "$frontend_exit"

  git checkout HEAD -- \
    py_modules/sdh_ludusavi/service.py \
    py_modules/sdh_ludusavi/gateway.py \
    src/index.tsx \
    src/surfaces/autoSyncStatusBrowserView.ts \
    src/controllers/gameLifecycleController.tsx

  restored_status="$(git status --short)"
  if [[ -n "$restored_status" ]]; then
    printf '%s\n' "$restored_status" >&2
    echo "working tree was not clean after V3 restoration" >&2
    exit 1
  fi

  if (( python_exit == 0 || frontend_exit == 0 )); then
    echo "one or more reverted suites unexpectedly passed" >&2
    exit 1
  fi
)
```

The first `git status --short` must list all five files as modified. An empty
result means the rollback did nothing, so the run would be measuring your own
implementation and would pass for the wrong reason.

Read the failure output and record which test names failed. They must be tests
you added in T1-T7. Non-zero status caused only by unrelated failures is not
valid evidence, and the block exiting 0 means the plan is not done — say so
rather than proceeding.

### V4 — Session log

Record in `docs/agent_conversations/` per the repo protocol: date, objective,
files modified, tests added per task, the V1-V3 output, and any point where the
source disagreed with this plan's description of it.

### Deferred and not verified

State these explicitly in the session log rather than leaving them implied:

- **No on-device verification.** Nothing here is tested against a Steam Deck.
  The F10 race, the F11 stranded-thread path, and the F12 orphaned adapter are
  covered only by unit tests with injected fakes.
- **T5 is bounded best-effort, not a guarantee.** Decky does not await
  `onDismount`, so frontend cleanup is sequenced only against itself. T4 is the
  actual correctness boundary for the F10 race.
- **T3 does not eliminate adapter-construction subprocesses.** Discovery
  verification still runs its own `--version` call on every adapter build; only
  the diagnostics probe is suppressed.
- **The F4 BrowserView change is not observable in tests beyond the factory
  call.** Whether Steam reaps a created view was checked once on-device and
  showed no accumulation; the review records that as unproven either way.
- **`stop()`'s worst-case duration remains unbounded** in the strict sense — it
  scales with outstanding process records, leases, systemd scopes, and watches.
  T1 and T4 do not address that, and T4's drain adds a new wait to it.
- **The retracted findings F1 and F3 are not implemented**, and the log-hygiene
  findings F6-F9 are deferred to a separate plan.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished teardown-correctness
```

This writes:

```text
/tmp/sdh_ludusavi/teardown-correctness_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer teardown-correctness`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/teardown-correctness-review-*.md
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
   scripts/orchestration/clear-finished teardown-correctness
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
   git add docs/review/teardown-correctness-review-*.md
   git commit -m "docs(review): record teardown-correctness review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished teardown-correctness
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer teardown-correctness` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed teardown-correctness
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize teardown-correctness
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/teardown-correctness_finalized
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
scripts/orchestration/finalize teardown-correctness
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/teardown-correctness_finished
/tmp/sdh_ludusavi/teardown-correctness_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
