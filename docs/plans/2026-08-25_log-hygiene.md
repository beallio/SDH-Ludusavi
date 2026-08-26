# Plan: Log hygiene for plugin diagnostics (log-hygiene)

## Context

The plugin's diagnostic log is hard to read and roughly one line in seven carries
no information. Four defects were confirmed by source inspection and recorded as
F6-F9 in `docs/review/load-unload-lifecycle-review-01.md`. They were deliberately
deferred out of the teardown-correctness plan; this plan implements them.

This is observability work. No runtime behaviour outside logging changes.

What is wrong today:

- `log_buffer.py:95` formats `f"{operation or 'frontend'}: {message}"`, so every
  unlabelled line is stamped `frontend:` — including backend-originated ones such
  as `Unload started` and `Startup reconciliation`. Nothing in the log tells you
  which side emitted a line.
- `registry.py:281` logs one DEBUG line per game inside `_coerce_game_status`, a
  pure dict-to-dataclass mapper. That was 56 of 660 lines (8.5%) in the sampled
  logs and scales linearly with library size.
- The update check is narrated twice, in two vocabularies, from **opposite sides
  of the RPC boundary**: structured trace-id events from
  `src/controllers/pluginUpdateController.tsx` (`check_start`, `check_reuse`,
  `check_success`) and prose from `py_modules/sdh_ludusavi/updater.py`
  (`Update check started`, `Update check cache hit`).
- Three smaller items: a dead `statusView.setContext` call in `hide()`, two
  different events sharing the message prefix `Syncthing watch allocated`, and the
  Syncthing config parser logging its ElementTree fallback at INFO on every parse
  when it is a constant for the Decky runtime.

Files in scope:

```text
py_modules/sdh_ludusavi/log_buffer.py
py_modules/sdh_ludusavi/registry.py
py_modules/sdh_ludusavi/updater.py
py_modules/sdh_ludusavi/syncthing/config.py
main.py
scripts/analyze_plugin_logs.py
src/surfaces/autoSyncStatusSurface.tsx
src/controllers/syncthingMonitor.ts
tests/test_log_buffer.py
tests/test_registry.py
tests/test_updater_service.py
tests/test_syncthing.py
tests/test_analyze_plugin_logs.py
tests/test_main_rpc.py
src/surfaces/autoSyncStatusSurface.test.ts
src/controllers/syncthingMonitor.failures.test.ts
docs/agent_conversations/<implementation-date>_log-hygiene.json
```

Run every frontend command through the project wrapper: `./run.sh pnpm ...`, not
bare `pnpm`. `scripts/quality_gates.sh` uses the wrapper and the repo contract
requires it.

Decisions already made — implement these, do not revisit:

- **F6 direction.** `log_buffer.log` defaults the label to `backend`. The
  `Plugin.log` RPC in `main.py` is by definition called from the frontend, so it
  supplies `frontend` when its caller passed no operation. Getting this backwards
  would mislabel every frontend message that omits an operation, and there are
  many — `App started:` and `Could not match game` among them.
- **F6 compatibility.** `scripts/analyze_plugin_logs.py` accepts both `frontend:`
  and `backend:`, preferring the new labelling. Old logs stay parseable. The
  ambiguity in historical logs — a `frontend:` line there may be a real frontend
  message or an unlabelled backend one — must be documented in the analyzer, not
  silently assumed away.
- **F8 direction.** Keep the trace-id stream; it carries correlation IDs the
  update flow uses across revalidate, install, and handoff. Demote the backend
  prose duplicates to DEBUG so they remain available when debugging.

Verified before writing this plan, to correct two claims in the source review:

- The review said F6 "ripples into `scripts/analyze_plugin_logs.py`". Its
  `LOG_LINE_RE` captures the whole message and **no** analyzer regex anchors on
  the `frontend:` prefix, so changing the default does not break parsing. The
  compatibility work in T6 is defensive and small, not a forced migration.
- The review described F8 as one component logging twice. It is two components on
  opposite sides of the RPC boundary, which is why T7 touches only the backend.

**Slug used throughout this plan:** `log-hygiene`

---

## Orchestration Contract

**Slug:** `log-hygiene`

**Plan file:**

```text
docs/plans/2026-08-25_log-hygiene.md
```

**Implementation branch:**

```text
feat/log-hygiene
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/log-hygiene_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/log-hygiene_finalized
```

**Review notes:**

```text
docs/review/log-hygiene-review-*.md
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
git checkout -b feat/log-hygiene
```

Commit this plan first:

```bash
git add docs/plans/2026-08-25_log-hygiene.md
git commit -m "docs(plan): add log-hygiene implementation plan"
```

---

## Implementation Tasks

Seven atomic tasks. Each is one coherent change and one commit. Every
behavior-changing task has a mutation gate that must pass before its commit.

T6 is a deliberate exception: the analyzer already accepts both labels, so that
task adds regression coverage and a documented limitation. It has no RED, no
GREEN, and no mutation gate, because no parser behaviour changes.

Order for behavior-changing tasks is: RED, GREEN, gate, commit. **Run each
task's gate before its commit** — the gate reverts the implementation file with
`git stash push`, which needs it to remain uncommitted.

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
  implementation_file="py_modules/sdh_ludusavi/registry.py"
  test_command=(./run.sh uv run pytest tests/test_registry.py -q)

  "${test_command[@]}" || exit 1

  before_stash="$(git rev-parse -q --verify refs/stash || true)"
  git stash push -m "log-hygiene-${task_label}-mutation" -- \
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

Most tasks here change logging text, level, frequency, or call count. That makes
it unusually easy to write a test that asserts nothing: one that greps for a
string you just wrote passes whether or not the change was correct.

Each test must assert on **the distinction the change creates** — a count
dropping, one label differing from another, a level changing — not merely that
some string is present.

T5 is the sharpest example and is called out in that task: the rendered text is
byte-identical before and after the change, so any test asserting on rendered
text is a no-op. It must assert on the forwarded arguments instead.

### Baseline

Capture before starting T1:

```bash
(
  set -euo pipefail
  ./run.sh uv run pytest -q 2>&1 | tail -3 | tee /tmp/sdh_ludusavi/lh-baseline-pytest.txt
  ./run.sh pnpm run test:unit 2>&1 | tail -5 | tee /tmp/sdh_ludusavi/lh-baseline-vitest.txt
)
```

Record both counts in the session log.

---

### T1 — Stop logging one line per game in the status mapper (F7)

**File:** `py_modules/sdh_ludusavi/registry.py`

**Change:** delete the `self.log("debug", f"Coercing status for ...", "refresh")`
call at line 281, inside `_coerce_game_status`. This is a pure deletion — add no
replacement line anywhere. Two separate loops drive this mapper (cache loading
and refresh), so a discretionary summary line would land inconsistently.
Failures already surface as exceptions; the per-game line adds nothing.

**RED:** add to `tests/test_registry.py` a test that runs a refresh over a
multi-game fixture with a recording log callback and asserts **zero** log records
whose message starts with `Coercing status for`. Assert on the count, not on
absence of a substring anywhere.

```bash
./run.sh uv run pytest tests/test_registry.py -q
```

Record the failure output. It must fail showing a non-zero count equal to the
fixture's game count. A failure showing zero means the fixture never exercised
the mapper.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T1"`.

**Commit:** `refactor(registry): drop per-game coerce logging`

---

### T2 — Remove the dead setContext call (F9)

**File:** `src/surfaces/autoSyncStatusSurface.tsx`

**Change:** in `hide()`, the first `statusView.setContext(currentAutoSyncStatusState)`
runs immediately before `currentAutoSyncStatusState` is reassigned, and a second
`setContext` follows with the new value. Delete the first call only. Leave the
second `setContext` and the `sync` call exactly as they are.

Confirm by reading `hide()` that exactly two `setContext` calls exist there
before you edit; other methods in this file also call `setContext` and must not
be touched.

**RED:** add to a suitable test file under `src/surfaces/` a test asserting that
one `hide()` invocation calls `setContext` exactly **once**, and that the value it
receives has `visible: false`. The count is the assertion that matters — a test
that only checks the final value passes with the dead call still present.

```bash
./run.sh pnpm run test:unit
```

Record the failure output; it must report 2 calls received.

`src/surfaces/autoSyncStatusSurface.test.ts` already exists — add the case there.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T2"`,
`implementation_file="src/surfaces/autoSyncStatusSurface.tsx"`, and
`test_command=(./run.sh pnpm run test:unit)`.

**Commit:** `refactor(ui): drop dead setContext call in hide`

---

### T3 — Give the two watch-allocation events distinct messages (F9)

**File:** `src/controllers/syncthingMonitor.ts`

**Change:** line 136 logs `Syncthing watch allocated: ... watch_id=null` at the
moment allocation is *requested*; line 410 logs `Syncthing watch allocated:` again
with the real watch ID once it exists. Two different events share one prefix.
Change the line 136 message to `Syncthing watch requested:` and keep its fields.
Leave line 410 unchanged.

**RED:** add the case to `src/controllers/syncthingMonitor.failures.test.ts`,
which already mocks logging and has a deferred `startWatch` promise to build on.

Assert synchronously after `start()` that a `Syncthing watch requested:` record
exists and **no** `Syncthing watch allocated:` record does. Then resolve the
deferred backend call, flush the promise, and assert the allocated record appears
exactly once. Asserting the presence of one and the absence of the other is what
makes this test real.

```bash
./run.sh pnpm run test:unit
```

Record the failure output.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T3"`,
`implementation_file="src/controllers/syncthingMonitor.ts"`, and
`test_command=(./run.sh pnpm run test:unit)`.

**Commit:** `refactor(syncthing): distinguish watch requested from allocated`

---

### T4 — Log the ElementTree fallback once, not per parse (F9)

**File:** `py_modules/sdh_ludusavi/syncthing/config.py`

**Change:** the fallback notice at line 205 is emitted at INFO on every parse.
Whether ElementTree is importable is a property of the runtime (`HAS_XML_ETREE`,
set at import time), not an event. Emit it at most once per process, keeping the
level and wording unchanged.

Use a module-level flag guarded by a `threading.Lock`. Up to four RPC workers can
enter Syncthing config discovery concurrently, so a bare boolean can emit twice
under a race. If you would rather not add the lock, weaken the requirement in the
docstring to best-effort once and say so in the session log — but do not claim
exactly-once while implementing best-effort.

**RED:** add the test to `tests/test_syncthing.py`, where this parser is already
covered. Import the live module as:

```python
import sdh_ludusavi.syncthing.config as syncthing_config
```

**Do not** copy the existing `py_modules.sdh_ludusavi.syncthing.config` import at
`tests/test_syncthing.py:55`. That loads a *different module object* from the one
the running code imports, so patching its flag has no effect on the function
under test and the test would pass against a no-op.

Force the live module's `HAS_XML_ETREE` to `False`, reset the new once-only
state in the fixture so test ordering cannot make this pass spuriously, call the
parser twice, and use `caplog` against `sdh_ludusavi.syncthing.config` to assert
exactly one fallback record.

```bash
./run.sh uv run pytest tests/test_syncthing.py -q
```

Record the failure output. It must fail showing 2 records.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T4"`,
`implementation_file="py_modules/sdh_ludusavi/syncthing/config.py"`, and
`test_command=(./run.sh uv run pytest tests/test_syncthing.py -q)`.

**Commit:** `refactor(syncthing): log the XML parser fallback once per process`

---

### T5 — Label backend lines `backend`, frontend lines `frontend` (F6)

**Files:** `py_modules/sdh_ludusavi/log_buffer.py`, `main.py`

This is the task where getting the direction backwards silently mislabels
everything. Read the Context decision on F6 before starting.

**Change, two parts:**

1. `log_buffer.py:95` — change the default from `'frontend'` to `'backend'`:
   `f"{operation or 'backend'}: {message}"`.
2. `main.py` — `Plugin.log` is the RPC the frontend calls, so it must supply the
   frontend label when its caller passed none. Forward
   `operation or "frontend"` to `backend.log`. The pre-construction fallback
   branch in that method already writes `operation or 'frontend'`; leave that
   branch's behaviour intact.

The net effect: a frontend call with no operation still reads `frontend:`, while a
direct backend call with no operation now reads `backend:`.

**RED:** the rendered log text is **byte-identical before and after this
change**. Before: `Plugin.log` forwards `operation=None` and the buffer default
renders `frontend:`. After: `Plugin.log` forwards `"frontend"` and the buffer
default is `backend`, still rendering `frontend:`. Any test asserting on rendered
text therefore passes against a no-op. Assert on the boundaries instead:

- In `tests/test_log_buffer.py`: patch `sdh_ludusavi.log_buffer._decky_log_fallback`.
  A direct `DiagnosticLogBuffer.log(...)` with no operation must send
  `backend: <message>` to the fallback; one with an explicit operation must
  preserve that operation. This fails until the buffer default changes.
- In `tests/test_main_rpc.py`: attach a *recording* backend to `plugin._backend`
  — the existing `MockService.log` is `pass` and records nothing, so it cannot
  witness this. Assert `Plugin.log(...)` with no operation forwards `"frontend"`
  as its operation argument, and that an explicit operation such as `"update"` is
  forwarded unchanged. The second assertion rejects the plausible wrong
  implementation that always forces `"frontend"`.
- `tests/test_main_rpc.py:257` exercises the pre-construction branch, because
  `_backend` is `None` there. Its `"[frontend:info] frontend: test message"`
  assertion must remain unchanged. Confirm that in the session log.

```bash
./run.sh uv run pytest tests/test_log_buffer.py tests/test_main_rpc.py -q
```

Record **both** named failures. A combined failure caused only by the log-buffer
test does not establish RED for the `main.py` half.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** run the mutation gate twice, once per file — `task_label="T5a"` with
`py_modules/sdh_ludusavi/log_buffer.py` and `task_label="T5b"` with `main.py`,
both using the combined test command above. Reverting either file alone must fail
the suite. If reverting one of them leaves the suite green, that half of the
change is untested.

**Commit:** `fix(logging): label backend log lines backend, not frontend`

---

### T6 — Characterize analyzer compatibility with both labels (F6)

**Files:** `scripts/analyze_plugin_logs.py`, `tests/test_analyze_plugin_logs.py`

The analyzer already accepts both labels: `LOG_LINE_RE` captures the whole
message and every downstream event regex *searches* rather than anchors. This
task is a passing characterization plus a documented limitation. It is **not** a
behaviour change, has no RED/GREEN, and gets no mutation gate.

**Change:** add this comment beside `LOG_LINE_RE`, without restructuring the
parser:

```python
# Origin labels remain part of `message`. Downstream event regexes search rather
# than anchor, so both `frontend:` and `backend:` parse identically. Historical
# `frontend:` lines are origin-ambiguous: before the backend default changed,
# unlabelled backend messages were also rendered `frontend:`.
```

**Regression test:** add a case that feeds the analyzer equivalent evidence
twice, once labelled `frontend:` and once `backend:`, and asserts the normalized
findings match (excluding filename and evidence text) with zero parse failures in
both runs. Use an event that actually produces a finding — two empty results
would be a trivial pass.

Existing coverage to preserve: seven of the eight fixtures under
`tests/fixtures/plugin_logs/` already contain `frontend:` lines, 19 lines in
total, plus inline `frontend:` lines in
`test_analyze_scope_freeze_and_thaw_watchdog_syntax` and
`test_analyze_malformed_lines_handled`. All of it must keep passing unchanged.
That is this task's regression control — it is not a mutation negative control,
because nothing in the parser changes.

```bash
./run.sh uv run pytest tests/test_analyze_plugin_logs.py -q
```

Run before and after adding the comment; it must pass both times.

**Commit:** `test(analyzer): cover backend and frontend log labels`

---

### T7 — Demote the duplicated update-check prose to DEBUG (F8)

**File:** `py_modules/sdh_ludusavi/updater.py`

**Change:** the backend emits prose that restates what the frontend's trace-id
stream already reports — `Update check started (version=..., force=...)` around
line 158 and `Update check cache hit (within 24h, ...)` around line 211. Demote
those to DEBUG. Change the level only: keep the wording, the fields, and the call
sites.

Touch only lines that duplicate a `check_start` / `check_reuse` / `check_success`
trace event. Leave every other updater log line at its current level, especially
anything on the revalidate, install, or handoff paths — those are safety-critical
and are not duplicated by the trace stream.

**RED:** use a recording `log_cb` and cover three distinct paths, so a broad
implementation cannot pass:

1. Run a forced uncached check, then an equivalent unforced check that takes the
   24-hour cache path. Assert exact `(level, message)` pairs showing
   `Update check started` and `Update check cache hit` at DEBUG.
2. On the uncached path, assert `Fetching GitHub releases` is still INFO.
3. Seed a matching pending install and assert
   `Update check pending-install fast path` is still INFO.

Assertions 2 and 3 are the negative controls. They reject the two plausible
over-broad implementations: demoting every INFO call in `check_for_update`, and
demoting every message beginning with `Update check`. The pre-change run must
fail specifically because the two target messages are INFO rather than DEBUG.

```bash
./run.sh uv run pytest tests/test_updater_service.py -q
```

Record the failure output.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T7"`,
`implementation_file="py_modules/sdh_ludusavi/updater.py"`, and
`test_command=(./run.sh uv run pytest tests/test_updater_service.py -q)`.

**Commit:** `refactor(updater): demote duplicated update-check prose to debug`

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

Each task carries its own gate; those are not repeated here. The steps below run
once, after T7.

### V1 — Full suite

```bash
scripts/orchestration/run-quality-gates
```

Record the actual pytest and vitest tallies and the exit code. Compare pytest
against `/tmp/sdh_ludusavi/lh-baseline-pytest.txt` and vitest against
`/tmp/sdh_ludusavi/lh-baseline-vitest.txt`. Each framework's count must grow by
the number of new cases **collected in that framework** — do not compare either
against the combined total. A count that did not grow means those tests were
never collected.

If a baseline file is missing, stop and report V1 as failed rather than
reconstructing it: after T7 the implementation and tests are both committed, so
no honest baseline can be recovered.

The quality gate runs mutating `ruff check --fix` and `ruff format` commands, so
require `git status --short` to be clean afterward. If it shows changes to files
this session owns, inspect them, commit the corrections, rerun V1, and require a
clean tree before V2.

### V2 — The two halves of T5 are independently required

```bash
./run.sh uv run pytest tests/test_log_buffer.py tests/test_main_rpc.py -q
```

Record the tallies. This rerun confirms the paired T5 contract is still green.

It does **not** by itself prove the two halves are independently required — that
was established by the T5a and T5b mutation gates, each of which reverted one
implementation file while leaving the other in place.

### V3 — Negative control: reverted backend and frontend groups are detected

Run after V1 and V2, from a clean working tree.

```bash
(
  set -u
  base_sha="$(git merge-base HEAD dev)" || exit 1
  files=(
    py_modules/sdh_ludusavi/log_buffer.py
    py_modules/sdh_ludusavi/registry.py
    py_modules/sdh_ludusavi/updater.py
    py_modules/sdh_ludusavi/syncthing/config.py
    main.py
    scripts/analyze_plugin_logs.py
    src/surfaces/autoSyncStatusSurface.tsx
    src/controllers/syncthingMonitor.ts
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

The per-file loop asserts the rollback actually changed all eight paths; an
unchanged file would mean the run was measuring your own implementation. The
`trap` guarantees restoration even if the block exits early.

Record the added test names that failed. This aggregate gate proves only that at
least one reverted Python behaviour and at least one reverted frontend behaviour
are detected. Per-file load-bearing coverage comes from the individual task
mutation gates. T6 is deliberately outside that claim, because it characterizes
behaviour that already existed.

### V4 — Inspect an independently produced post-change runtime log

The point of this plan is human readability, which no unit test measures. Note
that V1's commands build and test the plugin but never launch it, so they do
**not** produce a Decky runtime log. Inspect only a log you can establish was
written by a post-change plugin run.

If such a log exists, report:

- the count of lines labelled `backend:` versus `frontend:`;
- the count of `Coercing status for` lines, which must be 0;
- one verbatim backend-origin example and one verbatim frontend-origin example.

Record how you established the log's post-change provenance. If no post-change
runtime log exists on this machine, mark V4 deferred and say so plainly. Do not
substitute an older log, and do not fabricate excerpts.

### V5 — Session log

Create `docs/agent_conversations/<implementation-date>_log-hygiene.json` per the
repo protocol. Record: date, objective, files modified, tests added per task, the
V1-V4 output, confirmation that `tests/test_main_rpc.py:257` remained a
pre-construction assertion, your decision on T4's exactly-once vs best-effort
wording, and every point where the source disagreed with this plan.

Stage that exact path and commit it:

```text
docs(session): record log-hygiene implementation
```

Require `git status --short` to be clean afterward.

### Deferred and not verified

State these explicitly in the session log:

- **No on-device verification.** Nothing here is tested on a Steam Deck.
- **Historical logs stay ambiguous.** In any log written before T5, a `frontend:`
  line may be a real frontend message or an unlabelled backend one. The analyzer
  was *already* tolerant of both prefixes; T6 documents that limitation and adds
  regression coverage, but cannot make old logs unambiguous.
- **V4 is a judgement, not an assertion.** It reports counts and examples for a
  human to read. It does not prove readability improved.
- **Log levels are the only thing T7 changes.** No update-path behaviour is
  altered, and the revalidate, install, and handoff lines keep their levels.
- **T7 reduces default-level visibility of successful update checks.** Once the
  prose is at DEBUG, a successful check is narrated only by the frontend's
  trace-id stream. This was chosen deliberately, but it is an observability
  trade-off, not a pure duplicate removal: if the frontend is not running or its
  logging is off, a successful backend check leaves no INFO-level trace.
- **F1 and F3 from the source review remain retracted** and are not implemented
  here.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished log-hygiene
```

This writes:

```text
/tmp/sdh_ludusavi/log-hygiene_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer log-hygiene`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/log-hygiene-review-*.md
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
   scripts/orchestration/clear-finished log-hygiene
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
   git add docs/review/log-hygiene-review-*.md
   git commit -m "docs(review): record log-hygiene review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished log-hygiene
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer log-hygiene` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed log-hygiene
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize log-hygiene
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/log-hygiene_finalized
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
scripts/orchestration/finalize log-hygiene
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/log-hygiene_finished
/tmp/sdh_ludusavi/log-hygiene_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
