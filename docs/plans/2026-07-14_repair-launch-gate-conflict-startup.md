# Plan: Repair Launch-Gate Conflict Handling at Game Startup (repair-launch-gate-conflict-startup)

## Context

### Problem Definition

The development build `0.3.7-dev.gd71ba75` regressed pre-game conflict handling for a
tracked Proton/non-Steam game. The local save and backup legitimately differed, so the
expected behavior was to hold the game at launch and display the existing conflict modal.
Instead, the launch gate failed, the modal was deliberately skipped, and the frontend sent
this failure toast while the game continued loading:

```text
Launch gate unavailable; conflict resolution skipped while game is loading.
```

Fresh device evidence in `/tmp/sdh_ludusavi/steamdeck/logs/2026-07-14-conflict-toast`
identified two independent backend failures:

1. At `16:22:47.766`, Steam notified the frontend that PID `3973` had started. At
   `16:22:47.767`, `SystemdScopeController.discover()` rejected the PID because it was not
   yet in an exact Steam app scope. The user journal then reported
   `Started app-steam-app3156562597-3973.scope` later in the same second. The same immediate
   discovery race occurred for PIDs `6446` and `7813`.
2. A separate launch for PID `7051` reached the correct scope, but `systemctl --user freeze`
   inherited Decky/PyInstaller's `LD_LIBRARY_PATH` and loaded
   `/tmp/_MEI.../libcrypto.so.3`. The executable failed because SteamOS systemd required a
   newer OpenSSL symbol version.

The frontend behavior is downstream and currently correct. In
`src/controllers/gameLifecycleDecision.ts`, a conflict with `state.paused=false` is not
resolved while the game is advancing; it produces the observed failure toast. Do not hide
that toast or open the modal without a verified gate. Repair the backend so the normal
Steam startup ordering produces a verified frozen scope before the conflict decision.

The older `0.3.6` log is the control: it stopped PID `12992`, detected the same expected
conflict, displayed the modal, restored the selected backup, and resumed only afterward.
That PID-tree implementation was still unsafe because later Proton children escaped it, so
do not restore PID-tree success semantics.

### Intended Outcome

- A Steam lifetime PID received just before its exact `app-steam-appNNN-NNN.scope` exists is
  held during a short, bounded handoff window.
- The launch gate returns `status=paused` only after that exact Steam app scope is frozen and
  both cgroup v2 freezer state files confirm the transition.
- Once scope freeze is verified, every current or later process joining the scope remains
  blocked while save inspection, Syncthing settlement, and conflict resolution run.
- `systemctl` uses the Deck user's systemd bus without inheriting Decky/PyInstaller's private
  library path.
- A legitimate conflict opens the existing modal and performs the selected restore/keep/
  dismiss behavior before exactly one scope thaw.
- Genuine discovery, transition, or verification failures continue to fail closed, resume
  any temporary bootstrap stop, avoid changing saves, and retain the failure toast.
- The reusable log analyzer treats scope-discovery, scope-freeze, and conflict-skipped gate
  messages as actionable findings so the on-device acceptance gate cannot miss this class of
  regression again.

### Architecture Overview

Keep strict scope parsing and systemd transitions in
`py_modules/sdh_ludusavi/launch_gate.py`. Add a small acquisition layer in a new
`py_modules/sdh_ludusavi/launch_gate_acquire.py` rather than growing the existing
near-budget module. The acquisition layer must bridge the ordering gap safely:

1. Validate the launch PID, capture its owner/start-time identity, and send `SIGSTOP` only to
   that bootstrap PID through an injectable signal function.
2. Poll the same PID's unified cgroup membership to a short monotonic deadline. Retry only a
   typed "scope not ready" state caused by the PID not yet being in its exact Steam app
   scope. Wrong ownership, PID replacement, malformed cgroup data, path escape, or invalid
   scope state fail immediately.
3. When strict discovery returns an exact scope, invoke the existing bounded
   `systemctl --user freeze <exact-unit>` transition and verify `cgroup.freeze=1` and
   `cgroup.events` reporting `frozen 1`.
4. Send `SIGCONT` to the unchanged bootstrap PID only after scope freeze is verified. Because
   the PID is then inside the frozen cgroup, releasing its temporary process stop must not
   permit execution. Recheck the scope's frozen state after the handoff.
5. Return the discovered scope to `ProcessWatchdog`, which creates the existing renewable
   scope lease. No PID-only stop may ever produce `status=paused`.
6. On every timeout, discovery error, signal error, freeze error, cancellation, or unexpected
   exception, unwind the temporary stop if the original PID identity still exists. If scope
   freeze partially succeeded, preserve the current best-effort thaw behavior before failing.
   Never signal a replacement PID.

This bounded bootstrap stop is not a fallback gate. It exists only to prevent execution
during Steam's observed pre-scope window; successful public pause semantics still require a
verified complete-scope freeze. Do not scan arbitrary processes, infer a unit from an app ID,
freeze a parent slice, trust a caller-provided unit, or weaken the exact cgroup validation.

`SystemdScopeController._run_unit_command()` must build a subprocess environment that retains
the explicit/inherited user-bus values but clears `LD_LIBRARY_PATH` when Decky supplied it,
matching the established Ludusavi subprocess boundary in
`py_modules/sdh_ludusavi/ludusavi.py`. Do not mutate global `os.environ`.

### Core Data Structures

- Keep `SteamAppScope` as the durable exact unit/path/device/inode/root-PID identity.
- Add a frozen `LaunchProcessIdentity` containing the validated PID, owner UID, and proc start
  ticks used to detect exit or reuse across stop, discovery retries, and resume cleanup.
- Add a distinct `ScopeNotReadyError` (or equivalently explicit typed result) so bounded
  acquisition retries only the observed pre-scope state and not security/validation errors.
- Add `ScopeAcquisitionResult` with `success`, optional verified `scope`, and bounded `reason`
  fields. A successful result must imply that temporary PID stop cleanup completed and the
  returned scope remains verified frozen.
- Add `LaunchScopeAcquirer`, with injected strict scope controller, signal sender, proc root,
  monotonic clock, and wait function. It owns only bootstrap stop -> bounded discovery ->
  verified freeze -> bootstrap release.
- Keep `_PauseLease` in `watchdog.py` scope-based. It continues to own `SteamAppScope`, the
  original absolute-ceiling timestamp, opaque lease ID, and renewal deadline.

### Public Interfaces

Preserve all Decky RPC names, arguments, and response shapes:

```text
pause_game_process(pid) -> {status, pid, lease_id, lease_ttl_seconds}
renew_game_process_pause(pid, lease_id) -> {status, pid, lease_ttl_seconds}
resume_game_process(pid, lease_id?) -> {status, pid, ...}
```

Do not add app ID or scope-name parameters to the frontend API. The backend must continue to
derive the authoritative scope from the PID's own cgroup membership. Preserve
`createPauseLease`, lease renewal, `evaluateStartCheck`, and the conflict-modal API. Frontend
production code should change only if a failing regression test proves an integration defect;
the expected fix is backend-only plus analyzer/docs coverage.

### Dependency Requirements

Add no Python, JavaScript, system package, privilege helper, or upstream dependency. Use only
the current Python standard library and existing systemd/cgroup v2 runtime support. Tests
must inject signals, clocks, waits, proc/cgroup roots, and command runners; automated tests
must never stop real processes or invoke real `systemctl`.

### Testing Strategy

Follow strict Red-Green-Refactor. First add deterministic unit regressions for the delayed
scope appearance, temporary signal ordering/cleanup, PID identity changes, contaminated
systemctl environment, lease creation boundary, and log-analyzer findings. Confirm those new
cases fail for the current production behavior before implementing the acquisition layer.
Then make the focused backend suites green, preserve the existing frontend fail-closed and
conflict-modal tests, run the complete orchestration quality gate, and validate a local Decky
ZIP. Keep actual process signals, systemd transitions, and device logs out of automated tests.
Treat the final SteamOS conflict launch as deferred acceptance requiring separate installation
authorization after orchestrator approval.

### Scope Boundaries

- Do not change the conflict-recency decision. The differing local and backup saves in the
  field logs are expected input, not an error to suppress.
- Do not remove or soften the genuine gate-failure toast.
- Do not return to process-tree `SIGSTOP`/`SIGCONT` as a successful launch gate.
- Do not commit raw Deck/Steam logs or generated artifacts.
- The six `Task was destroyed but it is pending!` messages occurred during Decky plugin
  reload and are a separate WSRouter/unload investigation. Do not modify unload behavior in
  this plan unless a focused launch-gate cleanup test proves direct causality.
- `docs/plans/2026-07-14_thermo-review-quick-fixes.md` is reserved for future work and is not
  present at plan-authoring time. If it appears, treat it as unrelated user-owned work: do not
  stage, edit, delete, or absorb it into this branch.

**Slug used throughout this plan:** `repair-launch-gate-conflict-startup`

---

## Orchestration Contract

**Slug:** `repair-launch-gate-conflict-startup`

**Plan file:**

```text
docs/plans/2026-07-14_repair-launch-gate-conflict-startup.md
```

**Implementation branch:**

```text
feat/repair-launch-gate-conflict-startup
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/repair-launch-gate-conflict-startup_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/repair-launch-gate-conflict-startup_finalized
```

**Review notes:**

```text
docs/review/repair-launch-gate-conflict-startup-review-*.md
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
git checkout -b feat/repair-launch-gate-conflict-startup
```

Commit this plan first:

```bash
git add docs/plans/2026-07-14_repair-launch-gate-conflict-startup.md
git commit -m "docs(plan): add repair-launch-gate-conflict-startup implementation plan"
```

---

## Implementation Tasks

### 1. Establish RED regression coverage before production changes

Start by confirming `git status --short` contains only this plan. Preserve any unrelated user
work according to Scope Boundaries. Commit this plan as instructed by Setup before writing
behavior-changing code.

Add the following failing tests first:

- In `tests/test_launch_gate_scope.py`, reproduce a PID whose initial unified cgroup entry is
  the user `app.slice`, then change the synthetic entry to an exact
  `app-steam-app3156562597-3973.scope` from the injected wait callback. Assert the bootstrap
  PID receives `SIGSTOP` before discovery polling, the exact scope reaches verified frozen
  state, `SIGCONT` occurs only afterward, and the scope remains frozen after handoff.
- Cover the immediate-exact-scope path with the same ordering invariant; do not leave a
  process-execution window around `systemctl freeze`.
- Cover discovery timeout, wrong owner, malformed unified cgroup data, PID exit/reuse,
  signal failure, freeze command failure, freezer verification failure, and post-handoff
  verification failure. Every failure must return a bounded reason, create no lease, thaw any
  partial scope as applicable, and resume the original bootstrap PID at most once when its
  identity still matches.
- Prove non-ready cgroup membership is retryable while ownership, identity, traversal, unit
  grammar, and freezer-state violations are not.
- Inject `LD_LIBRARY_PATH=/tmp/_MEI-test` into the systemctl command environment and assert
  the child receives a cleared value while the caller environment is unchanged. Preserve
  supplied `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS`, and retain current defaults when
  they are absent.
- In `tests/test_watchdog.py`, make the fake acquisition boundary return success/failure and
  prove `ProcessWatchdog.pause()` records a renewable lease only for a verified frozen scope.
  Preserve same-scope lease rotation, absolute-ceiling origin, thaw retry, and shutdown
  invariants.
- In `tests/test_service.py`, `tests/test_main.py`, and/or `tests/test_compatibility.py`, add
  only the minimal regression assertions needed to prove the public pause/renew/resume RPC
  contract remains unchanged.
- In `tests/test_analyze_plugin_logs.py`, add sanitized log fixtures for immediate discovery
  failure, contaminated-environment freeze failure, the conflict-skipped toast, and a later
  successful scope acquisition. Require stable targeted findings for the failures and no
  finding for the successful handoff.

Use deterministic fakes and temporary filesystem trees. Run RED and record the failure reason
for each new behavior in the session record:

```bash
./run.sh uv run pytest --no-cov tests/test_launch_gate_scope.py tests/test_watchdog.py tests/test_service.py tests/test_main.py tests/test_compatibility.py
./run.sh uv run pytest --no-cov tests/test_analyze_plugin_logs.py
```

The new delayed-scope, bootstrap ordering, environment cleanup, and analyzer cases must fail
against the current implementation. Do not weaken existing exact-scope, symlink, identity,
lease, cleanup, or frontend fail-closed tests.

### 2. Add bounded bootstrap-to-scope acquisition

Create `py_modules/sdh_ludusavi/launch_gate_acquire.py` and implement the acquisition types
and boundary described in Architecture Overview.

Requirements:

1. Capture PID ownership and `/proc/NNN/stat` start ticks before sending a signal. Use the
   existing safe PID range. Parse the stat line without being confused by spaces or
   parentheses in the process name.
2. Send only `SIGSTOP` and `SIGCONT` to the exact validated PID through an injected callable.
   Do not walk a process tree and do not signal a process after its identity changes.
3. Use named short timeout/poll constants and injected monotonic/wait functions. Keep the
   total bootstrap acquisition bounded independently from the existing systemctl and freezer
   transition timeouts.
4. Retry only `ScopeNotReadyError`. Preserve strict rejection of malformed or non-unified
   cgroups, wrong ownership, unexpected hierarchy depth, invalid unit names, symlink escapes,
   missing state files after an exact scope appears, and changed proc/scope identity.
5. Freeze and verify the exact scope before releasing the temporary stop. After release,
   verify the scope remains frozen before returning `ScopeAcquisitionResult(success=True)`.
6. Centralize cleanup so every return/exception path has deterministic stop release and
   partial-scope thaw behavior. Log bounded reasons without raw cgroup paths, command
   environments, D-Bus addresses, or unbounded stderr.

Keep the new module focused and add a reasonable first-party size budget in
`tests/test_module_size_budgets.py`. Do not expand `launch_gate.py` or `watchdog.py` past their
current budgets as a shortcut.

Make the focused acquisition tests GREEN:

```bash
./run.sh uv run pytest --no-cov tests/test_launch_gate_scope.py tests/test_module_size_budgets.py
```

### 3. Sanitize systemctl execution without weakening scope validation

Update `SystemdScopeController` in `py_modules/sdh_ludusavi/launch_gate.py`:

- classify only the safe, observed pre-scope membership as `ScopeNotReadyError` for the
  acquisition layer;
- keep `discover(pid)` strict and single-attempt for callers/tests that need strict behavior;
- clear a present `LD_LIBRARY_PATH` in the copied child environment before invoking
  `systemctl`, following `get_ludusavi_environment()` semantics;
- keep `shell=False`, the exact bounded argv, command timeout, explicit user-bus defaults,
  bounded stderr, freezer-state verification, and best-effort thaw behavior unchanged; and
- never modify process-global environment variables.

Make all strict discovery, transition, and environment tests GREEN:

```bash
./run.sh uv run pytest --no-cov tests/test_launch_gate_scope.py tests/test_ludusavi.py
```

### 4. Integrate acquisition with renewable watchdog leases

Refactor `py_modules/sdh_ludusavi/watchdog.py` so `pause(pid)` delegates initial acquisition
to an injectable `LaunchScopeAcquirer`-compatible boundary rather than immediately calling
strict `discover()` and `freeze()`.

- Create `_PauseLease` only from a successful result containing a verified frozen scope.
- Preserve same-scope lease rotation without a thaw window and without resetting the original
  absolute-ceiling timestamp.
- Preserve renewal and resume against the stored device/inode scope identity; they must not
  depend on the bootstrap PID continuing to exist.
- Preserve retryable thaw leases, watchdog expiry, absolute-ceiling recovery, and bounded
  shutdown thaw retries.
- A failed acquisition must return the compatible `{status: "failed", pid, message}` result,
  log one actionable bounded warning, and leave no watchdog lease/thread behind.
- Do not change frontend RPC types or add a PID-only success fallback.

Run:

```bash
./run.sh uv run pytest --no-cov tests/test_watchdog.py tests/test_service.py tests/test_main.py tests/test_compatibility.py tests/test_module_size_budgets.py
./run.sh pnpm exec vitest run src/controllers/gameLifecycleDecision.test.ts src/controllers/gameLifecycleController.test.ts src/controllers/launchGateLease.test.ts
```

The frontend tests must continue to prove both sides of the contract: verified pause permits
the conflict modal/selected operation, while genuine pause failure skips save mutation and
shows the failure notification.

### 5. Make log analysis catch launch-gate acquisition failures

Update `scripts/analyze_plugin_logs.py` and `tests/test_analyze_plugin_logs.py` with bounded,
stable rules for:

- failure to acquire/discover an exact Steam app scope;
- failure to freeze or verify an acquired scope, including systemctl failures; and
- conflict handling skipped because the launch gate was unavailable.

Correlate or deduplicate the warning and toast within one launch incident where practical so
one root failure does not produce misleading noise, but do not suppress distinct launches.
Keep all existing lease-expiry, resume-before-resolution, backend-match, diagnostic, and
payload-safety findings compatible. `--strict` must return failure for the sanitized
regression fixtures and success for a verified freeze -> conflict resolution -> thaw fixture.

Run:

```bash
./run.sh uv run pytest --no-cov tests/test_analyze_plugin_logs.py
```

### 6. Update active technical documentation and session evidence

Update only the active launch-gate documentation needed to describe the corrected runtime:

- `DEVELOPMENT.md`: document the transient bootstrap stop, bounded scope acquisition,
  sanitized systemctl environment, verified handoff, and failure diagnostics.
- `docs/specs/custom_status_bar_ui.md`: clarify that an expected conflict is shown only after
  verified scope acquisition and that the failure toast remains for genuine gate failure.
- `docs/plans/cloud_sync_conflict_resolution_flow.html` and
  `tests/test_status_flow_diagram.py`: show bootstrap hold -> exact scope creation -> verified
  scope freeze -> conflict decision -> thaw, without presenting PID stop as the final gate.
- `docs/agent_conversations/2026-07-14_repair-launch-gate-conflict-startup.json`: record the
  objective, field evidence, files changed, RED tests, design decisions, commands/results,
  remaining limitations, and deferred device verification.

Do not rewrite the historical
`docs/plans/2026-07-14_freeze-steam-app-scope-during-launch-gate.md`; this plan is its durable
field-correction record. The README Launch Gate description remains accurate and needs no
change unless implementation alters user-facing behavior beyond this plan.

Run:

```bash
./run.sh uv run pytest --no-cov tests/test_status_flow_diagram.py tests/test_analyze_plugin_logs.py
./run.sh uv run python -m json.tool docs/agent_conversations/2026-07-14_repair-launch-gate-conflict-startup.json
```

### 7. Validate, package locally, and commit atomically

Use coherent Conventional Commits and keep each commit passing. A suitable sequence is:

1. `test(launch-gate): reproduce startup scope acquisition failures` with the minimal GREEN
   implementation required by hook-enforced TDD;
2. `fix(launch-gate): bridge startup into verified Steam scope freeze`;
3. `fix(launch-gate): sanitize systemctl library environment` if not inseparable from step 2;
4. `test(logs): detect launch-gate acquisition failures` with analyzer implementation;
5. `docs(launch-gate): document verified startup acquisition`.

Run the generated Quality Gates, then build and validate a local package:

```bash
./run.sh uv run python scripts/package_plugin.py
./run.sh uv run python scripts/validate_plugin_zip.py out/SDH-Ludusavi.zip --expected-name SDH-Ludusavi
git diff --check
git status --short
```

Inspect the final diff and confirm:

- no PID-only or process-tree path can return `status=paused`;
- every bootstrap stop is released on success/failure unless the original PID disappeared;
- successful acquisition still owns a verified scope lease after bootstrap release;
- no systemctl child receives Decky/PyInstaller's private `LD_LIBRARY_PATH`;
- exact cgroup/unit/path/device/inode validation remains intact;
- public RPC and frontend conflict contracts are unchanged;
- the log analyzer flags the field regression; and
- no raw device logs, generated caches, unrelated thermo plan, review note, release, tag, or
  branch mutation is included.

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

### Automated verification required in the implementation branch

In addition to every focused command in Implementation Tasks, run the generated Quality
Gates exactly as written. Expected results are zero exit status, no deleted review note, a
clean working tree, all Python/frontend tests passing, coverage above the configured floor,
and a valid local Decky ZIP whose packaged version matches the normal local hash policy.

Use a synthetic end-to-end regression fixture to prove this exact ordering:

```text
Steam lifetime PID -> temporary PID stop -> scope initially not ready -> exact scope appears
-> systemctl environment sanitized -> scope freeze requested and completed -> PID stop released
-> conflict detected -> modal choice resolved -> exact scope thawed once
```

Also prove every failure prefix of that sequence releases the bootstrap stop, changes no save,
creates no lease unless scope freeze was verified, and produces an analyzer-visible failure.

### Deferred on-device verification

Device installation, GitHub pushes, tags, and development/stable releases are not authorized
by this planning task and must not be performed by the implementer. After the orchestrator
has approved and finalized the implementation, wait for separate user authorization to build
or install a development release on `steamdeck`.

Once authorized and installed, repeat the field case with a Proton/non-Steam game whose local
save and backup intentionally differ:

1. Record the installed plugin version and pull fresh plugin logs into a new directory under
   `/tmp/sdh_ludusavi/steamdeck/logs`; do not commit them.
2. Launch the game. Confirm the systemd journal may report Steam's process notification just
   before `Started app-steam-app3156562597-3973.scope`, but the plugin waits through that
   ordering and logs a verified scope freeze instead of `Launch PID is not in an exact Steam
   app scope`.
3. Confirm no `systemctl ... libcrypto.so.3`, OpenSSL symbol-version, scope-discovery, or
   scope-freeze failure appears.
4. Leave the conflict modal unanswered for at least 15 seconds. Read `cgroup.freeze` and
   `cgroup.events` for the exact scope and confirm requested/completed frozen state remains 1.
   Confirm the game does not initialize DXVK, create windows, receive focus, or visibly
   advance.
5. Choose `Restore Backup Save`. Confirm restore completes before one verified thaw and the
   game then initializes normally.
6. Repeat with `Keep Local Save` and modal dismissal. Each path must apply or deliberately
   skip its save action before exactly one thaw, with no launch-gate failure toast.
7. Exercise plugin unload/frontend loss while the modal is open. Confirm the renewable lease
   or watchdog thaws the exact scope within its bound and leaves no stopped bootstrap PID or
   frozen unit.
8. Run the analyzer in strict mode against only the fresh logs:

   ```bash
   ./run.sh uv run python scripts/analyze_plugin_logs.py --strict /tmp/sdh_ludusavi/steamdeck/logs/launch-gate-acceptance/*.log
   ```

   Expect no scope-acquisition/freeze failure, conflict-skipped, lease-expiry,
   resume-before-resolution, warning/error, or traceback finding attributable to this fix.
9. Record the notification/scope/freeze/conflict/action/thaw timestamps and result in the
   durable review or release-approval record before authorizing a public release.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished repair-launch-gate-conflict-startup
```

This writes:

```text
/tmp/sdh_ludusavi/repair-launch-gate-conflict-startup_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer repair-launch-gate-conflict-startup`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/repair-launch-gate-conflict-startup-review-*.md
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
   scripts/orchestration/clear-finished repair-launch-gate-conflict-startup
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
   git add docs/review/repair-launch-gate-conflict-startup-review-*.md
   git commit -m "docs(review): record repair-launch-gate-conflict-startup review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished repair-launch-gate-conflict-startup
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer repair-launch-gate-conflict-startup` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed repair-launch-gate-conflict-startup
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize repair-launch-gate-conflict-startup
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/repair-launch-gate-conflict-startup_finalized
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
scripts/orchestration/finalize repair-launch-gate-conflict-startup
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/repair-launch-gate-conflict-startup_finished
/tmp/sdh_ludusavi/repair-launch-gate-conflict-startup_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.

## Release-gate recovery (2026-07-14)

The first authorized dev-release run (`29380777694`) passed its backend suite but
stopped before packaging because pnpm 10.23.0's legacy audit endpoint now returns HTTP
410. The existing pnpm `--ignore-registry-errors` option preserves vulnerability
failures while allowing registry transport/server failures to be reported without
blocking an otherwise validated release.

- Add a static regression assertion that both pre-install and post-install audits use
  `--ignore-registry-errors` together with the existing `moderate` vulnerability level.
- Verify the assertion fails before changing the supply-chain script.
- Update only the two audit invocations; keep frozen installation, install-script
  validation, build, typecheck, and frontend tests unchanged.
- Re-run the complete quality gate, commit atomically, promote through `dev` and `main`,
  then dispatch the dev release from the new main commit.
