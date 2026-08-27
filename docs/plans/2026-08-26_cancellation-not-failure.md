# Plan: Treat Ludusavi cancellation as cancelled, not failed (cancellation-not-failure)

## Context

A cancelled Ludusavi command is reported as a **failed operation** at every layer it
passes through. Cancellation is ordinary control flow in this plugin — the plugin
cancels its own subprocesses on unload, and the watchdog cancels a pinned pre-game
restore whenever the launch gate is released — so the plugin manufactures failures
during normal use, including a durable "failed" history entry the user sees in the
QAM.

Observed on `steamdeck-legos` running `0.4.7-dev.g5490a99`, in
`/home/deck/homebrew/logs/SDH-Ludusavi/2026-08-26 12.57.01.log`:

```text
[2026-08-26 12:57:02,645][INFO]: backend: Unload started (pending_update=False)
[2026-08-26 12:57:02,758][ERROR]: refresh: refresh failed: Ludusavi operation was cancelled
```

The single cause is `coordinator.py:71-76`. `OperationCoordinator.run_locked`
catches `Exception` broadly, logs `f"{operation} failed: {exc}"` at ERROR, sets
`last_result="failed"` / `last_error=str(exc)`, and re-raises.
`LudusaviOperationCancelledError` (`ludusavi_executor.py:38`) is an `Exception`,
so every cancellation lands in that branch.

Two cancellation paths reach it, both reproduced against real subprocesses:

**Unload.** `main.py:_unload` -> `backend.stop` -> `service.py:189` ->
`gateway.py:168` -> `ludusavi.py:93` -> `ManagedLudusaviExecutor.shutdown()` ->
`cancel_all()`. A refresh sitting in `process.communicate()` then raises at
`ludusavi_executor.py:154-155` (the `record.cancellation_requested` branch, which
is why the message is "Ludusavi operation was cancelled" and not "executor is
shutting down"). Reproduction output:

```text
  [INFO] refresh: Starting refresh
  [ERROR] refresh: refresh failed: Ludusavi operation was cancelled
  state: {'last_result': 'failed', 'last_error': 'Ludusavi operation was cancelled'}
```

**Watchdog / explicit resume.** `_GuardedOperationManager.run`
(`watchdog_lease.py:97-101`) re-raises whatever its callback throws, so a token
cancel from `request_release` — either `"explicit resume"` (`watchdog.py:224`) or
the automatic gate-expiry thaw (`watchdog.py:350`, which already logs its own
WARNING) — propagates into `run_locked` as a failure. Reproduction output:

```text
  [INFO] start: Starting start  (game=X-Men Origins: Wolverine - Uncaged Edition)
  [ERROR] start: start failed: Ludusavi operation was cancelled  (game=...)
```

This second path is why the change is worth making. Downstream of `run_locked`,
`lifecycle.py:166-172` catches the exception and calls
`history.record_history(game, operation, trigger, "failed", message=str(exc))`
before re-raising. History is persisted (`history.py:105` -> `service._save_state`)
and sets `last_failure` for that game, so it survives a restart and renders in the
QAM. The re-raise then reaches `main.py:422`, which logs a full traceback through
`decky.logger.exception` and returns `{"status": "failed"}` to the frontend, which
surfaces a failure in the auto-sync overlay.

So today: the user launches a game, the pre-game restore starts, the user hits
resume before it finishes — and the plugin records a permanent restore failure for
a game whose saves were never touched.

Files in scope:

```text
py_modules/sdh_ludusavi/coordinator.py
py_modules/sdh_ludusavi/lifecycle.py
main.py
src/formatting/operationText.ts
tests/test_coordinator.py
tests/test_service.py
tests/test_main.py
src/formatting/operationText.test.ts
docs/agent_conversations/<implementation-date>_cancellation-not-failure.json
```

Run every frontend command through the project wrapper: `./run.sh pnpm ...`, not
bare `pnpm`. `scripts/quality_gates.sh` uses the wrapper and the repo contract
requires it.

Decisions already made — implement these, do not revisit:

- **Cancellation stays an exception.** `run_locked` still re-raises. Callers rely
  on the exception for control flow and the lock release lives in `finally`. Only
  the log level, the recorded operation state, and the conversions at the two
  boundaries change.
- **`last_error` is cleared on cancellation.** `run_locked` sets
  `last_result="cancelled"` and `last_error=None`. There was no error, and
  `get_status()` feeds the QAM's last-operation display.
- **The reason string is `cancelled`.** It joins the existing skipped-reason
  vocabulary (`local_current`, `gate_lost`, `operation_running`, ...). Do not add a
  new top-level status.
- **A cancellation records a skipped history entry, not nothing.** The user
  should be able to see that a restore was cancelled, so the history entry is
  written, with `status="skipped"` and `reason="cancelled"`. `history.py:95`
  routes any non-`backed_up`/`restored`/`failed` status to the `last_skip` slot.
- **Cancellation is not silent in the UI.** Do not add `cancelled` to
  `SILENT_SKIPPED_REASONS` (`src/controllers/gameLifecycleDecision.ts:8`). A
  cancelled pre-game restore means saves were not restored; the overlay should say
  so rather than disappear.
- **`lifecycle._execute_operation` must not route the cancellation through
  `dependencies.skip`.** In these paths `skip`'s first argument is the lifecycle
  *phase*, not the Ludusavi operation: `restore_game_on_start` calls
  `skip("start", ...)` five times (`lifecycle.py:423-432`) while invoking
  `_execute_operation` with `operation="restore"`, and `backup_game_on_exit` calls
  `skip("exit", ...)` while the operation is `"backup"`. `service._skip`
  (`service.py:625-644`) derives the history trigger from that first argument, so
  passing `operation` would record `manual_restore` for a restore the auto-sync
  triggered. `_execute_operation` has no phase in scope — but it does have the
  correct `operation` and `trigger` pair, and its own `local_current` branch
  (`lifecycle.py:154-162`) already writes history directly with them. Follow that
  neighbouring pattern.

One existing test asserts the behaviour being replaced:

```text
tests/test_service.py:1243
test_cancelled_guarded_restore_records_failure_and_releases_the_coordinator_lock
```

It came from `5083ddc test(autosync): specify launch gate safety`, a test-only
commit that characterized what the code already did. **This plan authorizes
rewriting it** under T2 — required by scope-discipline rule 3, which otherwise
forbids editing a test's expected value. Its lock-release assertion is
load-bearing and must survive the rewrite; its failure-recording assertion is the
defect and must be inverted. Record the rationale in the session log.

No other test asserts the old behaviour: `tests/test_main.py:253` and `:273`
assert `logger.exceptions == ["refresh failed"]` for a generic `RuntimeError` and a
`BaseException`, neither of which is a cancellation, and both must still pass
unchanged after T3.

**Slug used throughout this plan:** `cancellation-not-failure`

---

## Orchestration Contract

**Slug:** `cancellation-not-failure`

**Plan file:**

```text
docs/plans/2026-08-26_cancellation-not-failure.md
```

**Implementation branch:**

```text
feat/cancellation-not-failure
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/cancellation-not-failure_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/cancellation-not-failure_finalized
```

**Review notes:**

```text
docs/review/cancellation-not-failure-review-*.md
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
git checkout -b feat/cancellation-not-failure
```

Commit this plan first:

```bash
git add docs/plans/2026-08-26_cancellation-not-failure.md
git commit -m "docs(plan): add cancellation-not-failure implementation plan"
```

---

## Implementation Tasks

Five tasks. Each is one coherent change and one commit. Every behavior-changing
task has a mutation gate that must pass before its commit.

Order for behavior-changing tasks is: RED, GREEN, gate, commit. **Run each task's
gate before its commit** — the gate reverts the implementation file with
`git stash push`, which needs it to remain uncommitted.

T1 through T3 must land in order. Each converts the cancellation at a different
layer, and T2's and T3's tests describe results that only exist once T1 stopped
treating cancellation as a generic failure.

### The mutation gate

This repository has had unrelated stashes in the past, so the gate must never pop
a stash it did not create. It also captures the mutation run's exit status
explicitly: `cmd; echo "exit=$?"` reports `echo`'s status, not the command's.

Use this pattern verbatim, changing only `task_label`, `implementation_file`, and
`test_command`:

```bash
(
  set -u
  task_label="T1"
  implementation_file="py_modules/sdh_ludusavi/coordinator.py"
  test_command=(./run.sh uv run pytest tests/test_coordinator.py -q)

  "${test_command[@]}" || exit 1

  before_stash="$(git rev-parse -q --verify refs/stash || true)"
  git stash push -m "cancellation-not-failure-${task_label}-mutation" -- \
    "$implementation_file" || exit 1
  after_stash="$(git rev-parse -q --verify refs/stash || true)"

  if [[ -z "$after_stash" || "$after_stash" == "$before_stash" ]]; then
    echo "mutation gate created no stash; refusing to pop existing work" >&2
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

A non-zero `mutation_exit` is valid evidence only if the output **names the
task's new tests**. A collection error or unrelated failure is not a negative
control. Read the output; never infer from the status alone.

### A caution specific to this plan

Every task here changes how one exception is classified. It is easy to write a
test that passes before the change: a test that merely raises
`LudusaviOperationCancelledError` and asserts the call raised, or that asserts a
log record exists, describes the old behaviour just as well as the new one.

Each test must assert on **the distinction the change creates** — a level that is
no longer `error`, a status that is `skipped` rather than `failed`, a history slot
that stayed `None`, a traceback that was not logged. When a test asserts an
absence, it must also assert the corresponding presence, so a test that exercises
nothing cannot pass.

### Baseline

Capture before starting T1:

```bash
(
  set -euo pipefail
  ./run.sh uv run pytest -q 2>&1 | tail -3 | tee /tmp/sdh_ludusavi/cnf-baseline-pytest.txt
  ./run.sh pnpm run test:unit 2>&1 | tail -5 | tee /tmp/sdh_ludusavi/cnf-baseline-vitest.txt
)
```

Record both counts in the session log.

---

### T1 — The coordinator stops calling cancellation a failure

**File:** `py_modules/sdh_ludusavi/coordinator.py`

**Change:** import `LudusaviOperationCancelledError` from `.ludusavi_executor` and
add an `except` branch **before** the existing broad `except Exception` at line 71:

- log at `debug`, with a message that says cancelled, not failed;
- set `self._operation.last_result = "cancelled"`;
- set `self._operation.last_error = None`;
- `raise`.

Leave the broad `except Exception` branch exactly as it is. The `finally` block
that releases the lock and clears `is_running` already covers both branches — do
not duplicate it.

`ludusavi_executor` imports only `pyludusavi` and the standard library, and
nothing in it imports `coordinator`, so this import introduces no cycle. Verify
that before you write it:

```bash
./run.sh uv run python -c "import sdh_ludusavi.coordinator"
```

**RED:** add to `tests/test_coordinator.py` a test that runs `run_locked` with a
callback raising `LudusaviOperationCancelledError` and a recording log callback,
then asserts all of:

- the exception propagates (`pytest.raises`);
- **zero** recorded log entries at level `error`;
- **exactly one** recorded entry at level `debug` whose message names the
  operation;
- `get_status()["last_result"] == "cancelled"`;
- `get_status()["last_error"] is None`;
- the lock was released — a second `run_locked` on the same coordinator returns
  normally.

Add a second test in the same commit asserting the unchanged path: a callback
raising `RuntimeError` still logs at `error`, still sets `last_result == "failed"`,
and still sets `last_error`. Without it, deleting the whole `except Exception`
branch would pass.

`tests/test_coordinator.py` currently passes a `DummyService` whose `log` swallows
everything; write a recording callback instead of reusing it.

```bash
./run.sh uv run pytest tests/test_coordinator.py -q
```

Record the failure output. The cancellation test must fail on the level or the
`last_result` assertion. If it fails because the exception did not propagate, the
test is wrong, not the code.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T1"`.

**Commit:**

```text
fix(coordinator): treat Ludusavi cancellation as cancelled, not failed
```

---

### T2 — A cancelled lifecycle operation is a skip, not a failure

**File:** `py_modules/sdh_ludusavi/lifecycle.py`

**Change:** in `_execute_operation`, add an `except LudusaviOperationCancelledError`
branch between the existing `except _GateLostError` (line 163) and the broad
`except Exception` (line 166). It must, in this order:

- record history with the `operation` and `trigger` already in scope, using
  `status="skipped"` and `reason="cancelled"`, exactly as the `local_current`
  branch at `lifecycle.py:154-162` does;
- log at `info` that the operation was cancelled, naming the operation and game;
- return `{"status": "skipped", "reason": "cancelled", "game": game_name}`.

Do not call `self.dependencies.skip(...)`. The Context section explains why: in
the guarded start and exit paths `skip`'s first argument is the lifecycle phase,
not the operation, and `service._skip` would derive the wrong history trigger from
the value `_execute_operation` holds.

Do not re-raise. This branch converts the cancellation into a return value; that
is the point of the task.

Clause order matters. `LudusaviOperationCancelledError` is an `Exception`, so a
branch placed after the broad one is dead code.

**RED:** rewrite `tests/test_service.py:1243`,
`test_cancelled_guarded_restore_records_failure_and_releases_the_coordinator_lock`.
The Context section authorizes this rewrite; nothing else in that file may change.

Rename it to describe the new contract and assert all of:

- `service.restore_game_on_start(...)` **returns** rather than raising, and the
  result is `{"status": "skipped", "reason": "cancelled", "game": ...}`;
- `service.get_game_history()["Hades"]["last_failure"] is None`;
- the recorded skip entry exists and carries the auto-start identity, not a manual
  one: `history["last_skip"]` has `status == "skipped"`, `reason == "cancelled"`,
  `operation == "restore"`, and `trigger == "auto_start"`. The trigger assertion is
  what catches a `dependencies.skip` implementation, which would record
  `manual_restore`;
- `history["last_restore"] is None`, as the original asserted;
- the coordinator lock was released: a subsequent service operation on the same
  service succeeds rather than returning `operation_running`.

Keep the `finally: service.resume_all_paused_processes()` teardown from the
original.

```bash
./run.sh uv run pytest tests/test_service.py -q -k cancelled
```

Record the failure output. Before T2 the call raises, so the failure must be the
uncaught `LudusaviOperationCancelledError` — not an assertion about history.

**GREEN:** make the change. Re-run the full file, not just `-k cancelled`:

```bash
./run.sh uv run pytest tests/test_service.py -q
```

Record the tallies. If any other test in that file fails, stop and report it —
this task is not authorized to change any other test.

**Gate:** the mutation gate with `task_label="T2"`,
`implementation_file="py_modules/sdh_ludusavi/lifecycle.py"`,
`test_command=(./run.sh uv run pytest tests/test_service.py -q)`.

**Commit:**

```text
fix(lifecycle): record a cancelled operation as skipped, not failed
```

---

### T3 — The RPC boundary stops logging a traceback for cancellation

**File:** `main.py`

**Change:** in `Plugin._call`, add an `except LudusaviOperationCancelledError as exc`
branch **before** the broad `except Exception` at line 421:

- log at debug through `decky.logger.debug`, naming the operation;
- return `{"status": "skipped", "reason": "cancelled", "message": str(exc)}`.

Do not call `decky.logger.exception` in this branch. Leave the `asyncio.CancelledError`,
`SystemExit`/`KeyboardInterrupt`, `OperationLockedError`, and `BaseException`
branches untouched.

T2 already converts lifecycle cancellations before they reach here. T3 covers
every other `_call` path — manual backup and restore, `unload_stop` — which go
through `run_locked` directly and still raise.

**RED:** add to `tests/test_main.py`, beside the existing `_call` tests, a test
asserting:

- `asyncio.run(plugin._call("refresh", raise_cancelled))` returns
  `{"status": "skipped", "reason": "cancelled", "message": ...}`;
- `logger.exceptions == []`.

Check `fake_decky_module` in that file records `debug` calls before asserting on
them; if it does not, assert only on `logger.exceptions` being empty and on the
returned dict, and say so in the session log rather than extending the fake.

The two existing tests at `tests/test_main.py:253` and `:273` must keep passing
unchanged. Run them explicitly and record the result:

```bash
./run.sh uv run pytest tests/test_main.py -q
```

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T3"`,
`implementation_file="main.py"`,
`test_command=(./run.sh uv run pytest tests/test_main.py -q)`.

**Commit:**

```text
fix(rpc): return cancelled operations as skipped without a traceback
```

---

### T4 — The QAM says cancelled in words

**File:** `src/formatting/operationText.ts`

**Change:** add `case "cancelled":` to the skipped-reason switch inside
`getLastOperationText`, with the detail string:

```text
cancelled before it finished
```

That switch already has a `default` that renders an unknown reason as
`reason.replace(/_/g, " ")`, so before this change `cancelled` renders as
`Restore skipped — cancelled`. The new detail must differ from that default text,
or the test asserting it passes without the change.

Do not touch `src/controllers/gameLifecycleDecision.ts`. `cancelled` stays out of
`SILENT_SKIPPED_REASONS` deliberately.

**RED:** add to `src/formatting/operationText.test.ts` a test asserting
`getLastOperationText("skipped", "cancelled", null, "start")` returns exactly:

```text
Restore skipped — cancelled before it finished
```

Confirm the em dash and spacing against the existing cases in that file rather
than copying them from this plan.

```bash
./run.sh pnpm run test:unit
```

Record the failure output. It must show the received string as
`Restore skipped — cancelled` (the default branch). Any other received value means
the call signature is wrong.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T4"`,
`implementation_file="src/formatting/operationText.ts"`,
`test_command=(./run.sh pnpm run test:unit)`.

**Commit:**

```text
feat(ui): label a cancelled operation as cancelled in the QAM
```

---

### T5 — Session log

Covered by V5. It is listed here so the task count matches the commit count.

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

This section is self-contained. Two rules govern every step:

- **Propagate unexpected failure.** `cmd; echo "exit=$?"` reports `echo`'s status.
  Capture with `cmd || rc=$?`, and make the block exit non-zero when a result
  contradicts what the step asserts.
- **Output is evidence only when it names the expected tests** or gives the
  requested tallies. A non-zero exit from an unrelated failure proves nothing.

These two rules are the short form of the orchestration program's
`references/verification-standards.md`; that document is the authority and is not
restated here.

Each task carries its own mutation gate; those are not repeated here. The steps
below run once, after T4.

### V1 — Full suite

```bash
scripts/orchestration/run-quality-gates
```

Record the actual pytest and vitest tallies and the exit code. Compare pytest
against `/tmp/sdh_ludusavi/cnf-baseline-pytest.txt` and vitest against
`/tmp/sdh_ludusavi/cnf-baseline-vitest.txt`. Each framework's count must grow by
the number of new cases **collected in that framework** — do not compare either
against the combined total. Note that T2 rewrites an existing test rather than
adding one, so the pytest count grows by the new tests only.

If a baseline file is missing, stop and report V1 as failed rather than
reconstructing it: after T4 the implementation and tests are both committed, so no
honest baseline can be recovered.

The quality gate runs mutating `ruff check --fix` and `ruff format` commands, so
require `git status --short` to be clean afterward. If it shows changes to files
this session owns, inspect them, commit the corrections, rerun V1, and require a
clean tree before V2.

### V2 — The three backend conversions are independently required

The T1-T3 mutation gates already established this, each by reverting one file. V2
confirms the three still hold together after all of them landed:

```bash
./run.sh uv run pytest tests/test_coordinator.py tests/test_service.py tests/test_main.py -q
```

Record the tallies. Also record, verbatim, the result of the two pre-existing
`_call` tests that must not have changed:

```bash
./run.sh uv run pytest tests/test_main.py -q \
  -k "maps_generic_exception_from_worker_thread or maps_base_exception_from_worker_thread"
```

Both must run and pass. `pytest` exits 5 when a `-k` expression selects nothing,
so a renamed or deleted test fails this step rather than silently passing it.

If either now fails, T3's branch is catching more than cancellation. Stop and
report it.

### V3 — Negative control: the reverted implementation is detected

Run after V1 and V2, from a clean working tree.

```bash
(
  set -u
  base_sha="$(git merge-base HEAD dev)" || exit 1
  files=(
    py_modules/sdh_ludusavi/coordinator.py
    py_modules/sdh_ludusavi/lifecycle.py
    main.py
    src/formatting/operationText.ts
  )

  restore_v3() { git checkout HEAD -- "${files[@]}"; }
  trap restore_v3 EXIT

  git checkout "$base_sha" -- "${files[@]}" || exit 1

  missing_rollback=0
  for file in "${files[@]}"; do
    if git diff --cached --quiet HEAD -- "$file"; then
      printf 'rollback did not change %s\n' "$file" >&2
      missing_rollback=1
    fi
  done
  (( missing_rollback == 0 )) || exit 1
  git status --short

  python_exit=0
  frontend_exit=0
  ./run.sh uv run pytest -q || python_exit=$?
  ./run.sh pnpm run test:unit || frontend_exit=$?

  printf 'python_exit=%s\nfrontend_exit=%s\n' "$python_exit" "$frontend_exit"

  restore_v3 || exit 1
  trap - EXIT

  restored="$(git status --short)"
  if [[ -n "$restored" ]]; then
    printf '%s\n' "$restored" >&2
    echo "working tree not clean after V3 restoration" >&2
    exit 1
  fi

  if (( python_exit == 0 || frontend_exit == 0 )); then
    echo "one or more reverted suites unexpectedly passed" >&2
    exit 1
  fi
)
```

The per-file loop asserts the rollback actually changed all four paths; an
unchanged file would mean the run was measuring your own implementation. The
`trap` guarantees restoration even if the block exits early.

Record the names of the tests that failed. This aggregate gate proves only that at
least one reverted Python behaviour and at least one reverted frontend behaviour
are detected; per-file coverage comes from the individual task mutation gates.

### V4 — On-device behaviour is deferred

The behaviour this plan exists for — pressing resume during a pre-game restore no
longer records a failure — cannot be observed by any command in V1-V3. Those
commands build and test the plugin but never launch it, so they produce no Decky
runtime log and touch no real launch gate.

Mark V4 **deferred** in the session log. Do not substitute an older log, do not
run a partial approximation, and do not describe the deferred check as done.

Record this recipe in the session log so the user can run it after a dev release:

1. Install the dev build on a Deck and enable debug logging.
2. Launch a tracked game whose backup is newer than the local save, so the
   pre-game restore actually runs.
3. Press resume while the launch gate is still held.
4. In `/home/deck/homebrew/logs/SDH-Ludusavi/`, the newest log must contain **no**
   line matching `start failed: Ludusavi operation was cancelled` and **no**
   traceback for that operation, and must contain a `Skipped start` line whose
   reason is `cancelled`.
5. In the QAM, that game's history must show a skipped entry, not a failure, and
   the last-operation text must read `Restore skipped — cancelled before it
   finished`.

### V5 — Session log

Create `docs/agent_conversations/<implementation-date>_cancellation-not-failure.json`
per the repo protocol. Record: date, objective, files modified, tests added per
task, the V1-V3 output, the V4 deferral, the rationale for rewriting
`tests/test_service.py:1243`, whether `fake_decky_module` records `debug` calls
(T3), and every point where the source disagreed with this plan.

Stage that exact path and commit it:

```text
docs(session): record cancellation-not-failure implementation
```

Require `git status --short` to be clean afterward.

### Deferred and not verified

State these explicitly in the session log:

- **No on-device verification.** See V4. Nothing here is tested on a Steam Deck,
  and the watchdog gate-expiry path is exercised only by unit tests.
- **The unload cancellation is not covered end to end.** T1 and T3 make it quiet,
  but the observed instance came from a refresh whose exception
  `registry.refresh_games` (`registry.py:171-180`) swallows into
  `dependency_error` before it can reach `_call`. That frontend path — a cancelled
  refresh surfacing as `Ludusavi refresh failed` at
  `src/components/qam/LudusaviContent.tsx:281` — is deliberately out of scope, so
  a cancelled refresh may still be reported as a refresh failure in the UI if the
  frontend is still alive to receive it. Note it for a separate plan.
- **Timing was not measured.** The change adds one `except` clause per layer and
  is not expected to affect operation latency; nothing here measures that.
- **`last_result="cancelled"` is a new value in the operation-status vocabulary.**
  Consumers of `get_operation_status` were not audited for how they render an
  unrecognized value. `OperationState` is in-memory only, so the value never
  survives a plugin restart.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished cancellation-not-failure
```

This writes:

```text
/tmp/sdh_ludusavi/cancellation-not-failure_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer cancellation-not-failure`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/cancellation-not-failure-review-*.md
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
   scripts/orchestration/clear-finished cancellation-not-failure
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
   git add docs/review/cancellation-not-failure-review-*.md
   git commit -m "docs(review): record cancellation-not-failure review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished cancellation-not-failure
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer cancellation-not-failure` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed cancellation-not-failure
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize cancellation-not-failure
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/cancellation-not-failure_finalized
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
scripts/orchestration/finalize cancellation-not-failure
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/cancellation-not-failure_finished
/tmp/sdh_ludusavi/cancellation-not-failure_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
