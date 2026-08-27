# Plan: Quiet redundant update-check suppression (update-check-suppression)

## Context

Installing a plugin update makes the frontend attempt an automatic update check
five times in about 70 milliseconds. Every attempt is refused by a guard, every
refusal is written to the log at INFO, and two of the effects that trigger the
attempts also re-issue a `get_update_check_context` RPC on the way. Observed on
`steamdeck-legos` while updating `0.4.6` to `0.4.7-dev.g5490a99`, in
`/home/deck/homebrew/logs/SDH-Ludusavi/2026-08-19 23.26.15.log`:

```text
[2026-08-26 12:56:54,656][INFO]: update: automatic_check_suppressed_pending_install: trace_id=none
[2026-08-26 12:56:54,690][INFO]: update: automatic_check_suppressed_pending_install: trace_id=none
[2026-08-26 12:56:54,722][INFO]: update: automatic_check_suppressed_pending_install: trace_id=none
[2026-08-26 12:56:54,723][INFO]: update: automatic_check_suppressed_pending_install: trace_id=none
[2026-08-26 12:56:54,738][INFO]: update: automatic_check_suppressed_pending_install: trace_id=none
```

There are two independent defects, and fixing only the first would hide the second
rather than fix it.

**The event is logged at the wrong level.** `logUpdate`
(`src/controllers/pluginUpdateController.tsx:24-33`) hardcodes `log("info", ...)`
for every stage it is given, so the suppressed-check no-op at line 102 is INFO
like `check_success` and `install_clicked`. Nothing happened; nothing should be
narrated at the default level.

**The attempts should not be happening.** `checkForUpdates` is a `useCallback`
whose dependency array (line 195) includes `state.installedOverride` and
`state.pendingInstallVersion`. `INSTALL_SUCCESS` sets both, so the callback's
identity changes. Two effects list `checkForUpdates` as a dependency and therefore
re-run whenever it does:

- the hydration effect (`useEffect` at line 248, deps at line 310), which calls
  `getUpdateCheckContextCall()` before reaching its own guarded
  `checkForUpdates({source:"automatic"})` at line 294;
- the automatic-checks effect (`useEffect` at line 343, deps at line 355), which
  calls `checkForUpdates({source:"automatic"})` at line 354.

Each re-run reaches the guard at line 101 — `opts.source === "automatic" &&
(state.installedOverride || state.pendingInstallVersion)` — and returns after
logging. The five log lines correspond to the install's successive state
transitions, each changing the callback identity and re-running both effects.

Measured with a throwaway probe built on the React mock already in
`src/controllers/pluginUpdateController.test.tsx`. One settling round after
`INSTALL_SUCCESS`:

```text
suppression_before_install: 0
suppression_after_install:  1
suppression_log_levels:     ["info"]
effect_indexes_rerun:       [0, 2, 4]      // 2 = hydration, 4 = automatic-checks
update_context_rpcs:        1 -> 2
```

The file already carries the tool for the fix. `checkForUpdatesRef` is declared at
lines 196-197 and reassigned on every render, and the mount effect at line 312
already calls `checkForUpdatesRef.current(...)` at lines 328 and 335, precisely so
that its dependency array (line 341) can omit the callback. The two remaining effects
predate that pattern.

Zero re-runs is not the target. `onInstallVersionConfirmed` is
`confirmInstalledPluginVersion` (`src/components/qam/LudusaviContent.tsx:362-370`),
a `useCallback` over the stable `ludusaviStore`, and it writes the new version into
the store — so `currentVersion` changes once per install and the hydration effect
re-runs once for a real reason. The target is one re-run per genuine input change
instead of one per state transition.

Files in scope:

```text
src/controllers/pluginUpdateController.tsx
src/controllers/pluginUpdateController.test.tsx
docs/agent_conversations/<implementation-date>_update-check-suppression.json
```

Run every frontend command through the project wrapper: `./run.sh pnpm ...`, not
bare `pnpm`. `scripts/quality_gates.sh` uses the wrapper and the repo contract
requires it.

Decisions already made — implement these, do not revisit:

- **Only `automatic_check_suppressed_pending_install` is demoted.** `logUpdate`
  gains an optional level that defaults to `"info"`, and exactly one call site
  passes `"debug"`. `check_reuse` is also arguably a no-op; it is deliberately
  left at INFO in this plan. Do not demote any other stage.
- **The guard itself does not change.** Suppressing an automatic check while an
  install is pending is correct. This plan reduces how often the guard is reached
  and how loudly it reports, not what it decides.
- **The fix for the churn is `checkForUpdatesRef`,** the pattern already in the
  file, not a `useMemo`, not a reducer restructure, and not removing
  `state.installedOverride` / `state.pendingInstallVersion` from the
  `checkForUpdates` dependency array. The callback reads that state and its deps
  are correct; the effects' deps are the defect.
- **`hasChecked`, `skipInitialCheck`, and `automaticCheckToggleHydrated` keep their
  current semantics.** No effect gains or loses a guard.

One existing test constrains this work and must keep passing unchanged:

```text
src/controllers/pluginUpdateController.test.tsx:240
"dependency arrays for re-check effects do not change on check result"
```

It asserts that a `CHECK_SUCCESS_AVAILABLE` dispatch leaves every effect's
dependency array identical. This plan extends the same guarantee to the install
transitions; it must not weaken the existing one. That test indexes
`activeEffects` positionally, so **do not add, remove, or reorder any `useEffect`
in this file** — only edit the dependency arrays and call expressions of the two
named effects.

**Slug used throughout this plan:** `update-check-suppression`

---

## Orchestration Contract

**Slug:** `update-check-suppression`

**Plan file:**

```text
docs/plans/2026-08-26_update-check-suppression.md
```

**Implementation branch:**

```text
feat/update-check-suppression
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/update-check-suppression_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/update-check-suppression_finalized
```

**Review notes:**

```text
docs/review/update-check-suppression-review-*.md
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
git checkout -b feat/update-check-suppression
```

Commit this plan first:

```bash
git add docs/plans/2026-08-26_update-check-suppression.md
git commit -m "docs(plan): add update-check-suppression implementation plan"
```

---

## Implementation Tasks

Three tasks. T1 and T2 are each one coherent change and one commit, and each has a
mutation gate that must pass before its commit. T3 is the session log.

Order for behavior-changing tasks is: RED, GREEN, gate, commit. **Run each task's
gate before its commit** — the gate reverts the implementation file with
`git stash push`, which needs it to remain uncommitted.

T1 before T2. T1 makes the suppression event observable at a level the tests can
distinguish; T2's test then asserts the event stops being emitted at all.

### Test harness

Both tasks add cases to `src/controllers/pluginUpdateController.test.tsx`, which
already mocks `react` with a hand-rolled hook implementation, plus `@decky/api`,
`../api/ludusaviRpc`, and `../utils/deckyInstaller`. It does **not** yet mock
`../utils/logging`.

T1 needs it mocked to observe log levels. Add:

```ts
vi.mock("../utils/logging", () => ({ log: vi.fn() }));
```

The controller imports `{ log, type LogFields }`; the type import is erased at
compile time, so a mock exporting only `log` is sufficient. This mock is shared by
every test in the file — after adding it, run the whole file and confirm the
existing cases still pass before writing anything new.

### The mutation gate

This repository has had unrelated stashes in the past, so the gate must never pop
a stash it did not create. It also captures the mutation run's exit status
explicitly: `cmd; echo "exit=$?"` reports `echo`'s status, not the command's.

Use this pattern verbatim, changing only `task_label`:

```bash
(
  set -u
  task_label="T1"
  implementation_file="src/controllers/pluginUpdateController.tsx"
  test_command=(./run.sh pnpm run test:unit)

  "${test_command[@]}" || exit 1

  before_stash="$(git rev-parse -q --verify refs/stash || true)"
  git stash push -m "update-check-suppression-${task_label}-mutation" -- \
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

Both tasks are about things that should stop happening. A test that renders the
hook and asserts a log line is absent passes trivially when the hook was never
driven into the state that produces it.

Every test here must assert an **absence together with a presence**: no
suppression event *and* the install actually completed; unchanged dependency
arrays *and* a dispatch that genuinely changed the reducer state. Prove the
fixture reached the state before asserting what it did not do.

### Baseline

Capture before starting T1:

```bash
(
  set -euo pipefail
  ./run.sh pnpm run test:unit 2>&1 | tail -5 | tee /tmp/sdh_ludusavi/ucs-baseline-vitest.txt
  ./run.sh uv run pytest -q 2>&1 | tail -3 | tee /tmp/sdh_ludusavi/ucs-baseline-pytest.txt
)
```

Record both counts in the session log. The pytest baseline exists only to show
this plan left the Python suite untouched.

---

### T1 — The suppressed-check no-op logs at debug

**File:** `src/controllers/pluginUpdateController.tsx`

**Change:** give `logUpdate` (lines 24-33) a fourth parameter, a log level
defaulting to `"info"`, and pass it through to `log(...)` in place of the
hardcoded `"info"`. Then pass `"debug"` at the single call site on line 102:

```text
logUpdate(null, "automatic_check_suppressed_pending_install");
```

Every other `logUpdate` call site keeps its current behaviour by omitting the new
argument. Do not change any other stage's level, and do not change the message
format.

**RED:** add a test that drives the hook through a completed install and then
asserts both halves:

- `log` was called for `automatic_check_suppressed_pending_install` with level
  `"debug"` — assert on the level argument, not merely that the call happened;
- `log` was called for at least one other stage with level `"info"`, proving the
  default survived.

The second assertion is what stops a change that demotes every stage.

```bash
./run.sh pnpm run test:unit
```

Record the failure output. It must show `"info"` received where `"debug"` was
expected for the suppression stage. A failure showing zero matching calls means
the fixture never reached the suppressed state — fix the fixture, not the
assertion.

**GREEN:** make the change. Re-run and record the tallies.

**Gate:** the mutation gate with `task_label="T1"`.

**Commit:**

```text
refactor(updater): demote the suppressed update-check no-op to debug
```

---

### T2 — The install stops re-running the two checkForUpdates effects

**File:** `src/controllers/pluginUpdateController.tsx`

**Change:** in both of these effects, call `checkForUpdatesRef.current(...)`
instead of `checkForUpdates(...)`, and remove `checkForUpdates` from the
dependency array:

- the hydration effect — call site line 294, dependency array line 310;
- the automatic-checks effect — call site line 354, dependency array line 355.

Leave every other entry in both dependency arrays in place. `checkForUpdatesRef`
is declared at lines 196-197 and reassigned during render, so it holds the current
callback by the time either effect body runs; the mount effect at line 312
already relies on exactly this.

Change nothing else. Do not touch the `checkForUpdates` `useCallback` or its
dependency array at line 195, the `install` callback's dependency array at line
471, or the guard at line 101. Do not add, remove, or reorder any `useEffect` —
the existing test at line 240 and the new one both index `activeEffects`
positionally.

**RED:** add a test modelled on the existing
`"dependency arrays for re-check effects do not change on check result"` at line
240, but dispatching an install instead of a check result. It must:

1. render, dispatch `HYDRATION_COMPLETE`, re-render, and capture every effect's
   dependency array;
2. assert `activeEffects.length === 5` at that point, so a future added effect
   fails this test loudly instead of silently shifting the indexes below;
3. dispatch `{ type: "INSTALL_SUCCESS", version, channel, preInstallVersion }`
   through the reducer setter, as the existing test dispatches its action;
4. re-render and capture the dependency arrays again;
5. assert that the hydration effect's and the automatic-checks effect's dependency
   arrays are **identical, element by element**, to what they were before;
6. assert that the reducer state actually changed — read the controller's
   `isInstalling` / `effectiveCurrentVersion` or the captured state and show
   `installedOverride` or `pendingInstallVersion` is now set. Without this the
   test passes against a dispatch that did nothing;
7. assert that no `automatic_check_suppressed_pending_install` call reached `log`
   during step 4.

Identify the two effects by the positional indexes the existing test already
uses. The file declares exactly five `useEffect` calls, at lines 230, 242, 248,
312, and 343, so the hydration effect is index 2 and the automatic-checks effect
is index 4. Say so in a comment. Confirm those five line numbers against the
source before relying on the indexes. Note that index 0, the clear-installed-override effect,
**is** expected to get new deps: `INSTALL_SUCCESS` sets `state.installedOverride`,
which that effect legitimately watches. Do not assert it is unchanged.

```bash
./run.sh pnpm run test:unit
```

Record the failure output. It must name the hydration or automatic-checks effect's
dependency comparison. If it fails on step 6 instead, the dispatch shape is wrong.

**GREEN:** make the change. Re-run the whole file and record the tallies. The test
at line 240 must still pass; if it does not, an effect was added or reordered.

**Gate:** the mutation gate with `task_label="T2"`.

**Commit:**

```text
fix(updater): stop re-running update-check effects on install state changes
```

---

### T3 — Session log

Covered by V4. It is listed here so the task count matches the commit count.

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
below run once, after T2.

### V1 — Full suite

```bash
scripts/orchestration/run-quality-gates
```

Record the actual vitest and pytest tallies and the exit code. Compare vitest
against `/tmp/sdh_ludusavi/ucs-baseline-vitest.txt`: it must grow by exactly the
number of cases T1 and T2 added. Compare pytest against
`/tmp/sdh_ludusavi/ucs-baseline-pytest.txt`: it must be **unchanged**. This plan
touches no Python; a changed pytest count means something outside its scope moved.

If a baseline file is missing, stop and report V1 as failed rather than
reconstructing it: after T2 the implementation and tests are both committed, so no
honest baseline can be recovered.

The quality gate runs mutating `ruff check --fix` and `ruff format` commands, so
require `git status --short` to be clean afterward. If it shows changes to files
this session owns, inspect them, commit the corrections, rerun V1, and require a
clean tree before V2.

### V2 — The pre-existing dependency guarantee still holds

```bash
./run.sh pnpm exec vitest run src/controllers/pluginUpdateController.test.tsx
```

Record the tallies and the names of every test that ran. The output must include
both:

- `dependency arrays for re-check effects do not change on check result` — the
  guarantee that existed before this plan, for `CHECK_SUCCESS_AVAILABLE`;
- the T2 test — the same guarantee extended to `INSTALL_SUCCESS`.

If the first is absent from the output, it was renamed or removed; that is out of
scope for this plan. Stop and report it.

### V3 — Negative control: the reverted controller is detected

Run after V1 and V2, from a clean working tree.

```bash
(
  set -u
  base_sha="$(git merge-base HEAD dev)" || exit 1
  file="src/controllers/pluginUpdateController.tsx"

  restore_v3() { git checkout HEAD -- "$file"; }
  trap restore_v3 EXIT

  git checkout "$base_sha" -- "$file" || exit 1

  if git diff --cached --quiet HEAD -- "$file"; then
    printf 'rollback did not change %s\n' "$file" >&2
    exit 1
  fi
  git status --short

  frontend_exit=0
  ./run.sh pnpm run test:unit || frontend_exit=$?
  printf 'frontend_exit=%s\n' "$frontend_exit"

  restore_v3 || exit 1
  trap - EXIT

  restored="$(git status --short)"
  if [[ -n "$restored" ]]; then
    printf '%s\n' "$restored" >&2
    echo "working tree not clean after V3 restoration" >&2
    exit 1
  fi

  if (( frontend_exit == 0 )); then
    echo "reverted suite unexpectedly passed" >&2
    exit 1
  fi
)
```

The `git diff --cached` check asserts the rollback actually changed the file; an
unchanged file would mean the run was measuring your own implementation. The
`trap` guarantees restoration even if the block exits early.

Record the names of the tests that failed. **Both** the T1 test and the T2 test
must appear. If only one does, the other is not load-bearing — report which, and
do not describe V3 as passed.

### V4 — Session log

Create `docs/agent_conversations/<implementation-date>_update-check-suppression.json`
per the repo protocol. Record: date, objective, files modified, tests added per
task, the V1-V3 output, the V5 deferrals below, whether adding the
`../utils/logging` mock disturbed any pre-existing test in the file, and every
point where the source disagreed with this plan.

Stage that exact path and commit it:

```text
docs(session): record update-check-suppression implementation
```

Require `git status --short` to be clean afterward.

### Deferred and not verified

State these explicitly in the session log:

- **No on-device verification.** V1-V3 build and test the plugin but never launch
  it, so they produce no Decky runtime log. Record this recipe for the user to run
  after a dev release: install the build, enable debug logging, install a further
  update from the QAM, and confirm the newest log in
  `/home/deck/homebrew/logs/SDH-Ludusavi/` contains **zero** INFO-level
  `automatic_check_suppressed_pending_install` lines, and at most one DEBUG-level
  line for the whole install. Do not substitute an older log and do not describe
  the deferred check as done.
- **The RPC reduction is inferred, not measured here.** The tests assert that the
  two effects stop re-running. Nothing in V1-V3 counts
  `get_update_check_context` calls reaching the backend across a real install; the
  probe recorded in the Context section measured one settling round in a mocked
  harness, not a device.
- **The React mock is not React.** Every assertion in this plan runs against the
  hand-rolled `useState`/`useEffect`/`useCallback` mock at the top of
  `pluginUpdateController.test.tsx`. It models dependency-array identity, which is
  what these tests assert, but it does not model batching, StrictMode double
  invocation, or effect cleanup ordering. A behaviour that depends on those is
  unproven either way.
- **`check_reuse` stays at INFO.** It is arguably as much of a no-op as the
  suppression event. Leaving it is a deliberate scope decision, not an oversight.
- **The guard's decision is unchanged.** This plan does not verify that
  suppressing automatic checks during a pending install is the right policy; it
  assumes it and reduces how often that policy is consulted.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished update-check-suppression
```

This writes:

```text
/tmp/sdh_ludusavi/update-check-suppression_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer update-check-suppression`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/update-check-suppression-review-*.md
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
   scripts/orchestration/clear-finished update-check-suppression
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
   git add docs/review/update-check-suppression-review-*.md
   git commit -m "docs(review): record update-check-suppression review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished update-check-suppression
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer update-check-suppression` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed update-check-suppression
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize update-check-suppression
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/update-check-suppression_finalized
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
scripts/orchestration/finalize update-check-suppression
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/update-check-suppression_finished
/tmp/sdh_ludusavi/update-check-suppression_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
