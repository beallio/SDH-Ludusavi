# Plan: Separate QAM View Selection From Persisted Preference (selected-game-view-state)

## Context

Flipping any QAM setting can silently change which game the panel is showing.
Observed on device: the panel opened on `X-Men Origins: Wolverine - Uncaged
Edition` (auto-selected from Steam context) while the persisted preference was
`Warhammer 40,000: Space Marine`; toggling a setting snapped the display — and
with it the status, last-operation, Browse Backups target, and the per-game sync
toggle's own checked state — to Warhammer.

Root cause: `snapshot.selectedGame` and `snapshot.settings.selected_game` look
like separate fields but are welded together in both directions.

- `applySettings` (`src/state/ludusaviState.tsx:136-145`) derives
  `selectedGame: normalized.selected_game`, so every settings write repositions
  the UI. Settings-mutation results call `applySettings(store, res)` with the
  backend's full payload, so a response about an unrelated key moves the
  selection.
- `setSelectedGame` (`ludusaviState.tsx:152-154`) goes the other way via
  `patchSettings({ selected_game })`, so a purely visual auto-selection writes
  into the store's `settings` object. From then on `snapshot.settings` is a blend
  of persisted values and transient view state with nothing marking which is
  which.

Two concepts with different lifetimes are sharing one field:

- **Ephemeral view selection** — which game the panel shows right now. Changes on
  panel open, on refresh, and from Steam context. Must never reach disk.
- **Persisted preference** — which game to show absent better information.
  Changes only on deliberate user choice. Belongs on disk.

Intended outcome: make `selectedGame` a genuinely independent store field so the
bug class disappears by construction rather than being patched per call site.
After this change, `applySettings` never touches the displayed selection, and
auto-selection never writes to settings.

The consumer side is cheap: roughly 50 non-test lines mention `selectedGame`,
almost all of them reads that do not change. Only the writers do.

`settings.selected_game` has few direct readers, but they are load-bearing and
must not be overlooked:

- `src/components/qam/useInitialContent.ts:116` reads it into `preferredGame` and
  passes it to the refresh-application paths at `:125` and `:131`. This is the
  one that defeats a naive fix — see Task 4.
- `src/settings/settingsMutationRuntime.ts:108-109` and `:481-489` use it for
  persisted-value bookkeeping.
- `src/runtime/startupHydration.ts:60` logs it.

Note that `src/components/qam/useSteamContext.ts:72,87` logs a field *named*
`selected_game` but sources it from the displayed value, not from settings.

Decisions already made — do not revisit:

- The displayed selection is seeded from the persisted preference **only when it
  is empty** (first hydration). Reopening the QAM keeps showing the game you were
  last looking at rather than snapping back.
- Auto-selection must **not** start persisting. That alternative was considered
  and rejected: `set_selected_game` calls `_save_state`, which rewrites the whole
  settings payload *and* the entire cache (game list plus full per-game history)
  on every QAM open, and would widen the sibling-instance clobber window on
  `sync_disabled_games` that `persistence.mutate_settings` was written to close.
- Manual dropdown selection keeps persisting exactly as it does today.
- `settings.selected_game` stays in the `Settings` type, stays persisted, and
  stops being polluted by view state. Scope that claim precisely: it becomes a
  mirror of the latest RPC response from the active backend instance, not a
  guaranteed mirror of disk. A sibling instance during a Decky reload can still
  return its own stale in-memory values for unrelated keys
  (`py_modules/sdh_ludusavi/service.py:189-198`, returned at `:238`). That is a
  separate pre-existing concern and is **out of scope here** — do not try to fix
  it in this plan.

Relevant existing code:

- `src/state/ludusaviState.tsx` — `applySettings`, `patchSettings`,
  `setSelectedGame`, `createInitialSnapshot`.
- `src/components/qam/LudusaviContent.tsx` — reads the display field at `:103`;
  auto-selection writers at `:250`, `:259`, `:295`, `:308`; the
  `setSelectedGame` dependency wired at `:160`.
- `src/components/qam/useSteamContext.ts` — Steam-context auto-selection at
  `:29` and `:106`.
- `src/settings/settingsMutationRuntime.ts` — `onGameChange` (the persisting
  path) around `:462-489`; every other mutation's `applyResult` calls
  `applySettings(ludusaviStore, res)`.
- `src/runtime/startupHydration.ts` — hydration point one.
- `src/components/qam/useInitialContent.ts:93` — hydration point two.

**Slug used throughout this plan:** `selected-game-view-state`

---

## Orchestration Contract

**Slug:** `selected-game-view-state`

**Plan file:**

```text
docs/plans/2026-07-19_selected-game-view-state.md
```

**Implementation branch:**

```text
feat/selected-game-view-state
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/selected-game-view-state_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/selected-game-view-state_finalized
```

**Review notes:**

```text
docs/review/selected-game-view-state-review-*.md
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
git checkout -b feat/selected-game-view-state
```

Commit this plan first:

```bash
git add docs/plans/2026-07-19_selected-game-view-state.md
git commit -m "docs(plan): add selected-game-view-state implementation plan"
```

---

## Implementation Tasks

Work the tasks in order. Write the failing test first for every behavior change.

This is a decoupling refactor: the observable fix is that settings mutations stop
moving the displayed game. Everything else about selection behavior — which game
auto-selection picks, what the dropdown does, what gets persisted — must stay
exactly as it is today.

### Store API (fixed — use exactly this)

Rename the store's writers so the two concepts cannot be confused again:

- `setDisplayedGame(gameName: string)` — sets `snapshot.selectedGame` only.
  Never touches `settings`.
- `hydrateDisplayedGame(gameName: string)` — sets `snapshot.selectedGame` only
  **if it is currently empty**; otherwise a no-op.

`setSelectedGame` is deleted, but **not until every caller is migrated**. Follow
the staged order below: add the new methods, migrate all callers, then delete.
Deleting in the first task would break typecheck until the last one, leaving the
suite red across several commits. Do not keep an alias after the deletion — a
leftover alias is how this coupling grows back.

### Task 1 — Add the new store methods (additive, suite stays green)

Tests: `src/state/ludusaviState.test.tsx`.

1. In `src/state/ludusaviState.tsx`, add `setDisplayedGame(gameName: string)`,
   writing `this.commit({ selectedGame: gameName })` directly. It must **not**
   call `patchSettings`.
2. Add `hydrateDisplayedGame(gameName: string)`, which commits only when
   `this.snapshot.selectedGame` is empty.
3. Leave `setSelectedGame`, `applySettings`, and `createInitialSnapshot` untouched
   in this task.

Tests must prove `setDisplayedGame` does not alter
`snapshot.settings.selected_game`, and that `hydrateDisplayedGame` seeds an empty
selection and is a no-op once one is set.

### Task 2 — Migrate every caller to the new methods

Mechanical rename, no behavior change yet. Update:

- `src/components/qam/LudusaviContent.tsx:160` (the injected dependency), `:250`,
  `:259`, `:295`, `:308`;
- `src/components/qam/useSteamContext.ts:29` and `:106` — these take the setter as
  a parameter, so update the parameter types at `:15` and `:48` too;
- `src/settings/settingsMutationRuntime.ts:476` (`optimisticUpdate`) and `:486`
  (`rollbackUpdate`), keeping the existing `lastQueuedSelectedGame = fallback`
  line in the rollback.

Do not change which game any of these paths chooses.
`resolveRefreshedSelection`, `selectCurrentSteamGameIfAvailable`, and
`resolveQamOpenSelection` are untouched in this task.

Migrating `onGameChange`'s `optimisticUpdate` changes observable behavior
immediately — `setDisplayedGame` does not patch settings, so
`src/settings/settingsMutationRuntime.test.ts:219-222`, which expects the
optimistic call to update `settings.selected_game` at once, goes red the moment
this task lands. Rewrite that assertion **in this task**, not later: the settings
mirror now stays at its previous value until the RPC resolves. Leaving it for
Task 3 would leave the suite red across a commit boundary.

### Task 3 — Cut the coupling and delete the old method

This is the task that changes behavior.

1. Remove `selectedGame` from the `commit` call in `applySettings`
   (`ludusaviState.tsx:136-145`). It keeps setting `settings`,
   `autoSyncNotificationsEnabled`, and `notificationSettings` — those genuinely
   derive from settings.
2. Delete `setSelectedGame`.

Existing tests assert the coupling and must be deliberately rewritten — they are
not incidental breakage:

- `src/state/ludusaviState.test.tsx:113` expects `applySettings` to set
  `selectedGame`. Invert it: `applySettings` must now leave the display alone.
- `src/state/ludusaviState.test.tsx:120-124` expects `setSelectedGame` to update
  both the display and `settings.selected_game`. Rewrite for `setDisplayedGame`
  updating only the display.
(`src/settings/settingsMutationRuntime.test.ts:219-222` was already rewritten in
Task 2, where the behavior actually changed.)

Record the rationale for each of these rewrites in the session log.

### Task 4 — Stop the refresh path from overriding a live selection

**Without this task the fix does not work.** `resolveRefreshedSelection`
(`src/components/qam/refreshSelection.ts:15`) resolves
`preferredGame || currentSelectedGame` — the preferred value *wins*. And
`useInitialContent.ts:116` sources `preferredGame` from
`settings.selected_game`. So even with `hydrateDisplayedGame` correctly
no-opping, this sequence still moves the display:

1. display is A (auto-selected from Steam context);
2. persisted preference is B;
3. `hydrateDisplayedGame(B)` no-ops because the display is non-empty;
4. initial game-list synchronization completes and applies `preferredGame = B`;
5. display becomes B.

Note that `preferredGame` is overloaded across callers: `useInitialContent`
passes the *persisted* preference, while `manualOperationFinalize.ts:41` passes
the *displayed* game. Do **not** change the precedence inside
`resolveRefreshedSelection` — that would alter a shared contract for all callers.
Fix it at the application site instead.

In `src/components/qam/LudusaviContent.tsx`, in both `applyCachedRefreshResult`
(~`:240-260`) and `applyRefreshResult` (~`:290-310`):

1. read the current selection live from the store —
   `const currentSelectedGame = ludusaviStore.getSnapshot().selectedGame;` —
   instead of the render-captured `selectedGame` used today at `:257` and `:303`.
   The captured value can be stale: `useInitialContent` starts its load from a
   mount-only effect (`useInitialContent.ts:207-209`), so the closure can still
   hold an empty string after another path has populated the store.
2. suppress `preferredGame` only when the live selection is **valid in the game
   list being applied** — not merely non-empty:

   ```ts
   const liveSelectionValid =
     currentSelectedGame !== "" &&
     games.some((game) => game.name === currentSelectedGame);
   const outcome = resolveRefreshedSelection({
     games,
     preferredGame: liveSelectionValid ? undefined : preferredGame,
     currentSelectedGame,
   });
   ```

   A non-empty-only check is wrong: with games `[A, B]`, a live selection of `Z`
   that no longer exists, and a valid persisted preference `B`, suppressing `B`
   would make `resolveRefreshedSelection` reject `Z` and fall through to first
   game `A` — silently discarding a valid preference.

Net precedence becomes: explicit Steam-context selection, then a **valid** live
displayed selection, then the persisted preference, then the first game. That is
the same "display wins once set" rule as the seeding decision, applied to the
path that would otherwise bypass it.

Because there is no `LudusaviContent` test file, extract this decision into a
pure, unit-testable helper rather than testing it through the component. Add a
new exported function to `src/components/qam/refreshSelection.ts` — for example
`resolveAppliedSelection({ games, preferredGame, liveSelection })` — that
encapsulates the validity check and delegates to the existing
`resolveRefreshedSelection`. Do **not** modify `resolveRefreshedSelection`
itself; its `preferredGame || currentSelectedGame` contract is relied on by other
callers.

This is behaviour-neutral for the other callers: `manualOperationFinalize` passes
the displayed game as `preferredGame`, so ignoring it in favour of the identical
live value changes nothing, and `useGameRefresh.ts:56` passes no preferred game
at all.

Tests, against the new helper in `refreshSelection.test.ts`:

- the five-step sequence above — live selection A, persisted B, refresh applied,
  result must remain A;
- cold case: empty live selection still takes the persisted preference;
- stale case: live selection `Z` absent from `[A, B]` with persisted `B` valid
  must resolve to `B`, not to first-game `A`;
- no preference and no live selection falls back to the first game.

### Task 5 — Seed at both hydration points

There are two, and missing either leaves the panel showing an empty selection on
open — a worse bug than the one being fixed.

1. `src/runtime/startupHydration.ts` — after `deps.applySettings(settings)`, seed
   from `settings.selected_game`. Add a `hydrateDisplayedGame` (or equivalently
   named) dep to `StartupHydrationDeps` and wire it where the runtime constructs
   the hydration, rather than reaching for the store directly from inside.
2. `src/components/qam/useInitialContent.ts:93` — same treatment after its
   `deps.applySettings(loadedSettings as Settings)` call.

Both seed calls must go through `hydrateDisplayedGame`, so a second hydration
cannot overwrite a selection the user is already looking at.

Tests: extend `src/runtime/startupHydration.test.ts` and the `useInitialContent`
tests to assert the seed happens on a cold store and is skipped when a selection
already exists.

You must also make the initial fetch survive a thrown settings request. This is
**required**, not optional polish — without it this refactor introduces a way to
strand the panel with no selection.

Today, if `deps.getSettings()` throws, the `Promise.all` in
`useInitialContent.ts:83-87` rejects, so `synchronizeGameList` at `:164-166`
never runs and the catch at `:187-203` only logs. The panel can then show a game
list (populated independently by startup tracking,
`startupHydration.ts:72-103`) with an empty selection. There is **no automatic
retry**: initialization runs from a mount-only effect
(`useInitialContent.ts:207-209`), `LudusaviContent` never re-invokes
`loadInitial`, and `alwaysRender: true` (`src/index.tsx:269`) means reopening the
QAM does not remount the component.

Current code self-heals from that state by accident: the next successful settings
mutation — the user toggling Automatic Sync, say — returns a full payload, and
`applySettings` seeds `selectedGame` from it (`ludusaviState.tsx:136-143`). After
Task 3 that no longer happens, and Task 6 deliberately leaves the mutation paths
alone, so the display would stay empty indefinitely. The refactor removes an
accidental recovery, so it owes a deliberate one.

Change `fetchInitialState` so a failure of either request degrades independently
instead of rejecting the whole initialization:

1. await the two calls so one rejection cannot cancel the other's handling — for
   example `Promise.allSettled` over `deps.getSettings()` and
   `deps.getGameHistoryCall()`;
2. on a rejected settings request, log it through the existing failure path
   (`deps.logError` / `deps.logRpcStatus`), skip `applySettings`, and return a
   value for which `deps.isRpcStatus(...)` is true, so `synchronizeGameList`
   computes `preferredGame` as `undefined` at `useInitialContent.ts:116` exactly
   as it already does for an RPC-status payload;
3. handle a rejected history request the same way, leaving existing history
   behavior unchanged;
4. let `synchronizeGameList` run in both cases so Steam-context or first-game
   resolution establishes a valid selection.

Tests: settings request **throws** while a game list is available — the panel
must still end with a non-empty selection; history request throws independently;
and both succeeding still behaves exactly as before.

### Task 6 — Fix the persisting path

`onGameChange` (~`:462-489`) is the one selection path that must still write to
disk. Its `optimisticUpdate` and `rollbackUpdate` were already migrated in
Task 2; confirm here that `applyResult` is left as-is. Its `isLatest` branch
calls `applySettings(ludusaviStore, res)`, which after Task 3 no longer moves the
display — that is the fix working as intended, not something to compensate for.
The dropdown's own `optimisticUpdate` already set the display.

Leave every other mutation's `applyResult` alone. All six — `toggleAutoSync`,
`toggleGameSync`, `toggleNotificationSetting`, `toggleUpdateChannel`,
`toggleAutomaticUpdateChecks` (`settingsMutationRuntime.ts:417-440`), and
`toggleDebugLogging` — may keep calling `applySettings` wholesale, because after
Task 3 that call is no longer capable of moving the selection. Do not
opportunistically rewrite them.

Tests: extend `src/settings/settingsMutationRuntime.test.ts` with the regression
that motivates this plan — with the displayed game set to A and the backend's
persisted `selected_game` still B, flipping an unrelated setting (use
`toggleGameSync`) must leave the displayed game as A. Add the same assertion for
`toggleAutoSync` so the guarantee is covered for more than the one toggle.

### Task 7 — Documentation

Update `DEVELOPMENT.md` where frontend state is described, stating the invariant
plainly: `selectedGame` is ephemeral view state, `settings.selected_game` is the
persisted preference, only `onGameChange` writes the latter, and `applySettings`
must never touch the former.

Record a session log under `docs/agent_conversations/` per the repo protocol.

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

Automated checks the implementer runs and must report output for:

```bash
scripts/orchestration/run-quality-gates
```

That hook runs `pnpm test`, `pnpm run build`, `./run.sh uv run ruff check . --fix`,
`./run.sh uv run ruff format .`, `./run.sh uv run ty check py_modules/sdh_ludusavi/`,
and `./run.sh uv run pytest`. Expected: every command exits 0, with new tests
present for Tasks 1, 3, 4, 5, and 6.

Targeted checks before marking the round complete:

1. `git grep -n -w "setSelectedGame" -- src` returns **no** hits. The `-w`
   word-boundary flag is required: the RPC binding `setSelectedGameCall`
   (`src/api/ludusaviRpc.ts:44`, used at `settingsMutationRuntime.ts:9,471-477`)
   contains the old name as a substring and must survive. If test-local callback
   variables named `setSelectedGame` exist (see
   `src/components/qam/useSteamContext.test.ts:30-64`), rename them so this check
   is unambiguous.
2. `git grep -n "selectedGame" -- src/state/ludusaviState.tsx` shows it committed
   only by `setDisplayedGame` and `hydrateDisplayedGame` — never inside
   `applySettings`.
3. No backend file changed. This is frontend-only: `selected_game` has no
   behavioral consumer in `py_modules/` (it is stored, returned by
   `get_settings`, and set — nothing reads it to make a decision), so a diff
   touching `py_modules/` means the scope was exceeded.

Deferred verification — cannot be done in this environment. State it plainly in
the session log rather than claiming it passed:

- On-device: open the QAM with a game running so the panel auto-selects it, then
  flip the per-game sync toggle. The displayed game must not change, and the
  toggle must still reflect the game you were looking at. This is the exact
  failure this plan exists to fix.
- On-device: repeat with the global Automatic Sync toggle and a notification
  toggle.
- On-device: change the game manually in the dropdown, close and reopen the QAM
  with nothing running, and confirm your choice persisted.
- On-device: with a game running, confirm auto-selection still picks it on open.
- On-device: reopen the QAM twice in a row **with no game running** and confirm
  the second open keeps the game you were last viewing rather than snapping to
  the persisted preference. The "no game running" condition matters: every
  visibility transition re-arms selection (`useSteamContext.ts:67-77`) and a
  running match is auto-selected at `:92-107`, which legitimately overrides the
  last-viewed game.
- Confirm via pulled logs (`./run.sh uv run python scripts/pull_plugin_logs.py
  --host steamdeck`) that `qam_opened`'s `selected_game` field still reports a
  sensible displayed game. Note it is logged at open time
  (`useSteamContext.ts:66-90`) before the Steam auto-selection effect at
  `:92-108` runs, so it reflects the selection at open, not necessarily the game
  finally shown.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished selected-game-view-state
```

This writes:

```text
/tmp/sdh_ludusavi/selected-game-view-state_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer selected-game-view-state`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/selected-game-view-state-review-*.md
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
   scripts/orchestration/clear-finished selected-game-view-state
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
   git add docs/review/selected-game-view-state-review-*.md
   git commit -m "docs(review): record selected-game-view-state review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished selected-game-view-state
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer selected-game-view-state` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed selected-game-view-state
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize selected-game-view-state
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/selected-game-view-state_finalized
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
scripts/orchestration/finalize selected-game-view-state
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/selected-game-view-state_finished
/tmp/sdh_ludusavi/selected-game-view-state_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
