# Status Bar: Keep Running Statuses Visible Until Completion (with 930s Safety Ceiling)

## Context

Today the auto-sync status bar force-hides `checking` / `backing_up` / `restoring`
("running") statuses after a fixed 10 seconds. When that timer fires, a module flag
`autoSyncStatusTimedOut` is set, and any later **success or skip** result is silently
suppressed (`completeAutoSyncStatus` returns early). Failures and conflicts are always
shown. This is deliberate, documented behavior in `docs/specs/custom_status_bar_ui.md`
(line ~108: "Checking and running states auto-hide after 10 seconds. A late success
stays quiet. A late failure still shows the failure toast.").

The problem: backend operations were recently bounded at up to **900 seconds**
(`LUDUSAVI_OPERATION_TIMEOUT_SECONDS`, previews at 300s — see
`py_modules/sdh_ludusavi/constants.py`). Any backup or restore that legitimately takes
more than 10 seconds (large saves, slow storage, cloud sync) now has its status bar
vanish mid-operation, and the user never gets the "GAME SAVE UP TO DATE" confirmation.
The bar lies by omission.

**Decision (confirmed with the user):** keep the running-status bar visible while the
operation is actually running; it hides naturally when the operation's result is
published (results auto-hide after 2s as today). Replace the 10s timer with a
**stuck-bar safety ceiling of 930 000 ms (930s)** — slightly above the backend's 900s
hard bound — so the ceiling only ever fires if the frontend never receives a
completion (catastrophic case). The late-success suppression behavior is retained but
now only applies after that ceiling fires.

This changes behavior against a written spec, so the spec must be updated in the same
commit.

## Prior session context (already merged, relevant)

Commit `a2e3131` (this session) added diagnostic logging around these exact decision
points, including tests in `src/surfaces/autoSyncStatusSurface.suppression.test.ts`
that pin the 10s timeout behavior. Those tests must be updated as part of this change
— they are behavior pins, not incidental.

## Where the 10s behavior lives (exhaustive)

A repo-wide grep for `10000` / `10 seconds` confirmed the behavior exists in exactly
three places (the `10000`s in `src/settings/settingsMutationController.tsx` are
unrelated RPC timeouts — do NOT touch them):

1. `src/surfaces/autoSyncStatusSurface.tsx` line ~81 — `const hideDelay = isRunning ? 10000 : 2000;`
2. `docs/specs/custom_status_bar_ui.md` line ~108 — the spec sentence quoted above.
3. `src/surfaces/autoSyncStatusSurface.suppression.test.ts` — advances timers by
   `10000` and asserts `"10000"` appears in the schedule log message.

`docs/status_bar_game_state_flows.html` and `tests/test_status_flow_diagram.py`
contain **no** timing references — no changes needed there.

## Critical hidden edge case: stale `autoSyncStatusTimedOut` flag

In `src/surfaces/autoSyncStatusSurface.tsx`, `publishAutoSyncStatus` currently resets
the flag only for two statuses:

```ts
if (status === "backing_up" || status === "restoring") {
  autoSyncStatusTimedOut = false;
}
```

It does **not** reset on `"checking"`. Failure sequence under the new 930s ceiling:

1. Game A's backup exceeds the ceiling → `autoSyncStatusTimedOut = true`, bar hidden.
2. Game B starts → `"checking"` is published (flag still `true`).
3. Game B's check completes with a success/skip result → `completeAutoSyncStatus`
   sees the stale flag and suppresses it.
4. Nothing replaces the `"checking"` state → the "VERIFYING GAME SAVE" bar now sits
   on screen for up to 930s.

Under the old 10s timer this self-healed in 10s; under a 930s ceiling it is a real
bug. **The fix must reset the flag for all running statuses**, using the existing
helper `isLudusaviRunningStatus` (already imported into `autoSyncStatusSurface.tsx`
from `./autoSyncStatusRenderer`; it returns true for `checking`, `backing_up`,
`restoring`). This edge case gets its own regression test (Test C below).

## Project protocol requirements (mandatory)

This repo's `CLAUDE.md` enforces a strict workflow. The implementing agent MUST:

1. Output the `AGENT_PROTOCOL_HANDSHAKE` block after verifying `pwd`, `ls`,
   `git status`, and dependencies (`pyproject.toml`, `uv.lock` exist; wrapper is
   `./run.sh`; cache root `/tmp/sdh_ludusavi`).
2. This plan already lives at `docs/plans/status_bar_running_visibility.md`; include
   it in the final commit.
3. Follow strict TDD: write/modify the tests first, run them, confirm the new ones
   FAIL, then implement, then confirm green.
4. Use `./run.sh` for all Python tooling. Frontend tooling runs via `pnpm` directly.
5. Work on the `dev` branch (matches existing repo practice; `git status` should be
   clean before starting — if not, stop and report).
6. Write a session log JSON to `docs/agent_conversations/` (see step 7).
7. Single atomic commit, Conventional Commits format (see step 8).

---

## Step 1 — RED: update and extend the frontend tests

File: `src/surfaces/autoSyncStatusSurface.suppression.test.ts`

This file already exists with hoisted `logMock`, mocked `@decky/api`, `@decky/ui`,
`../utils/logging`, and `./autoSyncStatusBrowserView`, plus a `freshSurface()` helper
that does `vi.resetModules()` + dynamic import. Keep all of that infrastructure.

### 1a. Import the new constant

Add to the imports (static import is fine — it's a primitive constant, identical
across module re-imports):

```ts
import { RUNNING_STATUS_HIDE_CEILING_MS } from "./autoSyncStatusSurface";
```

Note: this import will fail to resolve until Step 2 adds the export. For the RED run,
that is an acceptable failure mode (the whole file errors = tests fail). If you prefer
clean RED assertions, define `const RUNNING_STATUS_HIDE_CEILING_MS = 930000;` locally
in the test instead and skip the import; either is fine, but the import is preferred
so the test cannot drift from the implementation.

### 1b. Update the two existing timeout tests

- Replace both `await vi.advanceTimersByTimeAsync(10000);` with
  `await vi.advanceTimersByTimeAsync(RUNNING_STATUS_HIDE_CEILING_MS);`
- In the test `"logs the auto-hide schedule at debug level"`, replace
  `message.includes("10000")` with
  `message.includes(String(RUNNING_STATUS_HIDE_CEILING_MS))`.

### 1c. Add three new tests (these provide the RED signal)

Use the existing patterns: `freshSurface()`, `loggedMessages()`, fake timers.
`logAutoSyncStatusChange` in the surface emits info messages beginning with
`"Status update: "` that include `status=<kind>` and `visible=<bool>` — assert
against those.

**Test A — running status survives past the old 10s timeout:**

```ts
it("keeps a running status visible well past the old 10s timeout", async () => {
  const surface = await freshSurface();
  surface.publishAutoSyncStatus("backing_up", {
    source: "lifecycle_exit", gameName: "Hades", appID: "1145300", tracked: true,
  });
  logMock.mockClear();

  await vi.advanceTimersByTimeAsync(60000); // 1 minute: > 10s, < ceiling

  const messages = loggedMessages();
  expect(messages.some((m) => m.includes("timed out"))).toBe(false);
  expect(messages.some((m) => m.includes("visible=false"))).toBe(false);
});
```

**Test B — completion before the ceiling shows the final result:**

```ts
it("publishes the final result when the operation completes before the ceiling", async () => {
  const surface = await freshSurface();
  surface.publishAutoSyncStatus("backing_up", {
    source: "lifecycle_exit", gameName: "Hades", appID: "1145300", tracked: true,
  });
  await vi.advanceTimersByTimeAsync(60000);
  logMock.mockClear();

  surface.completeAutoSyncStatus(
    { status: "backed_up", game: "Hades" },
    { gameName: "Hades", appID: "1145300", tracked: true },
  );

  const messages = loggedMessages();
  expect(messages.some((m) => m.includes("Status update:") && m.includes("status=has_backup"))).toBe(true);
  expect(messages.some((m) => m.includes("suppressed"))).toBe(false);
});
```

**Test C — regression for the stale-suppression edge case:**

```ts
it("clears a previous timeout suppression when a new running status is published", async () => {
  const surface = await freshSurface();
  // Game A: backup exceeds the ceiling -> timedOut flag set
  surface.publishAutoSyncStatus("backing_up", {
    source: "lifecycle_exit", gameName: "GameA", appID: "1", tracked: true,
  });
  await vi.advanceTimersByTimeAsync(RUNNING_STATUS_HIDE_CEILING_MS);

  // Game B: new lifecycle publishes "checking", which must reset the flag
  surface.publishAutoSyncStatus("checking", {
    source: "lifecycle_start", gameName: "GameB", appID: "2", tracked: true,
  });
  logMock.mockClear();

  surface.completeAutoSyncStatus(
    { status: "backed_up", game: "GameB" },
    { gameName: "GameB", appID: "2", tracked: true },
  );

  const messages = loggedMessages();
  expect(messages.some((m) => m.includes("suppressed"))).toBe(false);
  expect(messages.some((m) => m.includes("Status update:") && m.includes("status=has_backup"))).toBe(true);
});
```

### 1d. Confirm RED

```bash
pnpm vitest run src/surfaces/autoSyncStatusSurface.suppression.test.ts
```

Expected: Tests A, B, C fail (under current code the 10s timer fires inside the 60s
advance, producing "timed out" logs and suppression). If the constant import errors
the whole file, that is also RED. Do NOT proceed until you have seen the failures.

## Step 2 — GREEN: implement in `src/surfaces/autoSyncStatusSurface.tsx`

Three precise edits. Current code references are from the file as of commit
`a2e3131`.

### 2a. Add exported constants near the top of the module (after the imports,
near the existing module-level state around line ~15):

```ts
// Backend operations are hard-bounded at 900s (LUDUSAVI_OPERATION_TIMEOUT_SECONDS in
// py_modules/sdh_ludusavi/constants.py). Running statuses hide when their result is
// published; this ceiling only fires if the frontend never hears back.
export const RUNNING_STATUS_HIDE_CEILING_MS = 930000;
export const RESULT_HIDE_DELAY_MS = 2000;
```

### 2b. In `scheduleAutoSyncStatusHide`, replace the literals:

Current:
```ts
const hideDelay = isRunning ? 10000 : 2000;
```
New:
```ts
const hideDelay = isRunning ? RUNNING_STATUS_HIDE_CEILING_MS : RESULT_HIDE_DELAY_MS;
```

Leave everything else in this function as-is — including the debug "Auto-hide
scheduled in ${hideDelay}ms" log and the info "Status bar timed out after
${hideDelay}ms … final operation result will not be displayed" log inside the timeout
callback. Their messages automatically reflect the new value.

### 2c. In `publishAutoSyncStatus`, widen the flag reset:

Current:
```ts
if (status === "backing_up" || status === "restoring") {
  autoSyncStatusTimedOut = false;
}
```
New:
```ts
if (isLudusaviRunningStatus(status)) {
  autoSyncStatusTimedOut = false;
}
```

`isLudusaviRunningStatus` is already imported in this file from
`./autoSyncStatusRenderer` — do not add a new import.

### 2d. Confirm GREEN

```bash
pnpm vitest run src/surfaces/autoSyncStatusSurface.suppression.test.ts
```
All tests in the file must pass.

## Step 3 — Update the spec

File: `docs/specs/custom_status_bar_ui.md`, line ~108.

Replace:
```
Checking and running states auto-hide after 10 seconds. A late success stays quiet. A
late failure still shows the failure toast.
```
With:
```
Checking and running states stay visible while their operation runs and are replaced
when the operation's result is published. A stuck-bar safety ceiling force-hides them
after 930 seconds (just above the backend's 900-second operation bound), and only if
that ceiling fires does a late success stay quiet. A late failure always shows the
failure toast. Publishing any new running status clears a previous ceiling
suppression.
```

## Step 4 — Full verification (Definition of Done gates)

Run all of these; all must pass:

```bash
pnpm test                                          # vitest (all 10 files) + tsc --noEmit
./run.sh uv run ruff check . --fix                 # no Python changed, but protocol requires it
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest                             # 503+ tests; watch test_module_size_budgets
```

Notes:
- `tests/test_module_size_budgets.py` enforces line budgets (e.g.
  `gameLifecycleController.tsx` ≤ 550). `autoSyncStatusSurface.tsx` gains ~6 lines —
  if a budget assertion fails, compact the new comment block; do NOT raise budgets.
- The controller tests (`gameLifecycleController.test.ts`,
  `gameLifecycleController.logging.test.ts`) use `vi.runAllTimersAsync()`, which
  drains the new 930s fake timer instantly — no changes expected there. If any fail,
  investigate; do not blindly bump timer advances.

## Step 5 — README check

README documents behavior/usage. Grep README.md for status-bar timing claims
(`grep -in "10 second\|status bar" README.md`). A prior repo-wide grep found no 10s
references in README, so no edit is expected — but verify, and update if a claim
exists.

## Step 6 — Session log

Create `docs/agent_conversations/2026-06-10_status_bar_running_visibility.json` with
the repo's established shape (see
`docs/agent_conversations/2026-06-10_diagnostic_logging_improvements.json` as the
template): keys `date`, `task_objective`, `files_modified`, `tests_added`,
`design_decisions`, `results`. Design decisions must record: ceiling=930s chosen to
match the backend 900s bound (user decision), suppression retained but ceiling-only,
and the stale-flag reset widened to all running statuses to fix the
checking-suppression edge case.

## Step 7 — Commit (single atomic commit on `dev`)

Stage exactly: `src/surfaces/autoSyncStatusSurface.tsx`,
`src/surfaces/autoSyncStatusSurface.suppression.test.ts`,
`docs/specs/custom_status_bar_ui.md`,
`docs/plans/status_bar_running_visibility.md`,
`docs/agent_conversations/2026-06-10_status_bar_running_visibility.json`.

Commit message:

```
feat(status): keep running status bar visible until operation completes

The bar previously force-hid checking/backing_up/restoring after a fixed
10s and suppressed the eventual success, so any backup or restore longer
than 10s ended with no on-screen confirmation. Backend operations are
bounded at 900s, so the timer now acts purely as a stuck-bar safety
ceiling at 930s; the bar hides when the operation result is published,
as it always did for sub-10s operations.

Also reset the timeout-suppression flag on every running-status publish
(including "checking"): under a long ceiling, a stale flag from a prior
game's timed-out operation would suppress the next game's result and
strand the VERIFYING bar on screen.

Spec updated accordingly (docs/specs/custom_status_bar_ui.md).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

The pre-commit hook re-runs all gates and rebuilds the plugin zip; "Steam Deck not
reachable, skipping push" is normal and not an error.

## Explicitly out of scope

- Do not change the 2s result auto-hide, the Syncthing status lifecycle
  (`shouldAutoHideStatus` exclusions), the epoch guard, the pre-RPC publish gating,
  or anything in `src/settings/settingsMutationController.tsx`.
- Do not change backend Python code; this is frontend + docs only.

## Known accepted trade-off (do not "fix")

With a 930s ceiling, a genuinely wedged check during game launch could keep the
"VERIFYING GAME SAVE" strip overlaying gameplay for up to ~5 minutes (the backend
preview bound) instead of 10s. The user accepted this: checks normally complete in
seconds, the backend bound guarantees resolution, and a new game launch replaces the
bar via the epoch mechanism.
