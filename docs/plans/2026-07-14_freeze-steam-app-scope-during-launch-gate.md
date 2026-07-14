# Plan: Freeze Steam App Scope During Launch Gate (freeze-steam-app-scope-during-launch-gate)

## Context

On 2026-07-14, an on-device save conflict proved that the launch gate's success log did
not mean the whole Steam game remained paused. The plugin received app lifetime PID
`12992`, logged `Paused game process tree rooted at PID 12992` at 12:32:46, and displayed
the conflict at 12:32:52. Before the user chose an action at 12:32:56, Steam added tracked
PIDs `13305` and `13311`; `Wolverine.exe` initialized through DXVK and created game windows
at 12:32:54-55. The restore completed and the original root was resumed only afterward,
but the actual game had already advanced.

The backend cause is in `py_modules/sdh_ludusavi/watchdog.py`. `_process_tree(pid)` takes
one `/proc` snapshot and `_send_signal_tree(...)` reports success when it signals at least
one member. Steam and Proton can later attach additional processes to the same Steam app
scope without placing them under the originally captured tree. The renewable lease keeps
renewing the original PID record, so neither the backend nor the frontend recognizes that
the gate failed to cover the later game processes.

SteamOS provides the correct process boundary. The incident created the user-systemd unit
`app-steam-app3156562597-12992.scope`; the device runs systemd 257 with `systemctl --user
freeze` and `thaw`, and uses the unified cgroup v2 hierarchy. The systemd freeze command
suspends every process in a unit's cgroup, while cgroup v2 exposes requested state through
`cgroup.freeze` and completed state through `cgroup.events`. A process attached after the
freeze request inherits the frozen cgroup instead of escaping a one-time PID snapshot.

Primary behavior references:

- systemd `freeze`/`thaw`: https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
- kernel cgroup v2 freezer: https://docs.kernel.org/admin-guide/cgroup-v2.html

At plan-authoring time, `README.md`, `assets/demo.webp`, and
`docs/agent_conversations/2026-07-14_review-conflict-launch-and-update-readme.json` are
uncommitted work from a separate user request. They are outside this plan. Before starting
implementation, the orchestrator must ensure that work has been committed separately or
otherwise moved out of the implementation worktree with the user's authorization. The
implementer must never stage, modify, discard, or absorb those files into this feature.

### Problem Definition

The launch gate must prevent every process in the Steam app scope from executing while
pre-game save verification, Syncthing settlement, or conflict resolution is pending. A
successful pause response must be issued only after the exact Steam app scope has reached a
verified frozen state. If the scope cannot be discovered, frozen, or verified, the backend
must return a failed pause result. The existing frontend then fails safely: it may inspect
save state, but it does not restore, back up, or resolve a conflict while the game is
loading.

The fix must retain these safety properties:

- the public pause/renew/resume RPC names, arguments, and successful result fields remain
  compatible with the current frontend lease helper;
- lease renewal keeps the scope frozen while a user leaves the conflict modal open;
- normal completion, dismissed conflicts, failures, stale lifecycle work, plugin unload,
  lease expiry, and the absolute watchdog ceiling all thaw the exact scope once;
- a launcher PID exiting does not orphan a frozen scope or invalidate an otherwise live
  lease;
- PID reuse, unit-path spoofing, cgroup-path traversal, missing unified cgroups, unavailable
  user systemd, and command timeouts fail closed without freezing an unrelated unit;
- no direct SIGSTOP/SIGCONT fallback may return `status=paused`, because that would preserve
  the observed unsafe success semantics.

### Architecture Overview

Split scope discovery and systemd transitions out of the already-large watchdog module:

1. Add `py_modules/sdh_ludusavi/launch_gate.py` with a small `SystemdScopeController`.
   It validates the launcher PID and ownership, reads its unified entry from
   `/proc/<pid>/cgroup`, accepts only an exact Steam app scope beneath the current user's
   `app.slice`, and records the cgroup directory identity.
2. Execute `systemctl --user freeze <exact-unit>` and `systemctl --user thaw <exact-unit>`
   with argv lists, `shell=False`, captured bounded output, a short timeout, and an explicit
   user-bus environment derived from the current UID when Decky did not provide it.
3. Verify transitions using cgroup v2 files. `cgroup.freeze` must show the requested state;
   poll the `frozen` field in `cgroup.events` to a bounded deadline before declaring the
   initial pause or final thaw successful. Accept a disappearing cgroup as an idempotent
   thaw only after its stored directory identity can no longer exist.
4. Refactor `ProcessWatchdog` to lease the verified scope identity rather than a process-tree
   snapshot. Renewal checks the lease ID, the stable cgroup directory identity, and the
   requested frozen state; it must not fail merely because the original launcher PID exited.
5. Keep frontend lease scheduling and RPC surfaces unchanged. Update backend logs, the log
   analyzer, active diagrams/specifications, and tests to describe scope freeze/thaw rather
   than SIGSTOP/SIGCONT.

Do not write `cgroup.freeze` directly, use privileged helpers, freeze a parent slice, modify
Steam/Proton/Ludusavi, or add a polling loop that repeatedly scans arbitrary user processes.
The backend runs as the Deck user and must target only the one validated app scope through
that user's systemd manager.

### Core Data Structures

- `SteamAppScope` (frozen dataclass): exact unit name, normalized cgroup path, cgroup device
  and inode identity, and the original verified launcher PID for diagnostics.
- `ScopeTransitionResult` or an equivalently explicit internal result: success/failure,
  concise reason, and whether the cgroup disappeared during an idempotent thaw.
- `SystemdScopeController`: `discover(pid)`, `freeze(scope)`, `thaw(scope)`,
  `freeze_requested(scope)`, and bounded `wait_for_frozen(scope, expected)` operations. Make
  filesystem roots, command runner, monotonic clock, and wait behavior injectable for tests.
- `_PauseLease`: `SteamAppScope`, original pause timestamp, opaque lease ID, and monotonic
  renewal deadline. Do not use continued existence of the launcher PID as scope liveness.

### Public Interfaces

Keep the existing RPC contract unchanged:

```text
pause_game_process(pid) -> {status, pid, lease_id, lease_ttl_seconds}
renew_game_process_pause(pid, lease_id) -> {status, pid, lease_ttl_seconds}
resume_game_process(pid, lease_id?) -> {status, pid, ...}
```

Failure results remain compatible `failed` results with a concise message. Do not require an
app ID or scope name from the frontend; discover the authoritative unit from the launch PID's
own cgroup membership. `main.py`, `src/api/ludusaviRpc.ts`, `src/types/index.ts`, and
`src/controllers/launchGateLease.ts` should require no observable API change. Touch them only
if a test proves a compatibility defect, and document the reason in the session log.

Use transition-oriented backend messages that let field logs distinguish a verified gate
from a failed one, for example:

```text
launch_gate: Froze Steam app scope app-steam-app3156562597-12992.scope for root PID 12992
launch_gate: Thawed Steam app scope app-steam-app3156562597-12992.scope for root PID 12992
```

Do not log raw command environments, D-Bus addresses, full cgroup paths, or unbounded command
output. Sanitize stderr to one bounded line when reporting a failure.

### Dependency Requirements

No Python, TypeScript, or package dependency changes are allowed. Runtime support requires
systemd's unit freezer (introduced before the installed systemd 257) and unified cgroup v2.
Detect either capability at runtime and return a failed pause result if it is unavailable.
Use only Python stdlib modules such as `dataclasses`, `os`, `pathlib`, `re`, `subprocess`,
and `time`.

### Testing Strategy

Follow strict RED-GREEN-REFACTOR. All on-device log material stays under
`/tmp/sdh_ludusavi`; tests use synthetic PIDs, units, proc files, cgroup files, and command
results. Unit tests must not call the host's real systemd manager or mutate real cgroups.

Backend tests must prove:

- valid unified `/proc/<pid>/cgroup` discovery resolves only the current user's exact
  `app-steam-app<digits>-<digits>.scope` beneath `app.slice`;
- wrong UID, malformed/v1 cgroup entries, missing files, traversal, symlinks escaping the
  cgroup root, non-Steam units, parent slices, and stale directory identity are rejected;
- freeze/thaw use exact argv, no shell, bounded timeouts, and the correct user-bus defaults;
- pause is not successful until `cgroup.freeze=1` and `cgroup.events` reports `frozen 1`;
- thaw is not successful until requested/completed state is zero, while a vanished scope is
  safe and idempotent;
- a late process represented as joining the already frozen fake scope remains covered without
  another PID-tree signal call;
- renewal survives launcher exit, extends only the matching lease, rejects changed scope
  identity or unexpected thaw, and never silently converts a failure into success;
- normal release, retry after thaw failure, plugin stop, lease expiry, absolute ceiling, PID
  reuse, and concurrent pause/resume leave no orphaned frozen scope;
- service, Decky RPC, and frontend result-shape compatibility tests remain green;
- the analyzer recognizes both historical process-tree pause logs and new scope-freeze logs,
  preserving existing rule IDs for watchdog expiry/resume-before-resolution incidents;
- active diagrams and specs describe `systemctl --user freeze/thaw` and cgroup coverage rather
  than promising a one-time SIGSTOP tree is sufficient.

**Slug used throughout this plan:** `freeze-steam-app-scope-during-launch-gate`

---

## Orchestration Contract

**Slug:** `freeze-steam-app-scope-during-launch-gate`

**Plan file:**

```text
docs/plans/2026-07-14_freeze-steam-app-scope-during-launch-gate.md
```

**Implementation branch:**

```text
feat/freeze-steam-app-scope-during-launch-gate
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/freeze-steam-app-scope-during-launch-gate_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/freeze-steam-app-scope-during-launch-gate_finalized
```

**Review notes:**

```text
docs/review/freeze-steam-app-scope-during-launch-gate-review-*.md
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
git checkout -b feat/freeze-steam-app-scope-during-launch-gate
```

Commit this plan first:

```bash
git add docs/plans/2026-07-14_freeze-steam-app-scope-during-launch-gate.md
git commit -m "docs(plan): add freeze-steam-app-scope-during-launch-gate implementation plan"
```

---

## Implementation Tasks

### 1. Protect unrelated work, commit the plan, and capture RED evidence

Before branching, run `git status --short` and enforce the clean-worktree precondition from
Context. If the unrelated README/demo/session files are still present, stop and report the
blocker; do not stash, delete, stage, or commit them. After the orchestrator provides a clean
worktree, follow Setup and commit only this plan first.

Create `tests/test_launch_gate_scope.py` before creating the production scope-controller
module. Add the discovery, validation, command, timeout, state-verification, and idempotent
thaw cases listed in Testing Strategy. Add failing scope-lease cases to
`tests/test_watchdog.py` before refactoring `ProcessWatchdog`. Use test doubles and temporary
`proc`/cgroup trees; no test may invoke real `systemctl`.

Run the focused RED commands and record the expected failures and their reason in the session
log:

```bash
./run.sh uv run pytest --no-cov tests/test_launch_gate_scope.py
./run.sh uv run pytest --no-cov tests/test_watchdog.py
```

The first command must fail because the scope controller is not implemented. The new watchdog
cases must fail because the existing `_PauseLease` still targets a PID tree. Do not weaken or
delete the tests after observing RED.

### 2. Implement validated Steam app-scope discovery and transitions

Create `py_modules/sdh_ludusavi/launch_gate.py` and implement the internal structures from
Architecture Overview.

Discovery must:

1. validate a safe integer PID and confirm `/proc/<pid>` belongs to `os.geteuid()`;
2. parse only the unified `0::` cgroup entry;
3. normalize the path under an injectable `/sys/fs/cgroup` root without following an escape;
4. accept only a scope basename matching `app-steam-app[0-9]+-[0-9]+.scope` under the current
   user's `user@<uid>.service/app.slice` hierarchy;
5. require readable `cgroup.freeze` and `cgroup.events` files; and
6. store the cgroup directory device/inode identity so PID reuse or unit replacement cannot
   redirect a later thaw.

Transitions must:

1. run only `systemctl --user freeze <unit>` or `systemctl --user thaw <unit>` as argv;
2. set `XDG_RUNTIME_DIR=/run/user/<uid>` and
   `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus` only when absent;
3. use a named timeout constant and convert missing executables, timeout, nonzero exit, and
   malformed state files into bounded failure results;
4. verify requested state via `cgroup.freeze` and completion via the `frozen` field in
   `cgroup.events`, polling with an injectable monotonic clock/wait until a short deadline;
5. best-effort thaw after a partial freeze failure; and
6. treat a genuinely disappeared, identity-checked scope as already thawed while never
   treating an extant frozen scope as success after a failed thaw command.

Run and make GREEN:

```bash
./run.sh uv run pytest --no-cov tests/test_launch_gate_scope.py
```

### 3. Move renewable watchdog leases from PID trees to scope identities

Refactor `py_modules/sdh_ludusavi/watchdog.py` to accept an injectable
`SystemdScopeController` and store the discovered `SteamAppScope` in `_PauseLease`.

- `pause(pid)` must serialize by PID, discover/freeze/verify the scope, then create the lease
  and return `status=paused`. Never return paused after a PID-only signal.
- If a lease already exists for the PID, preserve safety: rotate a same-scope lease without a
  thaw window, or thaw the old verified scope before targeting a different identity. Add a
  deterministic test for the chosen behavior.
- `renew_pause` must validate the opaque lease and scope directory identity and ensure freeze
  is still requested. It must remain valid after the original launcher PID exits.
- `resume`, watchdog expiry, absolute-ceiling recovery, and `stop()` must thaw the stored
  scope. Remove a lease only after confirmed thaw or confirmed scope disappearance; retain it
  after a retryable thaw failure.
- Keep per-PID transition locking and do not hold the shared lease-state lock while invoking
  systemctl or waiting for freezer state.
- Remove production `_process_tree`, `_read_ppid`, SIGSTOP, and SIGCONT behavior once scope
  tests are green. Do not leave an unsafe fallback that can report success.
- Replace success logs with the bounded freeze/thaw messages in Public Interfaces. Include
  actionable warnings for discovery, transition, lease, and automatic-thaw failures.

Update `tests/test_watchdog.py` and the focused launch-gate portions of
`tests/test_service.py` to assert scope behavior through fakes instead of patching `os.kill`.
Preserve the public service method signatures in `tests/test_compatibility.py` and the Decky
RPC coverage in `tests/test_main.py`.

Keep modules maintainable: add reasonable budgets for `launch_gate.py` and the refactored
`watchdog.py` to `tests/test_module_size_budgets.py`, reducing rather than growing the current
423-line watchdog where practical.

Run and make GREEN:

```bash
./run.sh uv run pytest --no-cov tests/test_launch_gate_scope.py tests/test_watchdog.py tests/test_service.py tests/test_compatibility.py tests/test_main.py tests/test_module_size_budgets.py
```

### 4. Preserve operational diagnostics and documentation contracts

Update `scripts/analyze_plugin_logs.py` and `tests/test_analyze_plugin_logs.py` so pause-event
correlation accepts both the historical `Paused game process tree rooted at PID ...` syntax
and the new verified scope-freeze syntax. If watchdog messages change from PID suspension to
scope freezing, accept both formats and preserve the stable findings
`launch_gate.lease_expired` and `launch_gate.resume_before_resolution`. Add a sanitized scope
fixture only if it improves coverage; never commit the device logs.

Update these active documentation surfaces:

- `docs/specs/custom_status_bar_ui.md`: explain that the renewable lease owns a frozen Steam
  app scope and fails safely when scope gating is unavailable.
- `docs/plans/cloud_sync_conflict_resolution_flow.html`: replace SIGSTOP/SIGCONT labels and
  explanatory text with verified scope freeze/thaw while keeping the standalone diagram.
- `tests/test_status_flow_diagram.py`: require the new terms and reject the obsolete claim.
- `DEVELOPMENT.md`: document the systemd user-manager/cgroup v2 runtime requirement, bounded
  fail-closed behavior, and the relevant launch-gate diagnostics.

Do not rewrite the unrelated README introduction or demo placement. Its existing Launch Gate
feature sentence remains accurate after this fix and needs no plan-owned edit.

Run:

```bash
./run.sh uv run pytest --no-cov tests/test_analyze_plugin_logs.py tests/test_status_flow_diagram.py
```

### 5. Document the implementation and commit atomically

Create
`docs/agent_conversations/2026-07-14_freeze-steam-app-scope-during-launch-gate.json` with the
required date, objective, files modified, RED tests, design decisions, results, and deferred
on-device verification. Mention the confirmed field timeline without copying raw log content
or device paths beyond the sanitized unit/PID example already in this plan.

Use coherent Conventional Commits. A suitable sequence is:

1. `test(launch-gate): define Steam scope freeze contract` together with the minimal GREEN
   scope controller if the pre-commit hook requires each commit to pass;
2. `fix(launch-gate): freeze the complete Steam app scope`;
3. `docs(launch-gate): document scope freeze safety`.

Do not commit a deliberately red tree. Preserve RED command output in the session log, then
commit each group only after its focused tests pass.

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

### Automated verification

Run focused regression coverage first:

```bash
./run.sh uv run pytest --no-cov tests/test_launch_gate_scope.py tests/test_watchdog.py tests/test_service.py tests/test_compatibility.py tests/test_main.py tests/test_analyze_plugin_logs.py tests/test_status_flow_diagram.py tests/test_module_size_budgets.py
```

Then run the generated Quality Gates exactly as written. Confirm that Ruff, formatting,
`ty`, all Python tests with the repository coverage threshold, frontend supply-chain checks,
Vitest, TypeScript checking, and the production build pass. Confirm `git diff --check` and a
clean `git status --short` after all changes are committed.

Build and validate a local development package without publishing or installing it:

```bash
./run.sh uv run python scripts/package_plugin.py
./run.sh uv run python scripts/validate_plugin_zip.py out/SDH-Ludusavi.zip --expected-name SDH-Ludusavi
```

Inspect the final diff and verify:

- no production `os.kill(..., SIGSTOP/SIGCONT)` launch-gate path remains;
- no systemctl call uses a shell, wildcard, caller-provided unit, parent slice, or unbounded
  wait;
- all error paths thaw or retain a retryable lease as specified;
- public RPC signatures and frontend types remain compatible; and
- raw Steam/Decky logs and generated caches are absent from Git status.

### Deferred on-device acceptance

On-device verification is required before declaring the runtime defect field-verified, but
is deferred until the user separately authorizes installation or a development release. The
implementer must not install on a Deck, push a release, or dispatch a release workflow as
part of this plan.

After an authorized build is installed on `steamdeck`, perform these acceptance checks with
a Proton/non-Steam game whose local save and backup intentionally differ:

1. Launch the game and leave the conflict modal unanswered for at least 15 seconds.
2. Confirm the plugin logs a verified freeze for the exact
   `app-steam-app<appid>-<pid>.scope` before displaying the conflict.
3. Read that scope's `cgroup.freeze` and `cgroup.events`; confirm freeze remains requested and
   completed while the modal is open, even after Steam adds later tracked PIDs.
4. Confirm Steam may log later PIDs joining the app, but the game executable does not
   initialize DXVK, create windows, receive focus, or visibly advance before resolution.
5. Choose `Restore Backup Save`; confirm restore finishes before the scope is thawed, then the
   game initializes normally.
6. Repeat with `Keep Local Save` and with modal dismissal; each path must perform its selected
   save action, or deliberately skip it, before exactly one thaw.
7. Exercise plugin unload or frontend loss while a conflict is open; the lease/watchdog path
   must thaw the scope within the bounded lease TTL and leave no frozen game unit.
8. Pull the fresh plugin logs into `/tmp/sdh_ludusavi/steamdeck/logs` and run
   `scripts/analyze_plugin_logs.py --strict`; expect no launch-gate expiry,
   resume-before-resolution, warning/error, or traceback finding.

Record the installed version, scope unit, timestamps, freezer states, result, and any
remaining limitation in the durable session/review record before release approval.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished freeze-steam-app-scope-during-launch-gate
```

This writes:

```text
/tmp/sdh_ludusavi/freeze-steam-app-scope-during-launch-gate_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer freeze-steam-app-scope-during-launch-gate`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/freeze-steam-app-scope-during-launch-gate-review-*.md
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
   scripts/orchestration/clear-finished freeze-steam-app-scope-during-launch-gate
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
   git add docs/review/freeze-steam-app-scope-during-launch-gate-review-*.md
   git commit -m "docs(review): record freeze-steam-app-scope-during-launch-gate review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished freeze-steam-app-scope-during-launch-gate
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer freeze-steam-app-scope-during-launch-gate` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed freeze-steam-app-scope-during-launch-gate
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize freeze-steam-app-scope-during-launch-gate
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/freeze-steam-app-scope-during-launch-gate_finalized
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
scripts/orchestration/finalize freeze-steam-app-scope-during-launch-gate
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/freeze-steam-app-scope-during-launch-gate_finished
/tmp/sdh_ludusavi/freeze-steam-app-scope-during-launch-gate_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
