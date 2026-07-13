# Plan: Harden Launch-Gate Lifecycle and Add Reusable Log Regression Analysis (launch-gate-log-regression)

## Plan Metadata

```text
TITLE=Harden Launch-Gate Lifecycle and Add Reusable Log Regression Analysis
SLUG=launch-gate-log-regression
PLAN_PATH=docs/plans/2026-07-12_launch-gate-log-regression.md
BRANCH=feat/launch-gate-log-regression
```

## Context

On 2026-07-12, six current and rotated SDH-Ludusavi Decky logs were copied from
`steamdeck:/home/deck/homebrew/logs/SDH-Ludusavi/` to the project temp area and reviewed.
The installed Deck build was `0.3.5`; the checkout was `0.3.6`. The newest log had no
warnings, errors, critical records, or tracebacks, but the recent history exposed two
launch-gate data-integrity risks, one orphaned Syncthing watch, and overly verbose
diagnostics. Source inspection confirmed that the two launch-gate mechanisms still exist
in the checkout.

Observed evidence:

1. The frontend classified 32 app starts as `tracked=false` and only 6 as `tracked=true`.
   Several `tracked=false` games were immediately matched by the backend. For one
   Warhammer conflict, the frontend did not pause the process and emitted `Launch gate
   unavailable; conflict resolution skipped while game is loading.` The frontend store
   starts with empty tracking sets, `createStartupHydration` currently fetches settings
   only, and the game list is not applied until the QAM content initialization path runs.
2. Three of six successfully paused launches were automatically resumed by the backend
   watchdog at 15 seconds while the conflict modal was still awaiting the user's choice.
   The selected backup/restore operation then ran after the game process was already
   active; final cleanup logged `PID ... is not tracked`. The watchdog treats the gap
   between backend RPCs as idle because it consults `OperationCoordinator.is_running`,
   which cannot represent a frontend-owned conflict prompt.
3. One post-game Syncthing watch reached its 180-second backend TTL without
   `stop_watch`. The incident crossed a frontend reinitialization and was only recovered
   by the backend self-termination guard.
4. Lifecycle logs stringify full RPC results. Successful backup lines reached almost
   5 KB and included complete save paths and redirected paths. BrowserView diagnostics
   also dump large property-name inventories. This conflicts with `DEVELOPMENT.md`, which
   requires transition-oriented diagnostics rather than full settings/payload dumps.

This plan fixes the runtime causes and converts the useful parts of the ad-hoc log review
into reusable development tools and deterministic regression tests. Raw on-device logs
must remain under `/tmp/sdh_ludusavi`; do not commit them. Commit only minimal synthetic,
sanitized fixtures that reproduce event sequences without real game libraries, device
identifiers, usernames, backup paths, or save contents.

### Problem Definition

The launch gate cannot currently guarantee that a recognized game remains paused until
restore/conflict handling is complete:

- a cold or failed frontend tracking cache can prevent the initial pause even when the
  backend recognizes the game;
- a correctly paused game can be resumed by an idle watchdog timeout while the user is
  still reading or answering the conflict dialog.

The system also lacks a repeatable way to detect these cross-line temporal failures from
field logs. Existing unit tests cover isolated matching, controller decisions, watchdog
resume behavior, and Syncthing cleanup, but they do not encode the observed end-to-end
sequences.

The intended result is:

- lifecycle tracking data is ready before normal launch classification;
- if tracking data is unavailable, launch protection fails conservatively for a bounded
  period instead of silently skipping the gate;
- a paused launch is represented by a renewable lease that remains valid while the
  frontend is alive and waiting for a user decision, but expires promptly if the frontend
  disappears;
- a new lifecycle phase supersedes any older Syncthing watch for the same game;
- logs remain useful without containing full operation payloads or multi-kilobyte runtime
  object inventories;
- developers can pull logs to the standard temp path and run a deterministic analyzer that
  reports the same invariant violations found in this review.

### Architecture Overview

The remediation has five bounded layers:

1. **Lifecycle bootstrap:** extend `src/runtime/startupHydration.ts` so the readiness
   promise covers both settings and a cached/non-forced `refresh_games` call. Apply the
   returned games and aliases directly to `LudusaviStateStore` before lifecycle events are
   classified. QAM initialization remains responsible for selection/UI behavior and fresh
   installed-app reconciliation.
2. **Conservative cold-state gating:** add an explicit tracking-readiness state to
   `LudusaviStateStore`. A valid launch PID is guarded when the game is tracked *or* tracking
   readiness is not `ready`. The backend check then determines whether the cold-state guard
   is retained for restore/conflict work or released immediately for an unmatched/disabled
   game.
3. **Renewable pause lease:** replace the watchdog's inference from
   `OperationCoordinator.is_running` with a lease owned by each paused PID. The frontend
   renews the lease while start-check, restore, and conflict UI work is pending. Missing
   renewals resume the game after a short bounded TTL; the existing absolute ceiling remains
   the unconditional safety net.
4. **Watch ownership and diagnostics:** make a new Syncthing watch supersede any existing
   watch for the same game/app across phases, await normal frontend stop paths, and replace
   full payload logging with stable summaries.
5. **Operational regression tooling:** add dependency-free Python scripts for pulling the
   Decky log set and analyzing one or more logs. The analyzer is a diagnostic aid and CI
   fixture target; product correctness remains enforced by focused Vitest/Pytest tests.

Do not move runtime matching into the log analyzer, do not make production behavior depend
on log text, and do not modify `pyludusavi` or any other upstream package.

### Core Data Structures

- `TrackingReadiness = "cold" | "ready" | "failed"` in the frontend store.
- `PauseLease` backend record containing the verified `_ProcessIdentity`, original pause
  timestamp, opaque lease ID, and monotonic lease deadline.
- `PauseLeaseHandle` frontend helper containing PID, lease ID, renewal timer, active flag,
  `renew()`, and idempotent `release()` behavior.
- `LogEvent` parsed from a Decky line: source path, line number, timestamp, level, operation,
  message, optional PID/app ID/watch ID.
- `LogFinding` with a stable rule ID, severity (`error`, `warning`, `info`), source location,
  concise evidence, and remediation hint.

Stable analyzer rule IDs introduced by this work:

- `launch_gate.backend_match_after_untracked_start`
- `launch_gate.resume_before_resolution`
- `launch_gate.lease_expired`
- `syncthing.watch_ttl_expired`
- `diagnostics.error_or_traceback`
- `diagnostics.oversized_or_raw_payload`

### Public Interfaces

Backend RPC additions, mirrored through `main.py` and `src/api/ludusaviRpc.ts`:

```text
pause_game_process(pid) -> {status, pid, lease_id, lease_ttl_seconds}
renew_game_process_pause(pid, lease_id) -> {status, pid, lease_ttl_seconds}
resume_game_process(pid) -> existing compatible result shape
```

`pause_game_process` retains its current name and existing `status`/`pid` fields so older
callers remain readable. The new frontend requires a valid `lease_id`; a missing or malformed
lease response is treated as a failed gate and the process is resumed best-effort.

Developer commands introduced by this work:

```bash
./run.sh uv run python scripts/pull_plugin_logs.py --host steamdeck
./run.sh uv run python scripts/analyze_plugin_logs.py /tmp/sdh_ludusavi/steamdeck/logs
./run.sh uv run python scripts/analyze_plugin_logs.py --strict --format json <path>...
```

The pull command defaults to plugin `SDH-Ludusavi` and destination
`/tmp/sdh_ludusavi/<host>/logs`, validates the host/plugin tokens before passing argv to
`ssh`/`scp`, and never writes inside the repository. The analyzer accepts files or
directories, sorts files deterministically, emits human-readable text by default, and
supports JSON for automation. Define exit codes as `0` for a completed analysis with no
strict violations, `1` when `--strict` finds an error-severity invariant violation, and `2`
for invalid arguments or unreadable input.

### Dependency Requirements

No runtime or development dependency changes are required. Use Python stdlib only for log
pulling/parsing (`argparse`, `dataclasses`, `json`, `pathlib`, `re`, `subprocess`) and existing
Vitest/Pytest/fake-timer facilities for tests.

### Testing Strategy

Strict TDD applies to every runtime behavior change. Preserve the observed failure sequences
as synthetic fixtures and focused tests:

- frontend startup tests prove tracking is applied before readiness resolves, settings and
  tracking failures are isolated, disposal blocks both late writes, and QAM initialization
  reuses the hydrated store;
- controller tests prove a cold cache conservatively pauses, unmatched backend results
  release immediately, matched restore/conflict results stay gated, a conflict decision can
  remain open well past 15 seconds while renewals continue, and cleanup releases exactly once;
- backend watchdog tests prove matching renewal extends a lease, stale/wrong lease IDs do not,
  an expired lease resumes, active leases ignore the former idle threshold, the absolute
  ceiling still resumes, PID identity protection remains intact, and shutdown resumes all;
- Syncthing tests prove cross-phase supersession and awaited stop behavior;
- diagnostic-summary tests prove no lifecycle line contains serialized `result.files`,
  `backupPath`, `/home/deck`, `/run/media`, or runtime property inventories;
- analyzer tests feed clean and failing sanitized fixtures, assert stable finding IDs and
  locations, exercise text/JSON/strict exit behavior, and verify malformed lines do not crash
  the scan;
- pull-script tests mock `subprocess.run`, verify plain `ssh <host>` / `scp` argv and temp
  destination construction, and reject unsafe host/plugin values without executing commands.

**Slug used throughout this plan:** `launch-gate-log-regression`

---

## Orchestration Contract

**Slug:** `launch-gate-log-regression`

**Plan file:**

```text
docs/plans/2026-07-12_launch-gate-log-regression.md
```

**Implementation branch:**

```text
feat/launch-gate-log-regression
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/launch-gate-log-regression_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/launch-gate-log-regression_finalized
```

**Review notes:**

```text
docs/review/launch-gate-log-regression-review-*.md
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
git checkout -b feat/launch-gate-log-regression
```

Commit this plan first:

```bash
git add docs/plans/2026-07-12_launch-gate-log-regression.md
git commit -m "docs(plan): add launch-gate-log-regression implementation plan"
```

---

## Implementation Tasks

### 1. Commit the plan and establish RED baselines

Commit this generated plan first as required by the orchestration contract. Then add failing
tests in small coherent groups before changing the corresponding production code. For each
group, run the narrow test command and record the expected failure in the session log before
implementing.

Do not copy `/tmp/sdh_ludusavi/steamdeck/logs` into the repository. Create only sanitized
fixtures under `tests/fixtures/plugin_logs/`, using fictional game names, PIDs, app IDs, watch
IDs, and paths.

Recommended commit boundaries:

1. `test(logs): add reusable plugin log regression analyzer`
2. `fix(lifecycle): hydrate tracking before launch classification`
3. `fix(launch-gate): keep paused launches alive with renewable leases`
4. `fix(syncthing): supersede stale cross-phase watches`
5. `fix(logging): summarize lifecycle and BrowserView diagnostics`
6. `docs: document log regression workflow and session results`

If a test-only commit would leave the branch intentionally red, keep the RED test and GREEN
implementation in the same atomic commit, but preserve command output in the session log to
prove test-first order.

### 2. Add reusable pull and log-analysis tooling

Create:

- `scripts/pull_plugin_logs.py`
- `scripts/analyze_plugin_logs.py`
- `tests/test_pull_plugin_logs.py`
- `tests/test_analyze_plugin_logs.py`
- `tests/fixtures/plugin_logs/clean.log`
- `tests/fixtures/plugin_logs/cold-tracking-conflict.log`
- `tests/fixtures/plugin_logs/watchdog-resume-before-resolution.log`
- `tests/fixtures/plugin_logs/syncthing-ttl-expiry.log`

Follow the existing `tests/test_package_plugin.py` convention for importing a script module
with `importlib.util`. Keep orchestration/CLI logic thin and move parsing/correlation into pure
functions in `scripts/analyze_plugin_logs.py` so tests do not spawn Python for every assertion.
Use subprocess tests only for final CLI exit-code coverage.

The pull script must:

1. accept `--host` (default `steamdeck`), `--plugin` (default `SDH-Ludusavi`), and optional
   `--destination`;
2. derive the default destination as `/tmp/sdh_ludusavi/<host>/logs`;
3. validate host and plugin as conservative SSH/path tokens and reject `/`, whitespace, shell
   metacharacters, and traversal;
4. create the destination with `Path.mkdir(parents=True, exist_ok=True)`;
5. inspect the remote directory with argv-based `ssh`, then copy its regular log files with
   argv-based `scp -p`; do not use `shell=True`;
6. print the resolved destination and copied-file count;
7. preserve existing files unless the same filename is refreshed, and never delete logs.

The analyzer must:

1. parse the existing Decky format without assuming every line is well formed;
2. count levels exactly (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) and separately detect
   traceback/exception markers;
3. correlate pause/resume/conflict/action lines by PID and app/lifecycle order;
4. report a high-severity `resume_before_resolution` when watchdog resume precedes the user's
   conflict action or final gate cleanup;
5. report `backend_match_after_untracked_start` when an app logged `tracked=false` and the
   corresponding backend check returns a matched, actionable/current result rather than
   `unmatched_game`;
6. report Syncthing TTL self-termination and oversized/raw lifecycle result payloads;
7. include file and line numbers in text and JSON output;
8. deduplicate repeated evidence for one lifecycle incident while preserving an occurrence
   count;
9. avoid treating benign words such as `failures_errors`, `timeout` status sources, or
   intentional `skipped` results as failures;
10. remain useful on future log versions by reporting unknown/malformed lines as parse stats,
    not fatal errors.

Add a narrow regression command to `DEVELOPMENT.md`, including the explicit warning that raw
Deck logs are user/device data and stay in `/tmp`. Do not add the operational pull to CI; CI
runs only the synthetic analyzer fixtures.

RED command:

```bash
./run.sh uv run pytest tests/test_pull_plugin_logs.py tests/test_analyze_plugin_logs.py
```

### 3. Hydrate lifecycle tracking independently of QAM mounting

Modify:

- `src/runtime/startupHydration.ts`
- `src/runtime/startupHydration.test.ts`
- `src/state/ludusaviState.tsx`
- `src/state/ludusaviState.test.tsx`
- `src/index.tsx`
- `src/components/qam/useInitialContent.ts` and its test only if needed to prevent redundant
  refresh/selection side effects
- `src/types/index.ts` for the `TrackingReadiness` type if it is shared

Add `trackingReadiness` to `LudusaviStateSnapshot`, initialized to `cold`. Make
`applyRefreshResult` set it to `ready`, including a valid empty game list. Add an explicit
`markTrackingFailed()` transition that leaves games/aliases untouched and sets `failed`.

Extend `StartupHydrationDeps` with separate tracking callbacks:

```text
fetchTracking(): Promise<RpcResult<RefreshResult>>
applyTracking(result: RefreshResult): void
markTrackingFailed(): void
```

Start settings and tracking fetches together, isolate their failures, and resolve `ready` only
after both branches settle or are disposed. A settings failure must not discard a successful
tracking result; a tracking failure must not discard settings. On dispose, neither late branch
may mutate the store. Log stable events `startup_tracking_hydrated` with game/alias counts or
`startup_tracking_hydration_failed` with an RPC reason/error class; never log the full result.

In `src/index.tsx`, implement tracking fetch as a non-forced `refreshGamesCall(false,
installedAppIds)` where `installedAppIds` comes from `getInstalledAppIdsString()`. Passing
`undefined` is valid and allows the backend registry to return/populate its cached games.
Apply the result directly to the store; do not perform route-hover selection during startup.
The existing QAM path may later reconcile installed app IDs and selection.

RED cases:

- readiness does not resolve until tracking is applied;
- tracking is present when the first lifecycle callback runs without ever mounting QAM;
- empty-but-valid refresh sets readiness to `ready`;
- tracking RPC status/rejection sets `failed` and logs once;
- dispose before either promise resolves causes no late mutation;
- opening QAM after startup hydration does not replace a user's selected game merely because
  the startup tracking snapshot arrived.

Narrow command:

```bash
./run.sh pnpm run test:unit -- src/runtime/startupHydration.test.ts src/state/ludusaviState.test.tsx src/components/qam/useInitialContent.test.ts
```

### 4. Make cold tracking fail conservatively during launch checks

Modify:

- `src/controllers/gameLifecycleController.tsx`
- `src/controllers/gameLifecycleController.test.ts`
- `src/controllers/gameLifecycleController.logging.test.ts`
- `src/controllers/gameLifecycleDecision.ts` and its test if a distinct guarded/tracked state
  is needed

Separate these concepts in controller-local state:

- `tracked`: the frontend cache positively matched the app;
- `trackingReady`: the cache is authoritative for this event;
- `guardCandidate`: `tracked || !trackingReady`;
- `paused`: the backend confirmed the process is paused.

When autosync is enabled and the instance PID is valid, pause if `guardCandidate` is true.
This means a cold/failed cache causes a bounded conservative pause. Continue calling the
backend check. If the backend returns `unmatched_game`, `auto_sync_disabled`, or another silent
skip, cancel any speculative pre-game watch and release the pause immediately in `finally`.
If the backend returns restore-needed or conflict, the existing decision rules may proceed
because `paused=true` protects the save files.

Start the pre-game Syncthing watch for a guarded candidate and rely on existing cleanup when
the backend says the game is unmatched. Do not retain a speculative watch after a silent skip.
Keep status metadata honest (`tracked=false` is allowed) and add `tracking_readiness` and
`guard_candidate` to the lifecycle start summary so the analyzer can distinguish cold safety
behavior from a stale-cache defect.

RED cases:

- cold cache + known backend conflict pauses and allows the modal/action path;
- cold cache + unmatched backend result pauses briefly, then resumes and cancels the watch;
- ready cache + untracked game does not pause;
- ready cache + tracked game preserves current behavior;
- failed tracking hydration follows the cold conservative path and emits one diagnostic;
- invalid/missing instance PID cannot be falsely reported as guarded and retains the existing
  failure notification for actionable restore/conflict results.

Narrow command:

```bash
./run.sh pnpm run test:unit -- src/controllers/gameLifecycleController.test.ts src/controllers/gameLifecycleController.logging.test.ts src/controllers/gameLifecycleDecision.test.ts
```

### 5. Replace watchdog idle inference with renewable pause leases

Modify backend:

- `py_modules/sdh_ludusavi/watchdog.py`
- `py_modules/sdh_ludusavi/constants.py`
- `py_modules/sdh_ludusavi/service.py`
- `main.py`
- `tests/test_watchdog.py`
- `tests/test_service.py`
- `tests/test_main.py` and/or `tests/test_main_rpc.py`
- `tests/test_compatibility.py`

Modify frontend:

- `src/types/index.ts`
- `src/api/ludusaviRpc.ts`
- new `src/controllers/launchGateLease.ts`
- new `src/controllers/launchGateLease.test.ts`
- `src/controllers/gameLifecycleController.tsx`
- `src/controllers/gameLifecycleController.test.ts`

Replace the `_paused_pids` tuple with a private dataclass holding process identity,
`paused_at`, opaque `lease_id`, and `lease_deadline`. Use `time.monotonic()` for elapsed/deadline
logic and a cryptographically unpredictable stdlib token. Keep wall time out of lease expiry.

Add constants with comments explaining their relationship:

```text
LAUNCH_GATE_LEASE_TTL_SECONDS = 30
LAUNCH_GATE_RENEW_INTERVAL_SECONDS = 5
WATCHDOG_ABSOLUTE_RESUME_SECONDS = LUDUSAVI_OPERATION_TIMEOUT_SECONDS + 60
```

The backend must:

- create and return a lease when pause succeeds;
- renew only when PID, verified process identity, and lease ID still match;
- never recreate a missing lease from a renewal call;
- resume when the lease deadline expires, regardless of the coordinator's between-RPC idle
  state;
- not resume merely because `OperationCoordinator.is_running` is false while the lease is
  current;
- retain the unconditional absolute ceiling and PID-reuse protection;
- remove the lease before/after successful explicit resume exactly once;
- resume all leases on backend stop/unload.

Remove the obsolete `is_operation_running` dependency from `ProcessWatchdog` once all callers
and tests use lease semantics. Preserve current `resume_game_process(pid)` compatibility.

The frontend `PauseLeaseHandle` must:

- validate `lease_id` and TTL from the pause response;
- renew every five seconds while active (well inside the 30-second TTL);
- serialize renewals so slow RPCs do not overlap;
- expose an idempotent `release()` that clears timers first and then resumes best-effort;
- notify the controller once if renewal fails, stop further restore/conflict mutation, and
  release/resume best-effort;
- stop renewal during plugin dismount and allow backend expiry if an RPC cannot be sent.

Integrate the handle through the complete start handler. Do not represent the conflict-modal
wait as an `OperationCoordinator` operation and do not extend the old 15-second timeout.
Lease ownership, not an arbitrary user-response duration, is the correctness boundary.

RED backend cases:

- pause returns an opaque lease and deadline metadata;
- correct renewal extends the monotonic deadline;
- wrong token, wrong PID, missing lease, and PID identity change fail without extension;
- current lease survives well beyond the former 15-second idle threshold;
- expired lease automatically resumes and logs `lease expired`;
- absolute ceiling resumes even after recent renewal;
- explicit resume and `stop()` clear all lease state.

RED frontend cases:

- fake timers produce renew calls at the configured interval with no overlap;
- a conflict promise left pending for 60 seconds renews repeatedly and does not call resume;
- resolving the conflict runs the selected action before one final release/resume;
- cancellation, exception, renewal failure, and dismount clear timers and release at most once;
- no backup/restore RPC runs after lease loss.

Narrow commands:

```bash
./run.sh uv run pytest tests/test_watchdog.py tests/test_service.py tests/test_main_rpc.py tests/test_compatibility.py
./run.sh pnpm run test:unit -- src/controllers/launchGateLease.test.ts src/controllers/gameLifecycleController.test.ts
```

### 6. Close cross-phase Syncthing watch ownership gaps

Modify:

- `py_modules/sdh_ludusavi/syncthing/watcher.py`
- `tests/test_watcher.py`
- `src/controllers/gameLifecycleController.tsx`
- `src/controllers/syncthingMonitor.handoffCleanup.test.ts`
- other focused `syncthingMonitor.*.test.ts` files only where assertions require it

In `SyncthingWatchManager.start_watch`, treat an existing watch with the same sanitized
`game_name` and `app_id` as superseded even if its phase differs. Remove it from the manager
under the lock, stop it outside the lock, and only then start/register the replacement using
the existing race-safe pattern. Different games may still have independent watches if current
architecture permits them.

At the start of frontend app-start and app-exit handlers, `await syncthingMonitor.stop()`
before creating the next lifecycle watch. Do not leave the stop as fire-and-forget. Preserve
the generation guards so a stale async stop cannot publish status into the new event.

RED cases:

- a post-game watch followed by a pre-game watch for the same game/app stops and deregisters
  the first watch;
- same-phase replacement still works;
- different game/app does not get stopped accidentally;
- controller waits for stop completion before calling `startWatch` for the new event;
- plugin dispose during allocation stops a late returned watch ID;
- no test waits for the 180-second TTL as normal cleanup.

Narrow commands:

```bash
./run.sh uv run pytest tests/test_watcher.py
./run.sh pnpm run test:unit -- src/controllers/syncthingMonitor.handoffCleanup.test.ts src/controllers/syncthingMonitor.initialization.test.ts src/controllers/gameLifecycleController.test.ts
```

### 7. Bound and sanitize lifecycle diagnostics

Modify:

- `src/controllers/gameLifecycleController.tsx`
- `src/formatting/operationText.ts` or a new focused
  `src/formatting/lifecycleLogSummary.ts`
- matching frontend test file
- `src/surfaces/autoSyncStatusBrowserView.ts` and its tests
- `DEVELOPMENT.md`
- `scripts/analyze_plugin_logs.py` rules/fixtures if final structured messages differ

Add a pure summary helper for `LifecycleCheckResult` and `OperationResult`. Log only stable,
bounded fields such as status, operation, reason, canonical game, and aggregate byte/file
counts when already available. Never stringify nested `result`, `files`, `registry`,
`backupPath`, or error payload objects. Cap/sanitize free-form failure text before logging so a
backend/upstream exception cannot reintroduce a huge payload.

Replace every `JSON.stringify(checkResult|restoreRes|conflictRes|backupResult)` lifecycle log
with the helper. Keep the actual typed result object unchanged for decisions and UI. This is
a diagnostic-only representation change.

In the BrowserView adapter, replace full key/prototype inventories with bounded capability
summaries: candidate source, whether required methods exist, normalization path selected, and
names of missing required methods only. Do not dump all runtime object properties.

Update `DEVELOPMENT.md` to explicitly prohibit full RPC-result serialization and raw save
paths in routine logs. Document the analyzer rule IDs and how to inspect the JSON output.

RED cases:

- summaries contain status/reason/game needed to diagnose behavior;
- nested file/registry/path payloads and raw JSON are absent;
- summary length is bounded under an adversarial oversized message;
- BrowserView diagnostics remain sufficient to identify normalization choice and missing
  methods but omit arbitrary properties;
- analyzer flags the old synthetic payload fixture and accepts the new summary fixture.

Narrow commands:

```bash
./run.sh pnpm run test:unit -- src/controllers/gameLifecycleController.logging.test.ts src/surfaces/autoSyncStatusBrowserView.test.ts
./run.sh uv run pytest tests/test_analyze_plugin_logs.py
```

### 8. Update durable documentation and session evidence

Update:

- `README.md` only if the user-visible launch-gate behavior or troubleshooting instructions
  need clarification;
- `DEVELOPMENT.md` with the reusable pull/analyze workflow and diagnostic contract;
- `docs/specs/custom_status_bar_ui.md` so its launch-gate section states that tracking
  bootstrap and renewable leases protect cold startup and conflict waits;
- a new concrete JSON session record under `docs/agent_conversations/` with date, objective,
  exact files, tests, RED evidence, decisions, commands, and results.

Do not claim on-device success in documentation before the deferred hardware scenario is run.
Record it as pending with the expected evidence.

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

### Focused RED/GREEN verification

Run each task's narrow commands immediately after writing its tests to capture RED, then again
after implementation for GREEN. The final local verification ladder is:

```bash
./run.sh uv run pytest tests/test_pull_plugin_logs.py tests/test_analyze_plugin_logs.py
./run.sh uv run pytest tests/test_watchdog.py tests/test_service.py tests/test_main.py tests/test_main_rpc.py tests/test_compatibility.py tests/test_watcher.py
./run.sh pnpm run test:unit -- src/runtime/startupHydration.test.ts src/state/ludusaviState.test.tsx src/controllers/launchGateLease.test.ts src/controllers/gameLifecycleController.test.ts src/controllers/gameLifecycleController.logging.test.ts src/controllers/syncthingMonitor.handoffCleanup.test.ts src/controllers/syncthingMonitor.initialization.test.ts src/surfaces/autoSyncStatusBrowserView.test.ts
./run.sh uv run python scripts/analyze_plugin_logs.py tests/fixtures/plugin_logs/clean.log
./run.sh uv run python scripts/analyze_plugin_logs.py --format json tests/fixtures/plugin_logs
```

Assertions for the analyzer fixture set:

- `clean.log` returns exit 0 and no error-severity findings;
- `cold-tracking-conflict.log` reports
  `launch_gate.backend_match_after_untracked_start`;
- `watchdog-resume-before-resolution.log` reports
  `launch_gate.resume_before_resolution`;
- `syncthing-ttl-expiry.log` reports `syncthing.watch_ttl_expired`;
- `--strict` returns 1 for fixtures containing error-severity launch-gate invariants;
- text and JSON outputs contain the same stable rule IDs, file names, line numbers, severities,
  and occurrence counts.

Then run the generated orchestration quality gate exactly as the contract requires:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git diff --check
git status --short
```

`run-quality-gates` must complete frontend unit tests, typecheck, build, Ruff fix/format, `ty`,
and the full Pytest suite. Inspect `git status --short` after the gate because formatters are
allowed to modify implementation files; commit all in-scope changes and leave the tree clean
before marking the round complete.

### Acceptance matrix

| Scenario | Required result |
| --- | --- |
| Plugin initializes and QAM is never opened | Settings and tracking hydration settle before the first lifecycle classification. |
| Tracking refresh fails, valid game PID launches | Process is conservatively paused, backend check determines match, and unmatched games are promptly released. |
| Recognized game has ambiguous save recency | Conflict modal is shown while a valid pause lease remains active. |
| User waits at least 60 seconds in conflict modal | Lease renewals continue; no watchdog resume and no backup/restore occurs before selection. |
| User selects local or backup version | Selected operation completes while paused, then the lease is released and process resumes once. |
| Frontend is destroyed during a paused launch | Renewals stop and backend resumes after lease TTL or during backend shutdown; no indefinite suspension. |
| New pre-game watch follows prior post-game watch | Older watch is stopped even though its phase differs; it never reaches backend TTL. |
| Successful backup produces a large nested result | Log contains a bounded summary and no save paths or serialized file map. |
| Analyzer scans malformed/mixed-version logs | Scan completes, counts parse failures, and still reports recognized invariant violations. |

### Deferred Steam Deck verification

Hardware verification is intentionally deferred until the branch passes review, is finalized
onto `dev`, and a development prerelease is built through the existing project workflow. Do
not publish a release, push a tag, or dispatch a release solely from this plan; those actions
require explicit user instruction.

When a build is installed on the Steam Deck:

1. Restart/reload the plugin and do **not** open its QAM content.
2. Launch a Ludusavi-managed game with a deliberately ambiguous local/backup state.
3. Confirm the game is paused and the conflict UI appears.
4. Leave the conflict UI unanswered for at least 60 seconds. Confirm the game remains paused
   and no save mutation starts.
5. Choose each resolution in separate safe test runs. Confirm backup/restore completes before
   the game resumes and that the resulting save is correct.
6. During a post-game Syncthing handoff, reload the frontend or immediately relaunch the same
   game. Confirm the previous watch is explicitly stopped and no 180-second TTL warning
   appears.
7. Pull the new logs and analyze them:

   ```bash
   ./run.sh uv run python scripts/pull_plugin_logs.py --host steamdeck
   ./run.sh uv run python scripts/analyze_plugin_logs.py --strict /tmp/sdh_ludusavi/steamdeck/logs
   ```

8. The new test window must contain no `resume_before_resolution`, no actionable backend match
   after an authoritative `tracked=false`, no Syncthing TTL expiry, no `ERROR`/`CRITICAL` or
   traceback, and no oversized/raw operation payload. Preserve the pulled logs only under
   `/tmp/sdh_ludusavi/steamdeck/logs` as review evidence.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished launch-gate-log-regression
```

This writes:

```text
/tmp/sdh_ludusavi/launch-gate-log-regression_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer launch-gate-log-regression`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/launch-gate-log-regression-review-*.md
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
   scripts/orchestration/clear-finished launch-gate-log-regression
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
   git add docs/review/launch-gate-log-regression-review-*.md
   git commit -m "docs(review): record launch-gate-log-regression review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished launch-gate-log-regression
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer launch-gate-log-regression` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed launch-gate-log-regression
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize launch-gate-log-regression
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/launch-gate-log-regression_finalized
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
scripts/orchestration/finalize launch-gate-log-regression
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/launch-gate-log-regression_finished
/tmp/sdh_ludusavi/launch-gate-log-regression_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
