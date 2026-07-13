# Review — launch-gate-log-regression (round 01)

Branch: `feat/launch-gate-log-regression`
Reviewed against: `docs/plans/2026-07-12_launch-gate-log-regression.md`

## Verdict

The branch is test-green but is not semantically safe or plan-complete. The first-round
implementation correctly establishes startup tracking hydration, a backend lease record,
cross-phase Syncthing supersession, and bounded BrowserView diagnostics, but the cold-state
and lease-loss paths still permit incorrect or unsafe behavior. The reusable tooling is
currently trained on synthetic messages that do not match the actual logs it is meant to
analyze.

## Gate status

- `scripts/orchestration/run-quality-gates`: PASS on orchestrator rerun.
  - Vitest: 30 files, 238 tests passed.
  - TypeScript typecheck: passed.
  - Rollup build: passed.
  - Ruff check/format: passed.
  - `ty check py_modules/sdh_ludusavi/`: passed.
  - Pytest: 658 passed; 86.67% coverage.
- `scripts/orchestration/check-review-notes-not-deleted`: PASS.
- `git diff --check`: PASS.
- Working tree was clean at review start.
- Semantic/on-device-log regression review: FAIL for the findings below.

## Required changes

### 1. Make the pull helper work with the real Decky log layout and the configured SSH alias

`scripts/pull_plugin_logs.py` filters remote names with
`filename.startswith(plugin + ".log")`. The real SDH-Ludusavi directory contains files such
as `2026-07-12 09.55.50.log`, `2026-07-08 23.46.41.log`, and an older `.log.save`, so the
current command selects zero files. The implementation also rewrites the configured bookmark
to `deck@steamdeck`; the user explicitly supplied `ssh steamdeck` / `scp ... steamdeck:...`,
and the plan requires plain host-alias argv.

Required:

- select regular `*.log` and `*.log.save` entries regardless of timestamp/name prefix;
- preserve spaces safely with argv-based subprocess calls and no `shell=True`;
- invoke `ssh <host>` and use `<host>:/home/deck/homebrew/logs/<plugin>/...` for `scp`;
- handle remote-list/copy failures through return code 2 for operational/input failure;
- add tests using the real timestamp filename convention and assert the plain host alias;
- retain the `/tmp/sdh_ludusavi/<host>/logs` default and never delete existing logs.

### 2. Parse and correlate the actual production log grammar

The analyzer recognizes fictional strings such as `App launch: PID=...`,
`backend check: matched`, `watchdog resume game process`, and `syncthing TTL expired`. The
real logs use messages such as:

```text
frontend: App started: <game> (<app_id>) tracked=false
launch_gate: Paused game process tree rooted at PID <pid>
lifecycle: check_game_start result ... {"status":"conflict",...}
watchdog: Watchdog detected PID <pid> suspended for 15s ... Resuming automatically.
launch_gate: Resumed game process tree rooted at PID <pid>
backup: Kept local save ... / restore: Restored ...
sdh_ludusavi.syncthing.watcher: Syncthing watch <id> exceeded 180.0s TTL ...
```

Running the new analyzer over `/tmp/sdh_ludusavi/steamdeck/logs` found only raw-payload
warnings and missed all three observed watchdog-before-resolution incidents, the known
frontend/backend tracking mismatches, and the Syncthing TTL incident. The fixture files do
not reproduce the field format and therefore cannot prove these rules.

Required:

- parse `[timestamp][LEVEL]: message` while tolerating the older spaced variant;
- build lifecycle incidents from the real app-start/check-result/pause/watchdog/action lines;
- correlate an app start to its backend check by app ID/game/event order and a pause to its
  watchdog/explicit resume/action by PID and order;
- detect the actual `exceeded 180.0s TTL` message;
- implement and test the documented `launch_gate.lease_expired` rule;
- make unreadable/missing input return 2 instead of silently scanning nothing;
- deduplicate by incident/rule while retaining a meaningful occurrence count (the current
  filename+line key can never collapse repeated evidence);
- replace fixtures with sanitized excerpts that preserve real syntax and add a regression
  test that detects all previously observed finding classes in one representative log set;
- continue avoiding false positives from `failures_errors`, status-source `timeout`, and
  intentional skip results.

### 3. Do not fabricate conflicts or skip backend lifecycle checks when tracking hydration fails

`gameLifecycleController.tsx` currently sets `tracked=true` when tracking hydration failed,
fabricates a `status="conflict"` result without calling `checkGameStart`, and fabricates a
skipped exit without calling `checkGameExit`. This contradicts the plan and the updated spec,
which require a bounded conservative pause followed by the backend source-of-truth check.
It would show a conflict for every launched app during tracking failure, cannot distinguish
unmatched games, and disables legitimate exit backups.

Required:

- preserve `tracked` as the honest result of the frontend cache;
- derive a separate `trackingReady`/`guardCandidate` value;
- for `cold` or `failed` readiness with autosync enabled and a valid PID, pause and begin the
  speculative pre-game watch, then call the real backend `checkGameStart`;
- release/cancel immediately when the backend returns `unmatched_game`, disabled, or another
  silent skip;
- proceed with restore/conflict only for the backend's actionable matched result;
- always call the real exit check; tracking hydration failure must not suppress backup-on-exit;
- log `tracking_readiness` and `guard_candidate` without claiming `tracked=true`;
- replace the current tests that explicitly expect no backend call with the RED/GREEN cases
  listed in plan task 4 (cold-known, cold-unmatched, ready-untracked, failed-known, invalid PID).

### 4. Treat lease renewal loss as a data-integrity event and own leases through controller disposal

`launchGateLease.ts` clears its interval when renewal returns `failed`, but it leaves the
handle active, does not notify the lifecycle controller, does not resume/release immediately,
and does not prevent a later restore/backup/conflict mutation. This recreates the original
risk after the backend lease expires. Renewal calls are also scheduled with `setInterval`
without an in-flight guard, so slow RPCs can overlap. The controller keeps the handle only in
the local start-handler stack; `dispose()` cannot stop its timer or release the paused game,
so a dismounted frontend can continue renewing until the absolute ceiling.

Required:

- make lease response validation reject missing/blank lease IDs and invalid TTL metadata;
- serialize renewals so a second renewal cannot start while the first is pending;
- expose a one-shot lease-loss signal/callback/promise to the controller;
- on terminal renewal failure or exception: clear timers, mark the handle lost, notify once,
  call resume best-effort, and make `release()` remain idempotent;
- race start-check/restore/conflict waits against lease loss so no save mutation RPC starts or
  continues to the next mutation step after protection is lost;
- retain active handles at controller scope and release them during `dispose()`; do not allow
  timer renewals after dismount;
- add the planned fake-timer tests: non-overlapping renewal, 60-second unresolved conflict with
  repeated renewals/no resume, resolution-before-single-release, renewal loss preventing the
  mutation RPC, exceptions/cancellation/dismount cleanup, and idempotent release.

### 5. Make the backend lease update atomic and align public result types/tests

`ProcessWatchdog.renew_pause` reads a mutable lease under the lock, releases the lock for
identity verification, and then mutates the old object after reacquiring without confirming
that the same lease is still registered. Concurrent resume/re-pause can therefore return
`renewed` without extending the current lease; identity-mismatch cleanup can pop a newer
lease. Recheck PID+lease ID+object identity under the lock before mutation/removal.

Also correct the frontend result types: failed pause/renew results do not contain
`lease_id`/`lease_ttl_seconds`, and successful renew responses currently do not return
`lease_id`, although `RenewGameProcessPauseResult` requires it. Model success/failure as
honest discriminated unions or make fields optional only where actually absent.

Add direct RPC coverage for `Plugin.renew_game_process_pause` and compatibility/static
coverage for the new RPC surface. Add a concurrent stale-renew/re-pause regression test or an
equivalent deterministic lock/recheck unit test.

### 6. Make lifecycle summaries structurally safe, not only short in the happy-path test

`summarizeLifecycleResult` copies `result.files` and `result.registry` without checking their
types. If either is the real nested mapping, the helper reserializes the exact file/registry
payload it is supposed to exclude. Truncating `message` to 150 characters also does not
remove `/home/deck`, `/run/media`, backup paths, or other user paths. The helper omits the
top-level canonical `game` and does not extract the real aggregate shape under
`result.overall`.

Required:

- whitelist scalar fields only;
- include top-level canonical game/status/operation/reason and numeric aggregate counts/bytes
  from the actual result shape where available;
- sanitize or replace path-like content in bounded free-form messages;
- add adversarial tests with object-valued `files`/`registry`, real nested
  `result.overall`/`result.games`, oversized messages, and `/home/deck`/`/run/media` paths;
- ensure neither the summary nor its tests rely on `any` to bypass the public result types.

Repair the broken Markdown fence in `DEVELOPMENT.md`: the ` ```text` block opened before
`event_name` is no longer closed before prose. Keep the structured logging example and close
the fence before the diagnostic contract.

### 7. Complete the planned behavior coverage and make the audit trail accurate

The plan explicitly required frontend stop-order/dispose tests for Syncthing, BrowserView
diagnostic tests, controller logging assertions, backend main-RPC/compatibility tests, and the
long conflict/lease-loss tests. Several are claimed in
`docs/agent_conversations/2026-07-13_launch-gate-log-regression.json` but were not added or
modified. The session log also lists `README.md` as modified when it is not in the diff,
records `./run.sh uv run ty check src/` instead of the official Python `ty` command, and uses
generic RED evidence rather than exact failing commands/results.

Required:

- add the missing tests required by tasks 4-7, including an assertion that
  `await syncthingMonitor.stop()` completes before the next watch allocation;
- add BrowserView tests proving bounded capability/missing-method logging without property
  inventories;
- update any frontend static source aggregation if the new modules need inclusion;
- correct the session log to list only actual files/tests and exact official commands;
- record concrete RED evidence per behavior group and the final verified counts;
- remove or consolidate the duplicate specialized session log if it cannot be kept fully
  accurate; one truthful plan-level session record is sufficient;
- rerun the analyzer against the saved real logs and record that it now detects the historical
  tracking, early-resume, TTL, and raw-payload evidence.

After all changes, run:

```bash
./run.sh uv run pytest tests/test_pull_plugin_logs.py tests/test_analyze_plugin_logs.py
./run.sh uv run pytest tests/test_watchdog.py tests/test_service.py tests/test_main.py tests/test_main_rpc.py tests/test_compatibility.py tests/test_watcher.py
./run.sh pnpm run test:unit -- src/runtime/startupHydration.test.ts src/state/ludusaviState.test.tsx src/controllers/launchGateLease.test.ts src/controllers/gameLifecycleController.test.ts src/controllers/gameLifecycleController.logging.test.ts src/controllers/syncthingMonitor.handoffCleanup.test.ts src/controllers/syncthingMonitor.initialization.test.ts src/surfaces/autoSyncStatusBrowserView.test.ts
./run.sh uv run python scripts/analyze_plugin_logs.py --format json /tmp/sdh_ludusavi/steamdeck/logs
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git diff --check
git status --short
```

The new round-complete marker must be stamped from a clean tree after all review-note changes
and this review note are committed.

STATUS: CHANGES_REQUESTED
