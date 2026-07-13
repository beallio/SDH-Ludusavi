# Review — launch-gate-log-regression (round 02)

Branch: `feat/launch-gate-log-regression`
Reviewed against: `docs/plans/2026-07-12_launch-gate-log-regression.md`

## Verdict

The correction commit fixes the remote log filename/SSH-alias contract, makes launch
classification honest, invokes the real backend lifecycle checks, serializes frontend
renewal requests, and moves backend lease inspection under its lock. It is still not safe
to approve. The lease-loss path can leave a process suspended and permits lifecycle work to
continue after protection is lost; a failed backend resume discards the only record that
would let watchdog/shutdown retry; and most of round 01's required types, tests, diagnostics,
fixtures, and audit corrections were not attempted.

## Gate status

- Working tree was clean at review start and the round marker matched `e5c60b5`.
- Focused Python selection: all 190 tests passed, but the command exited 1 because running a
  partial suite produced 54.77% aggregate coverage below the repository-wide 83% threshold.
  This is expected for that selection and is not treated as an implementation-test failure.
- Real saved-log analyzer: exit 0; 3,401 lines parsed; it now reports three historical
  `launch_gate.resume_before_resolution` incidents, one
  `launch_gate.backend_match_after_untracked_start` incident, one
  `syncthing.watch_ttl_expired` incident, and bounded-payload warnings.
- No full quality-gate rerun is needed before returning this semantic correction round: the
  critical findings below are directly observable in source and missing tests/files.

## Required changes

### 1. Make lease loss fail safe and observable to the lifecycle controller

`src/controllers/launchGateLease.ts` now serializes renewals, but on a failed renewal or
exception it sets `isActive=false` and stops. It neither resumes the process nor tells the
controller that protection was lost. Because `release()` immediately returns when
`isActive=false`, even the caller cannot perform the missing best-effort resume afterward.
The lifecycle handler therefore continues toward restore/conflict/backup while the backend
may independently resume the game, and a failed frontend renewal can leave the process
suspended until watchdog expiry.

Required:

- separate "renewing", "lost", and "released/resume-attempted" state so terminal renewal
  loss stops timers but does not suppress the one best-effort resume;
- expose a one-shot loss callback/promise carrying the reason and notify it exactly once;
- on renewal failure/exception, stop scheduling, notify the controller, and issue one
  best-effort resume; keep explicit `release()` idempotent across all states;
- validate a successful pause before constructing a handle: nonblank `lease_id`, positive
  finite TTL, and a success discriminator are mandatory;
- use the backend TTL to schedule renewal with safety margin rather than an unrelated fixed
  interval, while preserving non-overlap;
- retain all active handles in controller scope, remove them after release, and release them
  from `dispose()` before/while disposing other lifecycle resources;
- race check/restore/conflict waits against lease loss. After loss, do not start the next
  mutation RPC or treat the result as safely launch-gated; clean up speculative watches and
  surface a bounded failure;
- add fake-timer/controller tests for serialized slow renewal, repeated renewal during a
  60-second unresolved conflict with no resume, resolution with one resume, renewal failure
  and exception with one loss notification/resume, no mutation after loss, dismount cleanup,
  invalid lease metadata, and idempotent release.

Do not keep the controller's `rpc as any` lease construction. Model and use the public RPC
contract.

### 2. Preserve backend recovery ownership when resume signaling fails

`ProcessWatchdog.resume` now pops the lease before `_send_signal_tree(SIGCONT)`. If signaling
fails, the method returns `failed` after permanently forgetting a process that may still be
stopped. `resume_all`, plugin shutdown, and the watchdog can no longer retry it. The updated
test explicitly accepts this unsafe behavior.

Required:

- ensure a successful resume removes only the exact lease instance that was signaled;
- if signaling fails, retain that exact tracked lease so watchdog/shutdown can retry;
- prevent a stale resume from removing a concurrently installed replacement lease;
- retain PID identity checks without allowing identity-mismatch cleanup to remove a newer
  lease;
- add deterministic stale renew/resume/re-pause tests covering both successful and failed
  SIGCONT paths, including the retry after failure;
- avoid holding the state lock across external logging or signaling unless the locking
  design proves those calls cannot re-enter or block lease operations.

Round 01 also required direct `Plugin.renew_game_process_pause` RPC coverage and
compatibility/static coverage. `tests/test_main_rpc.py` and `tests/test_compatibility.py`
remain unchanged; add those tests.

### 3. Finish the real-log analyzer contract with incident-scoped correlation and fixtures

The correction now recognizes several real messages and successfully finds historical
early-resume, tracking, TTL, and raw-payload evidence. That is meaningful progress, but the
implementation still correlates through global `last_seen_app` and all previously resumed
PIDs. Interleaved games/files can associate an action with the wrong start or pause, and the
backend-result regular expression recognizes only a subset of the real result vocabulary.
For example, real matched results can be `status=needed` or `status=skipped` with reasons
such as `local_current`; `unmatched_game` is a reason, not a status. The lease-expiration
rule searches `lease expired for PID`, while the backend emits `suspended for ... (lease
expired). Resuming automatically.` The fixture files were not updated, and the tests added
only missing-input coverage, so field behavior remains unprotected.

Required:

- parse the lifecycle result JSON and classify backend recognition from status/reason/
  operation semantics rather than a partial status regex;
- key app/check incidents by app ID where present and bounded event order; key pause/resume/
  action incidents by PID plus the associated lifecycle/game window; reset state across
  independent files and completed incidents;
- recognize both lease-expired and absolute-ceiling watchdog reasons emitted by the backend;
- replace the fictional fixtures with sanitized real-syntax excerpts and add one regression
  proving tracking mismatch, early resume, lease expiry, Syncthing TTL, raw payload, and the
  required intentional-skip/status false-positive exclusions;
- make deduplication incident-based with meaningful occurrence counts. Slicing the first 50
  evidence characters can collapse unrelated incidents and does not define an occurrence;
- do not blanket-suppress every ERROR line containing `timeout` or `skipped`; suppress only
  the known status/source patterns so real errors retain diagnostics.

Record the real saved-log analyzer command and detected rule counts in the final audit.

### 4. Correct public result types and make lifecycle summaries structurally/path safe

`src/types/index.ts` still requires `lease_id` and `lease_ttl_seconds` on failed pause results
and requires a `lease_id` that successful renew responses do not return. Convert pause and
renew responses into truthful discriminated unions and use them through the RPC/controller/
lease helper without `any`.

`summarizeLifecycleResult` now rejects object-valued `files`/`registry`, but it still accepts
arbitrary strings for aggregate fields, omits the top-level canonical game and real
`result.overall` aggregate shape, and only truncates path-bearing messages. It can therefore
still emit `/home/deck`, `/run/media`, or backup paths. Its tests were not changed.

Required:

- whitelist numeric aggregates from the actual result shape, plus bounded top-level
  status/operation/reason/canonical game;
- remove or redact user paths from message/game/free-form values rather than only truncating;
- add adversarial typed tests for nested files/registry/games, `result.overall`, oversized
  messages, and Deck/removable-media paths; do not use `any` to bypass the contract;
- repair the documentation around the diagnostic contract and make every project command use
  `./run.sh` (the validation block still shows direct `pnpm run build`).

### 5. Complete the missing planned tests and truthful session record

The correction did not add or modify BrowserView tests, Syncthing stop-order tests,
controller logging tests, lease helper tests, main RPC/compatibility tests, or lifecycle
summary tests. The plan-level session log still claims those tests were added and claims
`README.md` was modified, neither of which is true. It still records the wrong type-check
target and generic RED evidence. The specialized lease record still says `setInterval` even
though the correction uses `setTimeout`.

Required:

- add all missing task 4-7 coverage from round 01, especially an awaited Syncthing stop
  before next allocation, BrowserView bounded/missing-method diagnostics, controller logging,
  and lease-loss/long-conflict behavior;
- correct `docs/agent_conversations/2026-07-13_launch-gate-log-regression.json` to list only
  files/tests actually changed, exact RED commands/failures by behavior group, the official
  `./run.sh uv run ty check py_modules/sdh_ludusavi/` command, final gate counts, and saved-log
  analyzer counts;
- remove or consolidate the specialized lease session record, or make every claim accurately
  match the final implementation;
- do not claim plan completion until the promised tests exist and prove the behavior.

After corrections, run the full command ladder from round 01, including
`scripts/orchestration/run-quality-gates`, review-note deletion protection,
`git diff --check`, and a clean-tree check. Commit every correction and stamp a new marker
from that clean HEAD.

STATUS: CHANGES_REQUESTED
