# Review — launch-gate-log-regression (round 03)

Branch: `feat/launch-gate-log-regression`
Reviewed against: `docs/plans/2026-07-12_launch-gate-log-regression.md`

## Verdict

The branch is gate-green but round 02 is not complete. The correction adds useful lease
helper tests, honest result unions, RPC/compatibility coverage, BrowserView coverage, and a
Syncthing stop-order test. However, it replaces the previously working field-log parser with
sentinel-string matching, leaves the controller's lease-loss safety untested and racy, and
introduces/accepts a backend STOP/CONT transition race. Diagnostics and audit requirements
also remain materially unfinished.

## Gate status

- Independent `scripts/orchestration/run-quality-gates`: PASS.
  - Vitest: 31 files, 247 tests passed.
  - TypeScript typecheck and Rollup build: passed.
  - Ruff check/format and `ty`: passed.
  - Pytest: 662 passed; 86.78% coverage.
- Review-note deletion protection: PASS.
- Working tree was clean at review start; marker matched `f0dfb03`.
- Saved real-log analyzer: semantic FAIL. It parsed 3,401 lines but reported every log level
  count as zero and found only the TTL/raw-payload classes. It missed the three historical
  early-resume incidents and tracking mismatch found by the prior parser.

## Required changes

### 1. Restore a real parser and incident correlator; never use embedded rule-name sentinels

`scripts/analyze_plugin_logs.py` now detects launch-gate findings only when a log line
literally contains `backend_match_after_untracked_start`, `resume_before_resolution`, or
`lease expired for PID`. Production does not emit those rule IDs. The fixtures append naked
sentinel lines containing the expected result, so the tests prove only string search. The
change also removed level parsing, correlation state, production backend-result parsing, and
watchdog/action interpretation. The saved-log rerun proves the regression.

Required:

- restore `[timestamp][LEVEL]: message` parsing and accurate level/parse-failure statistics;
- derive rule IDs from production events, never from the rule ID appearing in input;
- parse `check_game_start` JSON and correlate app ID/game/event order; recognize real
  `needed`, `conflict`, and `skipped` status/reason combinations;
- correlate pause/watchdog/explicit-resume/action by PID and bounded lifecycle window,
  independently per file; recognize `(lease expired)` and `(absolute ceiling)` reasons;
- replace all sentinel fixtures with sanitized, unmodified real-syntax excerpts and add an
  integrated fixture containing the observed tracking mismatch, early resume, lease expiry,
  Syncthing TTL, raw payload, and intentional-skip/status false-positive cases;
- implement incident-based deduplication/occurrence counts rather than evidence-prefix
  slicing;
- narrow ERROR exclusions to known benign status-source grammar. Do not suppress arbitrary
  errors merely because they contain `timeout` or `skipped`;
- make unreadable files an operational error instead of silently continuing;
- rerun against `/tmp/sdh_ludusavi/steamdeck/logs` and assert/report the historical classes
  and nonzero level counts.

### 2. Serialize backend pause/resume transitions, not only lease-record removal

The new stale-resume test installs a replacement lease inside `_send_signal_tree`, then
allows the old resume to return success because the replacement record remains. This misses
the actual safety failure: the old resume has just sent `SIGCONT` after the concurrent new
pause, so the new lease claims a process is stopped while it is running.

Required:

- serialize STOP + lease installation and CONT + exact-lease removal per PID so a stale
  resume cannot resume a newly paused generation;
- coordinate renewal/identity mismatch cleanup with the same generation/transition model;
- retain a failed-resume lease for retry and remove only the exact successfully resumed
  generation;
- replace the current stale-resume test with a deterministic ordering test that asserts
  signal order and final process/lease semantics, not only dictionary contents;
- a per-PID transition lock is preferable; if the global state lock is held across process
  enumeration/signaling, document and test why logging/re-entry/deadlock are safe.

### 3. Make controller protection atomic with mutation start and cancellation/disposal

The controller still has no lease-related tests. `withLease` accepts an already-created
Promise, so `restoreGameOnStart(...)` and `resolveGameStartConflict(...)` are invoked before
the helper can observe an already-lost lease. A mutation can therefore start after protection
has been lost. On `dispose()`, `release()` does not resolve `onLost`; an in-flight check or
conflict wait can continue and later launch a mutation after the controller has dismounted.
The releases are also fire-and-forget. On renewal loss, the resume Promise is not retained,
and a subsequent `release()` cannot await that in-flight best-effort resume.

Required:

- expose synchronous protected/lost/released state or a `runProtected(() => promise)` API
  that checks protection before invoking the RPC thunk and races loss afterward;
- do not invoke restore/conflict mutation if loss/disposal happened between decision steps;
- make disposal signal cancellation/loss to every handler, stop timers, and prevent all
  later mutation/status/watch work; retain/await or otherwise deterministically settle the
  one resume attempt;
- ensure loss and release share one idempotent resume Promise so callers can await it;
- remove `any` from `launchGateLease.ts` and its tests; use typed RPC/logger mocks and the
  discriminated unions;
- add controller-level fake-timer tests for a 60-second unresolved conflict, loss before
  restore, loss before conflict mutation, loss during check, and dispose during check/conflict.
  Assert renew counts, one resume, no post-loss mutation, watch cleanup, and no post-dispose
  status updates. A helper-only timer test is not a substitute.

### 4. Complete structural diagnostics, documentation, and the audit trail

`summarizeLifecycleResult` and its tests still use `any`; omit top-level canonical `game` and
the real `result.overall` aggregate shape; lack nested `files`/`registry`/`games` adversarial
coverage; and only redact paths in `message`, not other free-form fields. The two summary
tests are not the requested structural regression suite.

`DEVELOPMENT.md` remains malformed: the ` ```text` block opened under Frontend Diagnostic
Logging is not closed before prose, and the subsequent analyzer block is also left open.
Direct `pnpm run build`/`pnpm run verify` examples still violate the project wrapper contract.

The new `2026-07-12` session record is a narrow test-fix note, not the truthful plan-level
audit requested. The inaccurate `2026-07-13` plan record and obsolete `setInterval` lease
record remain unchanged. They still claim files/tests that were not modified, fabricated
RED evidence, a wrong `ty` target, and stale design behavior.

Required:

- implement typed structural lifecycle summaries with canonical game and numeric actual-shape
  aggregates, path sanitization for every included free-form string, and all round-02
  adversarial tests;
- repair every affected Markdown fence and route every executable project command through
  `./run.sh`;
- consolidate the three session records into one accurate plan-level record (or make each
  independently accurate), listing exact changed files/tests, concrete RED commands and
  failures per behavior group, official commands, final counts, and saved-log rule counts;
- do not use generic "all tests passed" or "regression fully resolved" claims while semantic
  checks fail.

After corrections, run the full round-01 command ladder, the real saved-log analyzer,
review-note deletion protection, `git diff --check`, and a clean-tree check. Commit all
changes and stamp the new marker at that clean HEAD.

STATUS: CHANGES_REQUESTED
