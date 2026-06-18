# Review — log-accuracy-fixes (round 01)

Branch: `feat/log-accuracy-fixes`
Commit reviewed: `142c2903631ec5a46e833aa51461bdf9f302068f`
Reviewed against: `docs/plans/2026-06-18_log-accuracy-fixes.md`

## Verdict

APPROVED. All three plan items are implemented correctly, with paired tests, as three
separate atomic commits on top of the committed plan. The implementation is semantically
correct, not merely test-green.

## Items

### Item A — pre-game watch timeout must not log `[ERROR]` (`ccade22`)
- `syncthingMonitor.ts`: the duration-cap branch in `pollOnce` now phase-splits. `pre_game`
  logs a single benign `info` line (`Syncthing pre-game watch reached max duration with no
  incoming sync; stopping`) and routes through a new `stopWatchTerminally` helper; `post_game`
  keeps `handlePollFailure`, which still emits the `error` line. The terminal-stop dispatch was
  factored out of `handlePollFailure` into `stopWatchTerminally` and reused by it, so behavior
  (terminal state + `stopWatchSafe`) is identical — a clean DRY refactor, not duplication.
- Correctly does **not** cancel the retained pre-game watch early, so in-gameplay incoming-sync
  detection is preserved (the design intent flagged in the plan's risks).
- Tests added: `pre_game timeout is benign` (asserts no `error` log, watch stopped) and
  `post_game timeout still errors` (regression guard). Both use the existing fake-timer harness
  and `advanceTimersByTimeAsync(121_000)`.

### Item B — runtime user identity from uid, not `$USER` (`38470ed`)
- `service.py`: new module-level `_resolve_process_identity()` resolves the username via
  `pwd.getpwuid(os.getuid()).pw_name`, with guarded `pwd`/`getpass` imports and an `unknown`
  final fallback; the inline `getpass.getuser()` identity construction was removed and the call
  site updated. Stays at `debug` level.
- Tests added (`tests/test_process_identity.py`): asserts the resolved name comes from the uid
  (`deck`) even when `$USER`/`$LOGNAME` are `root`, and a `KeyError` fallback path.

### Item C — focused-but-untracked QAM game logs at `debug` (`142c290`)
- `steam.ts`: `logCurrentGameNoMatch` severity changed from `session ? "warning" : "debug"` to
  unconditional `"debug"`; message text unchanged.
- Tests added (`src/utils/steam.test.ts`, new file): asserts `debug` severity for both the
  session-present and session-null cases.

## Gate status

- `./run.sh uv run pytest`: 603 passed, coverage 85.95% (≥ 83% threshold).
- `./run.sh npm run test`: 202 vitest tests passed across 21 files; `tsc --noEmit` clean.
- `ruff check`/`ruff format`/`ty check` run via `run-quality-gates` — passed.
- Working tree clean; no review notes deleted.

## Prior findings

None — this is the first review round; nothing outstanding.

## Finalization instructions

Proceed with finalization per the plan's orchestration contract: commit this approval note,
merge `feat/log-accuracy-fixes` into `dev`, clean up the working branch, push `dev` to GitHub,
and request/push a new dev release via `scripts/request_dev_release.sh`. Steam Deck / on-device
testing is deferred until after the dev push.

STATUS: APPROVED
