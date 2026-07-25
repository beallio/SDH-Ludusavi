# Plan: Background Update Polling and Update-Available Toast (background-update-polling-toast)

## Context

### Problem 1 — update checks only run while the QAM panel is open

The plugin never checks for updates in the background. There is no timer anywhere:
`src/controllers/pluginUpdateController.tsx` contains only two one-shot `setTimeout`s (a
60s check-timeout guard at ~line 123 and a 3s installer-handoff race at ~line 398), and the
Python backend (`main.py`, `py_modules/sdh_ludusavi/updater.py`) is purely request/response
with no `asyncio` background task. Every update check is triggered by an effect inside
`usePluginUpdateController`, and that hook only exists while `PluginUpdateSection` is
mounted — which happens inside `LudusaviContent` (`src/components/qam/LudusaviContent.tsx`,
the `<PluginUpdateSection …/>` block near line 609). Close the QAM panel and update
checking stops entirely.

On-device logs from a Steam Deck running 0.4.2 confirm this. Every `update: check_start`
is preceded ~200ms earlier by `ui: qam_content_mounted`, and plugin loads that never open
the panel produce zero checks:

```text
2026-07-24 17.01.59.log:16  ui: plugin_initializing        <- no check
2026-07-24 17.01.59.log:31  ui: plugin_initializing        <- no check
2026-07-24 17.01.59.log:41  ui: qam_content_mounted
2026-07-24 17.01.59.log:54  update: check_start            <- only here
2026-07-24 17.04.21.log:16  ui: plugin_initializing        <- no check
2026-07-24 17.04.21.log:35  ui: qam_content_mounted
2026-07-24 17.04.21.log:48  update: check_start            <- only here
```

This directly contradicts the shipped UI copy. The toggle at
`src/components/PluginUpdateSection.tsx` line 186 reads *"Checks in the background while the
plugin is loaded."* — today `automatic_update_checks` only gates the first in-panel check.

### Problem 2 — no toast when an update is available

`toaster.toast` is called in exactly four places in `pluginUpdateController.tsx`, none of
them for an available update: "Update Check Failed" (~lines 144 and 179, both gated on
`opts.force`, i.e. the manual button only), "Installation Initiated" (~line 223), and
"Installation Failed" (~lines 435 and 459). The `available` branch (~lines 150-163) only
dispatches `CHECK_SUCCESS_AVAILABLE` to the reducer; the result is rendered as in-panel
text ("Update available", `PluginUpdateSection.tsx` line 153). A user must open the QAM and
scroll to the Updates section to learn a release exists.

Half the plumbing for this already exists and is dead. `last_notified_tag` is returned by
`PluginUpdater.get_context()` (`py_modules/sdh_ludusavi/updater.py` line 146) and is typed
on the frontend (`src/types/index.ts` line 306, in `UpdateCheckContext`), but **nothing
writes it and nothing reads it** — a repo-wide grep finds only those two declarations. It
is scaffolding for a notification that was designed and never built. This plan wires it up
as the toast's dedup key.

### Problem 3 — an automatic check bypasses the backend's 24h cache

`updater.py` (~lines 197-219) throttles unforced checks to one real GitHub fetch per 24
hours. The effect at `pluginUpdateController.tsx` lines 314-335 intends to honor that: the
first-mount branch (line 330) passes `force: false`. But its dependency array includes
`checkForUpdates`, whose `useCallback` identity (line 198) changes whenever
`state.installedOverride`, `state.pendingInstallVersion`, or `effectiveCurrentVersion`
changes. During hydration with a pending install those all move, the effect re-runs with
`hasChecked.current` already `true`, and control falls to the `else` branch at line 333 —
`force: true`, which bypasses the 24h cache and hits the GitHub releases API for real. A
device log captured exactly this:

```text
14:44:24  update: check_start: trace_id=none, channel=development
14:44:24  frontend: Update check started (version=0.4.2, force=True)
14:44:24  frontend: GitHub releases fetch response: status=200, elapsed_ms=590
```

versus the healthy path on a later run: `force=False` → `Update check cache hit (within
24h…)`. This is the residual of the bug fixed in
`docs/plans/2026-06-19_fix-update-check-feedback-loop.md`, which removed `state.phase` from
the same dependency array but left `checkForUpdates` in it.

### Intended outcome

- The plugin checks for updates on a timer at plugin scope, so checking continues while the
  QAM panel is closed and the toggle description becomes true.
- When a genuinely new version is found, the user gets a toast once per release tag,
  controlled by a new `update_available` notification category.
- Automatic checks stop bypassing the backend's 24h cache.

### Design decisions (already settled — do not revisit)

1. **Poll interval is 6 hours**, with a 30-second settle delay before the first tick. The
   backend's 24h cache absorbs most ticks, so this costs at most ~1 real GitHub fetch per
   day while still catching a release within hours of a Deck wake. The plugin reloads
   frequently (the logs above show several reloads per hour), so a 24h timer would rarely
   fire; 6h survives that.
2. **The toast gets its own notification category**, `update_available`, alongside the
   existing four in `NotificationSettings`. It routes through the existing `notify()` helper
   in `src/index.tsx` (line 107) so the master "All Notifications" switch still silences it.
3. **Polling lives in the frontend at plugin scope**, not in the Python backend. The backend
   has no event bus — there is no `emit` / `addEventListener` anywhere in `main.py` or
   `src/api/ludusaviRpc.ts` — so it cannot push a toast to the UI. The `definePlugin`
   closure in `src/index.tsx` stays alive for as long as the plugin is loaded, and already
   hosts a comparable long-lived object (`lifecycleController`, created at line 230 and
   disposed at line 274).

### Key files

- `src/index.tsx` — plugin root; `notify()` helper (line 107), `definePlugin` (line 199),
  `onDismount` (line 271). New poller is created and disposed here.
- `src/runtime/updatePoller.ts` — **new**. Follow the dependency-injection factory shape of
  `src/runtime/startupHydration.ts` and `src/runtime/pluginRuntime.ts`.
- `src/controllers/pluginUpdateController.tsx` — the `force: true` fix (Problem 3).
- `src/components/qam/NotificationSettingsSection.tsx` — new toggle row.
- `src/types/index.ts` — `NotificationSettings` (line 1), `UpdateCheckContext` (line 302).
- `src/api/ludusaviRpc.ts` — RPC declarations; update calls at lines 101-106.
- `py_modules/sdh_ludusavi/updater.py` — `get_context` (line 125), `_clear_stale_cache`
  (line 153), `confirm_install_handoff` (line 543) as the return-shape pattern.
- `py_modules/sdh_ludusavi/service.py` — delegation methods (lines 469-483).
- `py_modules/sdh_ludusavi/constants.py` — `DEFAULT_NOTIFICATION_SETTINGS` (line 3).
- `main.py` — RPC surface; update methods at lines 108-173.

**Slug used throughout this plan:** `background-update-polling-toast`

---

## Orchestration Contract

**Slug:** `background-update-polling-toast`

**Plan file:**

```text
docs/plans/2026-07-24_background-update-polling-toast.md
```

**Implementation branch:**

```text
feat/background-update-polling-toast
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/background-update-polling-toast_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/background-update-polling-toast_finalized
```

**Review notes:**

```text
docs/review/background-update-polling-toast-review-*.md
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
git checkout -b feat/background-update-polling-toast
```

Commit this plan first:

```bash
git add docs/plans/2026-07-24_background-update-polling-toast.md
git commit -m "docs(plan): add background-update-polling-toast implementation plan"
```

---

## Implementation Tasks

Strict TDD. Every task below changes behavior, so write the failing test first, confirm it
fails for the stated reason, then implement the minimum to make it pass. Do the tasks in
order — later tasks depend on the RPCs and types added by earlier ones. Commit each task
separately with a Conventional Commits message.

Python tests go in `tests/` and run with `./run.sh uv run pytest`. Frontend tests are
colocated `*.test.ts` / `*.test.tsx` files and run with `./run.sh pnpm run test:unit`.

### Task 1 — Backend: add the `update_available` notification category

Red: extend `tests/test_constants.py` to assert `DEFAULT_NOTIFICATION_SETTINGS` contains
`update_available` defaulting to `True`. Add a test (fits `tests/test_config.py` or the
service settings tests) asserting that a persisted `notifications` dict that predates this
key still round-trips through `_coerce_notification_settings`
(`py_modules/sdh_ludusavi/service.py` line 567) with `update_available` set to the default.

Green: add `"update_available": True` to `DEFAULT_NOTIFICATION_SETTINGS` in
`py_modules/sdh_ludusavi/constants.py`. No other backend change is required —
`_coerce_notification_settings` iterates the keys of `DEFAULT_NOTIFICATION_SETTINGS`, so
old persisted settings that lack the key inherit the default automatically. Verify that
claim with the test rather than assuming it.

### Task 2 — Backend: `mark_update_notified` RPC

Red: add tests to `tests/test_updater.py` asserting that:

- `PluginUpdater.mark_notified("v1.2.3")` persists `last_notified_tag` into the update cache
  and that a following `get_context()` returns `last_notified_tag == "v1.2.3"`;
- `mark_notified` calls the save callback exactly once;
- `_clear_stale_cache()` drops `last_notified_tag`, so switching channels re-arms the toast.

Green:

- In `py_modules/sdh_ludusavi/updater.py`, add `mark_notified(self, tag: str) -> dict[str, object]`.
  Acquire `self._state_lock`, set `self._cache["last_notified_tag"] = tag`, call
  `self._save_callback()`, log at info level, and return `self.get_context()`. Match the
  structure of `confirm_install_handoff` (line 543), which is the established pattern for a
  cache mutation that returns the refreshed context.
- Add `last_notified_tag` to the keys popped by `_clear_stale_cache` (line 153), next to
  `last_available_tag`.
- In `py_modules/sdh_ludusavi/service.py`, add
  `def mark_update_notified(self, tag: str) -> dict[str, Any]: return self._updater.mark_notified(tag)`
  alongside the other update delegates (lines 469-483).
- In `main.py`, add `async def mark_update_notified(self, tag: str) -> dict[str, Any]`
  wrapping the service call through the same guard helper used by
  `confirm_update_install_handoff` (line 124).

Do **not** add any caller yet — Task 5 consumes this.

### Task 3 — Frontend: types and RPC declaration

No behavior change, so no test is required for this task on its own; it is exercised by
Tasks 4 and 5.

- `src/types/index.ts`: add `update_available: boolean;` to `NotificationSettings` (line 1).
  Leave `NotificationCategory` alone — it is derived as `keyof Omit<NotificationSettings, "enabled">`
  and picks the new key up automatically. `UpdateCheckContext.last_notified_tag` already
  exists at line 306; do not redeclare it.
- `src/api/ludusaviRpc.ts`: add, next to the other update calls at lines 101-106:

  ```ts
  export const markUpdateNotifiedCall = callable<[tag: string], RpcResult<UpdateCheckContext>>("mark_update_notified");
  ```

### Task 4 — Frontend: notification toggle row

Red: add a test for `NotificationSettingsSection` asserting the new row renders and that
toggling it calls `onToggleNotificationSetting("update_available", …)`. If no test file
exists for this component, create `src/components/qam/NotificationSettingsSection.test.tsx`
following the render/assert conventions already used in
`src/controllers/pluginUpdateController.test.tsx`.

Green: in `src/components/qam/NotificationSettingsSection.tsx`, add a fourth `ToggleField`
row after "Failures and Errors":

- `label="Plugin Updates"`
- `description="Shows a toast when a new plugin version is available."`
- `checked={settings.notifications.update_available}`
- `disabled={!settings.notifications.enabled || isBusy}`
- `onChange={(enabled: boolean) => onToggleNotificationSetting("update_available", enabled)}`

Move `bottomSeparator="none"` from the "Failures and Errors" row (line 52) to this new last
row, and give "Failures and Errors" `bottomSeparator="standard"` to match the rows above it.

### Task 5 — Frontend: the background update poller

This is the core of the change. Create `src/runtime/updatePoller.ts` with a colocated
`src/runtime/updatePoller.test.ts`.

Red first. Write the test file before the module. Required cases, all driven with injected
fake timers and stub dependencies (no real clocks, no real RPC):

1. `start()` performs no check immediately; the first check fires only after the initial
   delay elapses.
2. After the initial check, a check fires once per poll interval.
3. Every poll passes `force: false` to the check call — assert on the argument. This is what
   keeps the backend's 24h cache in control of real network traffic.
4. A tick is skipped entirely when the context reports `automatic_update_checks: false`.
5. A tick is skipped when the context reports a non-null `pending_update_install`, mirroring
   the `automatic_check_suppressed_pending_install` guard at
   `pluginUpdateController.tsx` lines 105-108.
6. `status: "available"` with a candidate tag different from `last_notified_tag` calls
   `notify` once and then calls `markUpdateNotified` with that tag.
7. `status: "available"` with a candidate tag equal to `last_notified_tag` does **not**
   notify — this is the dedup that stops a toast on every plugin reload.
8. `status: "current"` and `status: "failed"` never notify. A `failed` result is logged at
   warning level and the poller keeps its schedule; the backend returns `failed` for the
   rate-limit cooldown, and that must never surface as a toast.
9. A tick that is still in flight suppresses the next scheduled tick rather than running two
   concurrently.
10. `dispose()` clears both the initial-delay timer and the interval, and a check that
    resolves after `dispose()` neither notifies nor calls `markUpdateNotified`.

Green: implement `createUpdatePoller`. Follow the dependency-injection factory shape of
`src/runtime/startupHydration.ts` — a factory taking a deps object and returning a frozen
object with `start()` and `dispose()`. Requirements:

- Export the two timings as named constants so the tests import them rather than hardcoding
  numbers:

  ```ts
  export const UPDATE_POLL_INTERVAL_MS = 6 * 60 * 60 * 1000; // 6 hours
  export const UPDATE_POLL_INITIAL_DELAY_MS = 30_000;
  ```

  The 30-second settle delay keeps the first check from competing with startup hydration and
  the game-list refresh, both of which run at plugin init.
- Inject every side-effecting dependency: `getUpdateCheckContext`, `checkForUpdate`,
  `markUpdateNotified`, `notify`, `log`, and the timer functions
  (`setTimeout`/`clearTimeout`/`setInterval`/`clearInterval`), each defaulting to the global.
- Resolve the current version from the context's `effective_installed_version` rather than
  from a versions RPC. The backend already resolves it (`updater.py` lines 134-142), it
  accounts for a pending install, and it means the poller needs no store access for the
  check itself.
- Read `automatic_update_checks` from the same context payload, so toggling the setting takes
  effect on the next tick with no reload and no store subscription.
- Wrap the whole tick body in try/catch. A thrown RPC must be logged and must not kill the
  interval — the poller has to survive a suspend/resume cycle where an RPC fails.
- Toast copy: title `"SDH-Ludusavi Update Available"`, body
  `` `v${candidate.version} is available. Open the plugin to install.` ``.
- Order the notify/mark sequence so `markUpdateNotified` runs only after `notify` has been
  dispatched, and skip both when disposed.

### Task 6 — Wire the poller into the plugin root

Red: this is composition; cover it by asserting in a test that `dispose()` is reachable, or
rely on the Task 5 tests plus the typecheck gate. Do not add a brittle test that mounts the
whole plugin.

Green: in `src/index.tsx`:

- Create the poller after `lifecycleController` (line 230) and call `start()` next to
  `lifecycleController.start()` (line 253).
- Pass `notify` bound to the store and the new category:

  ```ts
  notify: (title, body) => notify(ludusaviStore, "update_available", title, body),
  ```

  This routes through the existing helper at line 107, which already checks
  `store.shouldShowNotification(category)` (`src/state/ludusaviState.tsx` line 227) and so
  honors both the master switch and the new per-category toggle.
- Call the poller's `dispose()` inside `onDismount` (line 271), alongside
  `lifecycleController.dispose()`.

### Task 7 — Stop the automatic check from bypassing the 24h cache

Red: add a test to `src/controllers/pluginUpdateController.test.tsx` that hydrates the
controller with a context containing a `pending_update_install` (so `installedOverride`,
`pendingInstallVersion`, and `effectiveCurrentVersion` all change during hydration) and
asserts that no automatic check is issued with `force: true`. With the current code this
fails: the identity of `checkForUpdates` changes, the effect at lines 314-335 re-runs with
`hasChecked.current === true`, and the `else` branch at line 333 fires a forced check.

Green: in `src/controllers/pluginUpdateController.tsx`, keep the latest `checkForUpdates` in
a ref and drop it from the dependency array of the effect at lines 314-335, leaving
`[updateChannel, currentVersion, isHydrated]`. Those three are the legitimate triggers: a
monotonic hydration gate plus two external inputs. Preserve the existing
`hasChecked` / `skipInitialCheck` / `automaticUpdateChecks` semantics and the timeout and
cancellation refs.

Constraints carried over from `docs/plans/2026-06-19_fix-update-check-feedback-loop.md`:

- Do not reintroduce `state.phase` into either effect's dependency array.
- Do not touch the `install` callback's `state.phase` dependency (line 465) — it is correct.
- Do not weaken any existing assertion in `pluginUpdateController.test.tsx`.

### Task 8 — Documentation and session log

- Update `README.md` where update behavior or notification categories are described, to
  state that checks run in the background every 6 hours while the plugin is loaded and that
  an available update raises a toast controlled by the "Plugin Updates" notification toggle.
- Record a session log under `docs/agent_conversations/` per AGENTS.md section 15: date,
  task objective, files modified, tests added, design decisions, results.

### Out of scope

- Do not add a backend `asyncio` polling task or an event bus. Polling is frontend-side by
  design (see Context).
- Do not make the poll interval user-configurable.
- Do not redesign the update reducer, the manual "Check now" button, the install flow, or
  the rate-limit/cooldown behavior.
- Do not bump the plugin version or cut a release; finalization handles the dev release.

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

Run the full gate chain from the repository root:

```bash
./run.sh bash scripts/quality_gates.sh check
```

That runs ruff check, ruff format --check, `ty check py_modules/sdh_ludusavi/`, pytest, and
`pnpm run verify` (which invokes `pnpm test` = vitest + tsc) — see
`scripts/check_frontend_supply_chain.sh` line 64.

Targeted runs while iterating:

```bash
./run.sh uv run pytest tests/test_updater.py tests/test_constants.py
./run.sh pnpm run test:unit
```

Assertions to confirm before marking the round complete:

1. The Task 5 poller tests fail against an absent/no-op module and pass against the
   implementation, including the two dedup cases (new tag notifies, repeat tag does not).
2. The Task 7 regression test fails on the unpatched controller and passes after the ref
   change. Re-read the patched dependency array and confirm it contains no value that
   changes as a result of a check completing.
3. Every existing test in `src/controllers/pluginUpdateController.test.tsx` and
   `tests/test_updater*.py` still passes with its original assertions.
4. Grep confirms `last_notified_tag` now has a writer and a reader, not just the two
   declarations it had before:

   ```bash
   grep -rn "last_notified_tag" --include=*.py --include=*.ts --include=*.tsx . | grep -v node_modules
   ```

### Deferred on-device verification

These require a Steam Deck and a published release, so they run after the dev build from
finalization is installed — not during the implementation round. Record them as deferred in
the session log.

Plugin logs live at `/home/deck/homebrew/logs/SDH-Ludusavi/` (note: not `/home/deck/logs`).

1. **Background polling.** Install the dev build, load the plugin, and do **not** open the
   QAM panel. Confirm a `update: check_start` appears roughly 30 seconds after
   `ui: plugin_initializing`, with no preceding `ui: qam_content_mounted`. That single log
   pairing is the whole point of the change — today every `check_start` is preceded by a
   mount.
2. **Cache respected.** Confirm the polled check logs `force=False` and, on the second and
   later ticks within a day, `Update check cache hit (within 24h…)` rather than a
   `GitHub releases fetch response`.
3. **Toast fires once.** With the update channel set to `development` and an older build
   installed so a real candidate exists, confirm the toast appears with the candidate
   version, then reload the plugin and confirm it does **not** appear again (dedup via
   `last_notified_tag`).
4. **Toggle silences it.** Turn off "Plugin Updates" in the Notifications section, force
   another available result, and confirm no toast. Repeat with the master "All
   Notifications" switch off.
5. **No forced-check regression.** Open and close the QAM panel several times, including
   immediately after an install, and confirm no `force=True` automatic check appears in the
   log — only the manual "Check now" button should produce one.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished background-update-polling-toast
```

This writes:

```text
/tmp/sdh_ludusavi/background-update-polling-toast_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer background-update-polling-toast`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/background-update-polling-toast-review-*.md
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
   scripts/orchestration/clear-finished background-update-polling-toast
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
   git add docs/review/background-update-polling-toast-review-*.md
   git commit -m "docs(review): record background-update-polling-toast review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished background-update-polling-toast
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer background-update-polling-toast` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed background-update-polling-toast
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize background-update-polling-toast
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/background-update-polling-toast_finalized
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
scripts/orchestration/finalize background-update-polling-toast
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/background-update-polling-toast_finished
/tmp/sdh_ludusavi/background-update-polling-toast_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
