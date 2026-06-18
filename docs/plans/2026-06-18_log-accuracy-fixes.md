# Fix Diagnostic Log Noise and Accuracy

TITLE: Fix Diagnostic Log Noise and Accuracy
SLUG: log-accuracy-fixes
PLAN_PATH: docs/plans/2026-06-18_log-accuracy-fixes.md
BRANCH: feat/log-accuracy-fixes

## Context

A review of recent Steam Deck logs (`/tmp/sdh_ludusavi/steamdeck-logs/`) confirmed the
recent autosync/logging fixes work, but surfaced three diagnostic-accuracy defects. They
are independent and span both the TypeScript frontend and the Python backend. None changes
user-visible sync behavior; all three make the logs honest and quieter so real problems are
easier to spot.

- **Item A — false `[ERROR]` on the pre-game Syncthing watch.** When a game launch resolves
  to `local_current` (nothing to download), the pre-game watch is *intentionally retained*
  (`retainPreGameWatch = true` in `gameLifecycleController.tsx`) so an incoming peer push
  during play can still be detected. When no push arrives, the watch hits its 120s cap and is
  currently torn down through `handlePollFailure`, which logs at `error`
  (`watch_duration_timeout`). For a pre-game watch this is the normal "no incoming sync"
  outcome, not a failure. Observed in `2026-06-18 14.42.25.log` lines 104–105.
- **Item B — process identity reports the wrong user.** `service.py` logs
  `uid=1000, euid=1000, user=root`. `getpass.getuser()` reads `$USER`/`$LOGNAME` (stale
  `root`) instead of resolving the name for the actual runtime uid (`deck`, uid 1000).
- **Item C — `[WARNING]` for a focused-but-untracked game.** Focusing any Steam game that
  has no Ludusavi backup entry logs `QAM current game not selected` at `warning`
  (`steam.ts` `logCurrentGameNoMatch`). That is the expected state for most games, so the
  warning is noise. Observed in `2026-06-18 14.42.25.log` lines 171/179/189 (Mad Max).

## Combine vs. separate (commit strategy)

All three items share one branch (`feat/log-accuracy-fixes`) and this one plan, but they are
unrelated behavior changes touching different files and different concerns. Per the repo
Atomic Commit Policy they must be **three separate commits**, each pairing its code change
with its own test (red → green). Do **not** squash them into one commit.

- Commit 0 (docs): ensure `PLAN_PATH` is committed on the branch before implementation code.
- Commit 1 (Item A): `fix(syncthing): stop logging pre-game watch timeout as an error`
- Commit 2 (Item B): `fix(logging): report runtime user identity from uid, not $USER`
- Commit 3 (Item C): `refactor(ui): log focused-but-untracked QAM game at debug, not warning`

Items A and C are both frontend TypeScript but live in different files (`syncthingMonitor.ts`
vs `steam.ts`) and address different concerns — keep them as separate commits, not combined.
Item B is backend Python and is necessarily separate. Within each item, the code and its test
ship in the same commit.

Suggested implementation order: B (smallest, isolated) → C → A (largest). Order is not
load-bearing; only the per-item commit separation is.

---

## Item A — Pre-game watch timeout must not log `[ERROR]`

### Files
- Modify: `src/controllers/syncthingMonitor.ts`
- Test: `src/controllers/syncthingMonitor.failures.test.ts`

### Current behavior (read first)
- `pollOnce` (`syncthingMonitor.ts` ~line 404). The duration-cap block (~409–418):
  ```ts
  const timeoutStartedAt =
    context.phase === "pre_game" ? context.startedAt : context.handoffActivatedAt;
  if (timeoutStartedAt !== null && Date.now() - timeoutStartedAt > MAX_WATCH_DURATION_MS) {
    log("info", `Syncthing watch ${context.watchID} hit the active 120s timeout, stopping.`);
    this.handlePollFailure(context, "watch_duration_timeout");
    return;
  }
  ```
- `handlePollFailure` (~453–469) unconditionally `log("error", ...)`, then dispatches
  `{ type: "poll_failed" }` (terminal + `stopWatch`) and calls `stopWatchSafe`.
- Confirm the design intent before touching: in `gameLifecycleController.tsx`, the
  `local_current`/skipped path sets `retainPreGameWatch = true` (~line 356) and the `finally`
  block (~368) only cancels the watch when it is NOT retained. So the lingering pre-game watch
  is intentional — **do not** cancel it early; only fix the log severity of its eventual
  timeout. The `poll_failed` machine transition does not publish any status for `pre_game`
  (publish is gated on `state.phase === "post_game"`), so this is a log-only issue.

### Required outcome
- A `pre_game` watch that reaches `MAX_WATCH_DURATION_MS` stops cleanly (reaches terminal
  state, `stopWatchSafe` invoked) and emits **no** `[ERROR]` log. It emits exactly one
  informational log describing the benign stop (use `info` or `debug`; wording must not call
  it a "failure", e.g. `Syncthing pre-game watch reached max duration with no incoming sync;
  stopping: generation=...`).
- A `post_game` watch that reaches its (handoff-relative) duration cap keeps the existing
  behavior: one `[ERROR]` `Syncthing poll failure: ... message=watch_duration_timeout`.

### Recommended implementation
Keep the terminal-stop dispatch DRY. Add an optional severity parameter to `handlePollFailure`:
```ts
private handlePollFailure(
  context: WatchContext,
  message: string,
  reason?: string,
  severity: "error" | "info" = "error",
): void {
  if (context.cancelled) return;
  log(severity, `Syncthing poll failure: generation=${context.generation} message=${message}`);
  // ...unchanged dispatch/stop tail...
}
```
Then phase-branch the duration-cap block in `pollOnce` so the pre-game path logs the benign
info line and passes `severity: "info"` (or routes through a small shared terminal-stop helper
without the "poll failure" wording — implementer's choice, as long as no `error` is emitted and
the watch still stops). Post-game continues to call `handlePollFailure(context,
"watch_duration_timeout")` with the default `error` severity. Avoid emitting two redundant log
lines for the pre-game case.

### Test (add to `syncthingMonitor.failures.test.ts`)
The suite already uses `vi.useFakeTimers()` and stubs `globalThis.window` (vitest fake timers
also mock `Date.now`, which the duration check relies on). Add two tests:
1. **pre_game timeout is benign**: mock `startWatch` → `{ status: "watching", watch_id: "w1", ... }`,
   `pollWatch` → a valid idle sample (`{ status: "idle", timestamp_unix: 1000 }`, then repeated
   idle samples) so the watch initializes and keeps polling. Spy on logging severity — either
   `vi.spyOn(console, "error")` / `vi.spyOn(console, "info")` (as `logging.test.ts` does) or
   mock `../utils/logging` (`vi.mock("../utils/logging", () => ({ log: vi.fn(), mapSyncthingFailureReason: (r:any)=>null }))`)
   and assert `log` is never called with `"error"`. Start a `"pre_game"` watch, then
   `await vi.advanceTimersByTimeAsync(MAX + a few poll intervals)` (e.g. `121_000`) to drive the
   duration branch. Assert: no `error`-level log; `mockRpc.stopWatch` was called (watch stopped).
2. **post_game timeout still errors** (regression guard): start a `"post_game"` watch, activate
   handoff, advance past the cap, assert an `error`-level log containing `watch_duration_timeout`
   is emitted. (If a comparable assertion already exists, extend it rather than duplicating.)

Use `import { MAX_WATCH_DURATION_MS }` only if it is exported; it is currently module-private —
do not export it solely for the test, just use the literal `121_000` in the test with a comment.

### Verify
```bash
./run.sh npm run test -- syncthingMonitor.failures
```

---

## Item B — Report runtime user identity from uid, not `$USER`

### Files
- Modify: `py_modules/sdh_ludusavi/service.py` (~lines 140–143)
- Test: `tests/test_process_identity.py` (new)

### Change
Replace the inline `getpass.getuser()` identity string with a module-level pure helper that
resolves the username from the actual runtime uid:
```python
def _resolve_process_identity() -> str:
    uid = os.getuid()
    euid = os.geteuid()
    try:
        import pwd

        user = pwd.getpwuid(uid).pw_name
    except (KeyError, ImportError):
        import getpass

        try:
            user = getpass.getuser()
        except Exception:
            user = "unknown"
    return f"uid={uid}, euid={euid}, user={user}"
```
In `__init__`, replace the existing three identity lines (the `import getpass`, the `identity =`
f-string, and the `self.log("debug", ...)` call) with:
```python
self.log("debug", f"Process identity: {_resolve_process_identity()}", "init")
```
Keep it at `debug` level. Place `_resolve_process_identity` near the other module-level helpers
in `service.py` (e.g. beside `_coerce_notification_settings`). `os` is already imported at the
top; do not add a top-level `getpass`/`pwd` import — keep them guarded inside the helper.

### Test (`tests/test_process_identity.py`)
Make it deterministic and independent of the CI user:
```python
from sdh_ludusavi import service


def test_identity_resolves_user_from_uid_not_env(monkeypatch):
    class _Pw:
        pw_name = "deck"

    monkeypatch.setattr(service.os, "getuid", lambda: 1000)
    monkeypatch.setattr(service.os, "geteuid", lambda: 1000)
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("LOGNAME", "root")

    import pwd
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _Pw())

    result = service._resolve_process_identity()
    assert result == "uid=1000, euid=1000, user=deck"
    assert "root" not in result
```
Add a second test that falls back gracefully when `pwd.getpwuid` raises `KeyError` (asserts the
string is still well-formed and contains `user=`).

### Verify
```bash
./run.sh uv run pytest tests/test_process_identity.py
```

---

## Item C — Log focused-but-untracked QAM game at `debug`, not `warning`

### Files
- Modify: `src/utils/steam.ts` (`logCurrentGameNoMatch`, ~line 399)
- Test: `src/utils/steam.test.ts` (new — no test file currently exists for this module)

### Change
`logCurrentGameNoMatch` currently chooses severity `session ? "warning" : "debug"`. The
`session`-present branch fires for any focused game absent from the Ludusavi tracked list,
which is the normal state for most games. The function has no trackedness context to
distinguish a genuine matching bug, and the common case is benign, so downgrade both branches
to `debug`:
```ts
export function logCurrentGameNoMatch(
  session: RunningSession | null,
  currentGames: readonly GameStatus[],
  currentAliases: Record<string, string>
) {
  log(
    "debug",
    `QAM current game not selected: context=${session ? describeSteamGameSession(session) : "none"} games=${currentGames.length} aliasKeys=${Object.keys(currentAliases).length}`,
    "qam_context",
    session?.name
  );
}
```
Leave the message text unchanged (it already carries the context).

### Test (`src/utils/steam.test.ts`)
Create a focused suite for `logCurrentGameNoMatch`. Mock `@decky/api`
(`vi.mock("@decky/api", () => ({ callable: () => () => Promise.resolve() }))`) so `log` can
import, and either spy on `console.debug`/`console.warn` or mock `../utils/logging` to capture
the level. Assert:
- Called with a non-null `session`, it logs at `debug` (i.e. `console.warn` NOT called;
  `console.debug` called with a message containing `QAM current game not selected`).
- Called with `session = null`, it also logs at `debug`.
Construct minimal `RunningSession`/`GameStatus` fixtures from the types in `../types`; keep
`currentGames`/`currentAliases` empty or one-element.

### Verify
```bash
./run.sh npm run test -- steam
```

---

## Quality gates (run before every commit and before marking a round finished)
```bash
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
./run.sh npm run test
```
All must pass. Only the Python gates are relevant to Item B and only the TS test runner to
Items A/C, but run the full suite before declaring the round complete. Do not introduce caches
inside the repo; the wrapper redirects them to `/tmp/sdh_ludusavi`.

## Known risks / watch-outs
- **A**: Do not "fix" the lingering pre-game watch by cancelling it early — that would break
  in-gameplay incoming-sync detection. The change is log-severity only. Preserve the post-game
  error path exactly (a missing post-handoff upload confirmation is a real error).
- **A**: vitest fake timers must mock `Date.now` for the duration check to trigger; the existing
  `beforeEach` already calls `vi.useFakeTimers()`. Drive time with `advanceTimersByTimeAsync`.
- **B**: `pwd` is POSIX-only; the guarded import keeps non-Linux dev hosts working. `getpwuid`
  raises `KeyError` for unknown uids — the fallback covers that.
- **C**: Downgrading to `debug` means this line disappears unless `debug_logging` is on (it
  defaults on). That is the intended outcome — it is diagnostic noise.

## Deferred verification
Steam Deck / on-device user testing is deferred until **after** `dev` is pushed to GitHub and a
new dev release is built. Do not block finalization on hardware testing. After the dev release
is available, the next launch logs should show: no `[ERROR] ... watch_duration_timeout` for a
`local_current` launch, `user=deck` in the process-identity line, and the focused-untracked
QAM line at `[DEBUG]`.

---

## Orchestration contract (implementer instructions)

You are the implementing agent. Use the `implementer` skill. Work only on branch
`feat/log-accuracy-fixes` (branch off `dev`). Do not write your own review. Do not create or
delete files under `docs/review/`; review notes are durable audit records committed by the
orchestrator.

Paths:
- Plan: `docs/plans/2026-06-18_log-accuracy-fixes.md`
- Branch: `feat/log-accuracy-fixes`
- Round-complete marker: `/tmp/sdh_ludusavi/log-accuracy-fixes_finished`
- Finalized marker: `/tmp/sdh_ludusavi/log-accuracy-fixes_finalized`
- Review notes: `docs/review/log-accuracy-fixes-review-*.md`

Each review note ends with exactly one of:
```
STATUS: CHANGES_REQUESTED
```
or:
```
STATUS: APPROVED
```

### On completing an implementation or review round
1. Run the project quality gates (above).
2. Ensure the working tree is clean.
3. Commit all relevant changes (atomic, Conventional Commits, per the commit strategy).
4. Write the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished log-accuracy-fixes
   ```
Then either keep polling for review notes or exit cleanly. If you exit, the orchestrator
resumes you with `agy -c -p` via `scripts/orchestration/continue-implementer log-accuracy-fixes`.
On every resume, scan existing `docs/review/log-accuracy-fixes-review-*.md` notes first before
waiting for new file events.

### When a review note says `STATUS: CHANGES_REQUESTED`
1. Clear the round-complete marker:
   ```bash
   scripts/orchestration/clear-finished log-accuracy-fixes
   ```
2. Read the review note.
3. Implement every requested change.
4. Run quality gates.
5. Commit the implementation fixes.
6. Commit the review note itself if it is not already committed.
7. Recreate the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished log-accuracy-fixes
   ```
8. Keep polling for more review notes or exit cleanly for orchestrator resume.

### When a review note says `STATUS: APPROVED`
1. Confirm all review notes are committed.
2. Confirm the working tree is clean.
3. Finalize:
   ```bash
   scripts/orchestration/finalize log-accuracy-fixes
   ```
4. Confirm the finalized marker exists: `/tmp/sdh_ludusavi/log-accuracy-fixes_finalized`.
5. Stop polling and exit cleanly.

Finalization includes: commit any uncommitted review note; merge `feat/log-accuracy-fixes` into
`dev`; clean up the working branch; push `dev` to GitHub; request/push a new dev release using
the project release script (`scripts/request_dev_release.sh`). Steam Deck / user testing is
deferred until after the dev push.
