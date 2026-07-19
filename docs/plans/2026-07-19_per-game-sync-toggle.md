# Plan: Per-Game Sync Toggle (per-game-sync-toggle)

## Context

Automatic sync today is all-or-nothing: the `Automatic Sync` toggle in the QAM
`GLOBAL` section (`src/components/qam/AutoSyncSettingsSection.tsx`) gates every
tracked game. Users need to exclude individual games — for example a game whose
saves are already synced by its own cloud, or one where a restore would be
destructive — without turning off auto-sync for their whole library.

Intended outcome:

- A per-game `Sync This Game` toggle appears directly below the `Browse Backups`
  button in the QAM `GAME` section, applying to the currently selected game.
- The toggle defaults to on. Turning it off disables **both** the launch-time
  restore and the exit-time backup for that game only.
- When global `Automatic Sync` is off, the per-game toggle has no effect —
  nothing runs for any game either way. The toggle stays interactive and its
  value is still persisted, so it takes effect when global auto-sync is
  re-enabled.
- When global auto-sync is on and the selected game's per-game sync is off, the
  in-game status bar briefly shows `SAVE SYNC DISABLED FOR THIS GAME` at game
  start, then auto-hides like other terminal statuses. The notice appears on
  **start only** — it must be suppressed on exit, even though the exit path
  returns the same skip reason.
- The start notice is **best-effort**, not guaranteed. `check_game_start` returns
  the silent `operation_running` reason before it ever reaches the per-game check
  (`py_modules/sdh_ludusavi/lifecycle.py:193`), so launching a disabled game while
  another Ludusavi operation is in flight shows no bar. Sync is still correctly
  skipped; only the banner is missing. Do not reorder the checks to fix this.
- A disabled game must not be paused with the SIGSTOP launch gate and must not
  start any Syncthing watch — not the initial pre-game watch, not the pre-game
  watch restarted after conflict resolution, and not the post-game watch on exit.
  Nothing is going to run, so the launch must not be delayed at all.

Decisions already made — do not revisit:

- Per-game state is keyed by **Ludusavi game name**, matching how
  `selected_game` and `game_history` are already keyed
  (`py_modules/sdh_ludusavi/service.py`, `py_modules/sdh_ludusavi/history.py`).
- Storage is an opt-out list persisted in settings, so absence means enabled and
  no migration is needed for existing installs.
- The status bar is informational only; no launch gate, no pause, no watch.

Relevant existing code:

- `py_modules/sdh_ludusavi/constants.py` — `SETTINGS_KEYS` tuple.
- `py_modules/sdh_ludusavi/service.py` — settings state, `get_settings`,
  `set_auto_sync_enabled` (the model for the new setter), `_load_state`,
  `_save_state`, `LifecycleDependencies` wiring at ~line 122, and the `_skip`
  helper at ~line 487 whose reason allowlist controls history recording.
- `py_modules/sdh_ludusavi/lifecycle.py` — `check_game_start`,
  `restore_game_on_start`, `resolve_game_start_conflict`, `check_game_exit`,
  and the `LifecycleDependencies` dataclass with `is_auto_sync_enabled`.
- `main.py` — RPC method surface.
- `src/api/ludusaviRpc.ts` — `callable` declarations.
- `src/types/index.ts` — `Settings`, `AutoSyncStatusKind`.
- `src/state/ludusaviState.tsx` — `normalizeSettings`, `applySettings`,
  `patchSettings`, `setAutoSyncEnabled`.
- `src/settings/settingsMutationRuntime.ts` — `toggleAutoSync` at ~line 257 is
  the exact template for the new optimistic-mutation-with-rollback toggle.
- `src/components/qam/GameSettingsSection.tsx` — the `Browse Backups` row.
- `src/components/qam/LudusaviContent.tsx` — QAM wiring at ~line 551.
- `src/controllers/gameLifecycleController.tsx` — `handleAppStart` at ~line 159,
  where `autoSyncEnabled` gates the pause and the Syncthing watch.
- `src/controllers/gameLifecycleDecision.ts` — `SILENT_SKIPPED_REASONS`.
- `src/surfaces/autoSyncStatusSurface.tsx` — `complete()` maps a skipped result
  reason to a published status (~line 299).
- `src/surfaces/autoSyncStatusRenderer.tsx` — `autoSyncStatusText` map and
  `iconSvgForAutoSyncStatus`.

**Slug used throughout this plan:** `per-game-sync-toggle`

---

## Orchestration Contract

**Slug:** `per-game-sync-toggle`

**Plan file:**

```text
docs/plans/2026-07-19_per-game-sync-toggle.md
```

**Implementation branch:**

```text
feat/per-game-sync-toggle
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/per-game-sync-toggle_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/per-game-sync-toggle_finalized
```

**Review notes:**

```text
docs/review/per-game-sync-toggle-review-*.md
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
git checkout -b feat/per-game-sync-toggle
```

Commit this plan first:

```bash
git add docs/plans/2026-07-19_per-game-sync-toggle.md
git commit -m "docs(plan): add per-game-sync-toggle implementation plan"
```

---

## Implementation Tasks

Work the tasks in order. Each task is one commit (or a red/green pair of commits).
Write the failing test first for every behavior change, then implement.

### Data shape (fixed — use exactly this)

Settings gain one key, an opt-out list of Ludusavi game names:

```json
"sync_disabled_games": ["Game A", "Game B"]
```

Absent or empty means every game syncs. Persist it sorted and de-duplicated so
settings writes stay stable. Never write a key that flips the default: a game is
disabled only if its name is present in the list.

New skip reason string: `game_sync_disabled`.
New status kind: `game_sync_disabled`.

---

### Task 1 — Backend settings state and setter

Tests: `tests/` (follow the existing service-test file naming; put these with the
other settings/persistence service tests).

1. Add `"sync_disabled_games"` to `SETTINGS_KEYS` in
   `py_modules/sdh_ludusavi/constants.py`.
2. In `py_modules/sdh_ludusavi/service.py`:
   - initialize `self._sync_disabled_games: set[str] = set()` next to
     `self._auto_sync_enabled`;
   - load it in `_load_state` from `settings.get("sync_disabled_games", [])`,
     accepting only non-empty `str` entries and passing each through
     `sanitize_game_name`; ignore any non-list value;
   - emit `"sync_disabled_games": sorted(self._sync_disabled_games)` from both
     `get_settings` and the `_save_state` settings payload;
   - add `set_game_sync_enabled(self, game_name: str, enabled: bool) -> dict[str, Any]`:
     sanitize the name and return `self.get_settings()` unchanged if it is empty;
     otherwise perform a **locked read-modify-write** (see below), log at info
     level (`f"Per-game sync {'enabled' if enabled else 'disabled'} for {name}"`),
     and return `self.get_settings()`;
   - add `is_game_sync_enabled(self, game_name: str) -> bool` returning
     `sanitize_game_name(game_name) not in self._sync_disabled_games`.

`set_game_sync_enabled` must **not** just mutate the in-memory set and call
`_save_state`. `_save_state` writes the service's whole settings snapshot
(`service.py:392`), and Decky's update flow can briefly run two backend instances
against the same file (`py_modules/sdh_ludusavi/persistence.py:27`), so a blind
whole-snapshot write lets one instance discard the other's opt-outs. Re-read
persisted settings under the lock and merge just this game's membership, using
the existing precedent in `reconcile_pending_update_install`
(`service.py:445-459`) — same lock order, state lock then persistence lock:

Do **not** implement this as "mutate the in-memory set, then call `_save_state`".
`_save_state` writes the service's whole settings snapshot (`service.py:392-413`)
from memory, so a read-modify-write built on top of it either writes stale data
or discards the merge, depending on which value wins.

Instead add one atomic settings-only transaction to `PersistenceManager` in
`py_modules/sdh_ludusavi/persistence.py`:

```python
def mutate_settings(
    self, mutator: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any]:
    """Locked read-modify-write over the settings file only."""
```

Under `self._lock`: read via `self._settings_store.read()`, apply `mutator`,
write the result with `self._settings_store.write(...)`, and return it. Three
requirements:

- read, merge, and write all happen inside **one** lock acquisition, so no other
  writer can land between the read and the write;
- it touches settings only — it must not read or rewrite the cache file;
- it must **fail closed**. `_load_all_locked` deliberately downgrades an
  unreadable or invalid settings file to `{}` (`persistence.py:170-176`), which
  is right for startup but catastrophic here: a transient read error would look
  like "no games disabled" and erase every opt-out on the next write. Let
  `OSError` and `json.JSONDecodeError` propagate out of `mutate_settings` rather
  than coercing to `{}`. This repo lives in a Dropbox-synced tree where transient
  read failures are a known hazard, so this is not a theoretical concern.

`set_game_sync_enabled` then:

1. calls `mutate_settings` with a mutator that patches **only** the
   `sync_disabled_games` key of the persisted dict — adding or discarding this
   one sanitized name and leaving every other key exactly as read;
2. adopts the returned list into `self._sync_disabled_games`, so memory matches
   what actually landed on disk;
3. does **not** call `_save_state`;
4. on `StateLockTimeoutError`, `OSError`, or `json.JSONDecodeError`, logs a
   warning, leaves both memory and disk unchanged, and returns
   `self.get_settings()` — mirroring the timeout handling at `service.py:458`.

Leave `_save_state` alone: it keeps writing the in-memory set like every other
setting. A stale sibling instance could in principle still overwrite the field
through an unrelated save, but `enforce_single_instance` (`singleton.py:276`)
terminates stale siblings at startup, the exposure window is the same one that
already exists for every other setting, and step 2 keeps this instance's memory
authoritative. Do not build extra machinery for the residual case.

Test it: the **first** disable on a machine with no settings file persists the
name (this is the exact case a pass-through scheme silently drops); a second
disable preserves the first; re-enabling removes only the named game; a simulated
concurrent writer's opt-out is preserved across a toggle for a different game; a
read error during the transaction leaves the persisted list untouched and does
not erase it; a lock timeout leaves state unchanged and does not raise.

Tests must also cover: default is enabled for an unknown game, and disabling then
re-enabling round-trips through save/load. For a corrupt persisted value,
validation is **per-entry, not
all-or-nothing**: `["Hades", 1, "", None, "   "]` must load as `{"Hades"}`, and a
non-list value (a dict, a string) must load as an empty set. Filter **after**
`sanitize_game_name`, not before — it collapses whitespace and returns `""` for a
whitespace-only name (`py_modules/sdh_ludusavi/game_names.py:1-4`), so a
raw-length check alone would persist an empty opt-out entry.

### Task 2 — Backend lifecycle gating

Tests: the existing lifecycle test module.

1. Add `is_game_sync_enabled: Callable[[str], bool]` to `LifecycleDependencies`
   in `py_modules/sdh_ludusavi/lifecycle.py`, and wire it in `service.py` where
   `is_auto_sync_enabled=lambda: self._auto_sync_enabled` is passed (~line 122)
   as `is_game_sync_enabled=lambda name: self.is_game_sync_enabled(name)`.
2. In `check_game_start`, after `match_game` resolves the game and **before** the
   `has_backup` and `game.error` checks, add:

   ```python
   if not self.dependencies.is_game_sync_enabled(game.name):
       return self.dependencies.skip("start", game.name, "game_sync_disabled")
   ```

   Gate on the registry-canonical `game.name`, not the raw launch name, so the
   key always matches what the QAM dropdown wrote.
3. Add the same guard, in the same position relative to `match_game`, to **all
   four** remaining lifecycle entry points — missing any one leaves a hole:
   - `restore_game_on_start`;
   - `resolve_game_start_conflict`;
   - `check_game_exit`;
   - `backup_game_on_exit` (`lifecycle.py:422`) — do not skip this one. The
     frontend calls check and backup as two separate RPCs
     (`gameLifecycleController.tsx:358` then `:366`), so without this guard a
     game disabled *between* the two calls still gets backed up, and the RPC is
     directly callable regardless. Place the guard after `match_game` and before
     the `game.error` check, matching the others.
4. In `_skip` (`service.py` ~line 487) add `"game_sync_disabled"` to the tuple of
   reasons that do **not** record history. A disabled game is launched
   repeatedly; it must not fill `game_history` with skip entries. The info log
   line still fires.
5. Adding a required field to `LifecycleDependencies` breaks **every** existing
   constructor, not just the lifecycle tests. Update all four call sites so the
   suite stays green, each passing an enabled-by-default callback
   (`is_game_sync_enabled=lambda _name: True`) unless the test is asserting the
   new behavior:
   - `tests/test_lifecycle.py:24`
   - `tests/test_decision_logging.py:125`
   - `tests/test_recency_direction.py:47`
   - `tests/test_backup_browser.py:156`

   Do not weaken the dataclass to a defaulted/optional field to avoid this — an
   explicit dependency is what makes a missed call site a type error.
6. Backend tests that assert an exact settings dict must gain the new key:
   `tests/test_service.py:195`, `:533`, and `:554`. This is a fixture update
   forced by a new field, not a behavior change — do not alter what those tests
   assert about other keys.

Tests must cover, for start, exit, and both second-stage operation RPCs: a
disabled game returns `{"status": "skipped", "reason": "game_sync_disabled"}`; an
enabled game is unaffected; global auto-sync off still returns
`auto_sync_disabled` (the global check wins and runs first); disabling a game
between `check_game_exit` and `backup_game_on_exit` blocks the backup; no history
entry is recorded for the disabled skip.

### Task 3 — RPC surface

1. In `main.py`, add an async `set_game_sync_enabled(self, game_name: str, enabled: bool)`
   following the exact shape of the existing `set_auto_sync_enabled` wrapper
   (same guarded-call helper, same return type).
2. In `src/api/ludusaviRpc.ts`, add:

   ```ts
   export const setGameSyncEnabledCall = callable<
     [gameName: string, enabled: boolean],
     RpcResult<Settings>
   >("set_game_sync_enabled");
   ```

### Task 4 — Frontend settings type, defaults, and store

1. `src/types/index.ts`: add `sync_disabled_games: string[]` to `Settings`.
2. `src/state/ludusaviState.tsx`:
   - add `sync_disabled_games: []` to `defaultSettings()`;
   - in `normalizeSettings`, coerce the field to a string array
     (`Array.isArray(...) ? settings.sync_disabled_games.filter(n => typeof n === "string" && n.length > 0) : []`)
     so a malformed backend payload cannot crash rendering;
   - add `setGameSyncEnabled(gameName: string, enabled: boolean)` that patches
     `sync_disabled_games` (add or remove the name, keep it sorted and unique)
     via the existing `patchSettings` path;
   - add `resolveCanonicalGameName(name: string, appID: string): string | null`
     that mirrors the backend's resolution order in
     `py_modules/sdh_ludusavi/matcher.py:57-90`, run against
     `snapshot.games` and `snapshot.gameAliases`:
     1. `appID` against each game's `steam_id`, compared as
        `String(game.steam_id) === appID` — `steam_id` is typed
        `string | number` (`src/types/index.ts:71-74`) and the existing tracked-ID
        builder already stringifies it (`ludusaviState.tsx:110-116`). A numeric
        `steam_id` must match;
     2. `gameAliases` lookup;
     3. exact `normalize()` match on a game's name;
     4. unique normalized-substring candidate — ambiguous means no match.
     Return the game's canonical `name`, or `null` when nothing resolves.
     Step 4 must also apply the backend's fuzzy eligibility rules, ported from
     `matcher.py:19-33` (`fuzzy_match_allowed`): both sides longer than 4 chars
     passes; otherwise the game must be `configured`, the target exactly 4 chars,
     a prefix of the input, and the next input character one of space, `.`, or
     `-`. Without these rules the resolver accepts short-name matches the backend
     rejects, reintroducing the disagreement this task exists to prevent.
     Cover a numeric `steam_id` and a short-name (≤4 char) case in tests.
   - add `isGameSyncDisabled(name: string, appID: string): boolean` that resolves
     the canonical name first and only then tests membership in
     `sync_disabled_games`. Return `false` when resolution fails.

   Do **not** fuzzy-match the launch name directly against the disabled list.
   The disabled list holds canonical registry names while the backend resolves
   appID → alias → exact → fuzzy, so a direct list match disagrees with the
   backend in both directions: an appID- or alias-only match is missed (frontend
   pauses a game the backend will skip), and with `Hades` disabled, launching
   `Hades II` substring-matches the sole disabled entry — the frontend then skips
   the pause while the backend, resolving by appID, reports a restore is needed.
   `evaluateStartCheck` treats restore-needed-without-a-pause as a failure
   (`gameLifecycleDecision.ts:70`), so that combination silently loses a restore.

   Returning `false` on unresolved names is deliberate: the pause is the safe
   default and the backend remains authoritative for whether sync actually runs.

   Leave `isTracked` alone. Its matching is similar but not identical, and
   refactoring the two into one helper risks changing tracked-game behavior for
   no benefit here.
3. `src/runtime/startupHydration.ts`: add
   `sync_disabled_games_count: settings.sync_disabled_games?.length ?? 0` to the
   `startup_settings_hydrated` log payload. On-device log inspection is the
   primary debugging channel for this plugin, so the count must be visible at
   hydration.

Tests: extend the existing `ludusaviState` and `startupHydration` test modules.
`resolveCanonicalGameName` / `isGameSyncDisabled` need cases for: appID match
where the launch name differs from the canonical name; alias match; exact name
match; the `Hades` disabled / `Hades II` launched false-positive (must report
**not** disabled); an ambiguous substring resolving to `null`; and an empty
`games` list. Also update the typed `Settings` fixtures that a new required field
breaks — at minimum `src/runtime/startupHydration.test.ts:6` and the literal
`Settings` object at `src/state/ludusaviState.test.tsx:95`.

### Task 5 — Frontend settings mutation

In `src/settings/settingsMutationRuntime.ts`, add `toggleGameSync(gameName: string, enabled: boolean)`
modeled directly on `toggleAutoSync` (~line 257):

- **per-game** sequence tracking — a `Map<string, number>` keyed by game name,
  not a single shared counter. Two different games toggled in quick succession
  are independent mutations; a shared counter makes the first one look
  superseded (`settingsMutationRuntime.ts:230`) and its result gets dropped;
- `lastPersistedSyncDisabledGames: string[] | null`, updated inside
  `applySettings` (`settingsMutationRuntime.ts:95`) alongside the other
  persisted-value caches — the plan is not complete without that line;
- `optimisticUpdate: () => ludusaviStore.setGameSyncEnabled(gameName, enabled)`;
- `rpcCall` must refresh the cache itself, because `mutateSetting` only calls
  `applyResult` when the sequence still matches (`settingsMutationRuntime.ts:230`)
  — a superseded success never reaches it, so "update the cache on a superseded
  success" is not implementable through `applyResult`. Wrap the call instead:

  ```ts
  rpcCall: async () => {
    const res = await setGameSyncEnabledCall(gameName, enabled);
    if (!isRpcStatus(res)) lastPersistedSyncDisabledGames = res.sync_disabled_games;
    return res;
  },
  ```

- `getPersistedValue: (res) => res.sync_disabled_games`;
- pass `gameName` through to `mutateSetting` so the existing per-game logging
  path is used, the same way the selected-game mutation does;
- rollback must be **scoped to the toggled game** and must read the cache **at
  failure time**, not use the captured `fallbackValue`:

  ```ts
  rollbackUpdate: () =>
    ludusaviStore.setGameSyncEnabled(
      gameName,
      !(lastPersistedSyncDisabledGames ?? []).includes(gameName),
    ),
  ```

  `fallbackValue` is captured when the mutation is submitted
  (`settingsMutationRuntime.ts:156-175`), before any queued RPC resolves, so
  using it reintroduces same-game divergence: A starts enabled; "disable A"
  succeeds; a rapidly queued "re-enable A" fails and rolls back to the
  pre-first-response value, leaving the UI enabled while the backend has A
  disabled. Reading the cache lazily fixes this because `rpcCall` above updates
  it on every success. Still pass a sane `fallbackValue` for logging, but do not
  consume it in the rollback.

  Never restore a whole cached list on failure — with an uninitialized cache that
  would replace a fully hydrated list with `[]`;
- reset the map and cached value in `dispose()` alongside the others;
- export `toggleGameSync` from the controller object next to `toggleAutoSync`.

Tests: extend `src/settings/settingsMutationRuntime.test.ts`, mirroring the
existing auto-sync cases, covering at minimum:

- optimistic update then success;
- hydration with one game already disabled, then a *failed* toggle for a
  different game — the first game must stay disabled;
- A succeeds while B fails concurrently;
- timeout followed by a late success;
- two different games toggled rapidly, neither superseding the other;
- **the same game toggled rapidly** — disable A succeeds, then a queued re-enable
  A fails; the UI must end disabled, matching the backend.

### Task 6 — QAM toggle UI

In `src/components/qam/GameSettingsSection.tsx`:

- add props `gameSyncEnabled: boolean` and `onToggleGameSync: (enabled: boolean) => void`;
- add a `PanelSectionRow` containing a `ToggleField` **directly below** the
  `Browse Backups` row:
  - label `Sync This Game`;
  - description `Backs up and restores this game automatically. Requires Automatic Sync.`;
  - `checked={gameSyncEnabled}`;
  - `disabled={isBusy || !selectedStatus}` — the toggle is meaningful for any
    resolved game, so it deliberately uses a looser condition than the
    Browse Backups row above it, which additionally requires
    `selectedStatus?.status === "has_backup"` (`GameSettingsSection.tsx:165`);
  - do **not** disable it when global auto-sync is off; the value must remain
    editable and persisted so it applies once auto-sync is switched back on.

In `src/components/qam/LudusaviContent.tsx` (~line 551), pass
`gameSyncEnabled={!(settings.sync_disabled_games ?? []).includes(selectedGame)}`
and `onToggleGameSync={(enabled) => void toggleGameSync(selectedGame, enabled)}`,
destructuring `toggleGameSync` from `settingsController` next to `toggleAutoSync`.

### Task 7 — Launch path must not pause a disabled game

In `src/controllers/gameLifecycleController.tsx` there are **four** gates, not
two. Missing the last two leaves a disabled game starting Syncthing watches.

In `handleAppStart` (~line 159):

1. after `const autoSyncEnabled = ...` compute
   `const gameSyncDisabled = ludusaviStore.isGameSyncDisabled(name, appID);`
   (pass both arguments — see Task 4);
2. gate the pause:
   `const shouldPauseLaunch = autoSyncEnabled && !gameSyncDisabled && guardCandidate && ...`;
3. gate the initial pre-game watch: `if (autoSyncEnabled && !gameSyncDisabled && guardCandidate)`;
4. gate the pre-game watch **restarted after conflict resolution** at
   `gameLifecycleController.tsx:272` (`if (autoSyncEnabled && guardCandidate)`
   inside the `if (resolution)` block).

In `handleAppExit` (~line 325):

5. gate the post-game watch at `gameLifecycleController.tsx:336`
   (`if (autoSyncEnabledExit) { ... syncthingMonitor.start("post_game", ...) }`)
   with the same per-game check.

For gates 4 and 5, re-evaluate `ludusaviStore.isGameSyncDisabled(name, appID)`
fresh rather than reusing a value captured at launch — conflict resolution can
sit open for minutes, and exit is a separate handler entirely.

Log the decision at info level in the existing style: append
`game_sync_disabled=${gameSyncDisabled}` to the `App started:` line and the
equivalent to the `App exited:` line.

Mind the declaration order. Both log lines currently sit **above** the
auto-sync reads — `App started:` at `gameLifecycleController.tsx:176` with
`autoSyncEnabled` at `:182`, and `App exited:` at `:327` with
`autoSyncEnabledExit` at `:329`. Move the `isGameSyncDisabled` call above each
log line rather than leaving it where this plan first mentions it; do not
reference the variable before it is declared.

The `checkGameStart` / `checkGameExit` RPCs still run — the backend skip is what
drives the status bar. Only the SIGSTOP pause and the Syncthing watches are
skipped.

Tests: extend `src/controllers/gameLifecycleController.test.ts` with cases
asserting that a game in `sync_disabled_games` produces no pause RPC, no pre-game
watch, no post-game watch on exit, and no watch restart after conflict
resolution, while the same game with sync enabled still does all four.

The shared store mocks in `src/controllers/gameLifecycleController.test.ts:31`
and `src/controllers/gameLifecycleController.logging.test.ts:35` expose only
`isTracked` and `shouldPublishAutoSyncStatusBeforeRpc`. Calling
`isGameSyncDisabled` unconditionally will throw in every existing test in both
files until those mocks gain the method — update them as part of this task.

### Task 8 — Status bar surface

1. `src/types/index.ts`: add `"game_sync_disabled"` to `AutoSyncStatusKind`.
2. `src/surfaces/autoSyncStatusRenderer.tsx`:
   - add `game_sync_disabled: "SAVE SYNC DISABLED FOR THIS GAME"` to
     `autoSyncStatusText`;
   - add an `iconSvgForAutoSyncStatus` branch returning a filled circle with a
     diagonal slash cut in `#0b151f`, matching the 20x20 `viewBox` and
     `currentColor` conventions of the neighbouring icons;
   - add `game_sync_disabled` to the amber (`#f59e0b`) group in the `.icon`
     colour ternary in `renderAutoSyncStatusHtml`;
   - leave `isLudusaviRunningStatus`, `isSyncthingActiveStatus`, and
     `shouldAutoHideStatus` untouched — the new status must auto-hide, which is
     already the default for anything that is not `conflict` or a Syncthing
     active status. Assert that in a test rather than changing the function.
3. `src/surfaces/autoSyncStatusSurface.tsx`, in `complete()` (~line 299): inside
   the `result.status === "skipped"` branch, before the `unknown` fallback,
   handle `result.reason === "game_sync_disabled"`:
   - when `options.lifecycle === "lifecycle_start"`, publish
     `game_sync_disabled`, following the shape of the adjacent
     `conflict_unresolved` case;
   - otherwise call `api.hide({ ...options, source: "hide" })` and return.
     Returning silently is **not** sufficient: the exit handler publishes
     `checking` before `check_game_exit` (`gameLifecycleController.tsx:342-343`),
     and a running status stays visible until the auto-hide ceiling
     (`autoSyncStatusSurface.tsx:102-131`). Without an explicit hide, quitting a
     disabled game leaves `VERIFYING GAME SAVE` on screen for minutes — the
     opposite of the intended behavior.
4. Also suppress the pre-check publish at its source. In `handleAppExit`, skip
   the `publishAutoSyncStatus("checking", ...)` call at
   `gameLifecycleController.tsx:342` when the frontend already resolves the game
   as disabled, so the bar never flashes. Keep the hide in step 3 regardless —
   it is the backstop for the case where frontend resolution misses and only the
   backend knows the game is disabled.

   The lifecycle check is required, not optional. `check_game_exit` returns the
   same reason and `evaluateExitCheck` forwards non-silent skips to
   `completeStatus` (`gameLifecycleDecision.ts:160,176`), so without it the bar
   also appears every time you quit a disabled game. There is precedent for
   branching on `options.lifecycle` in this function at
   `autoSyncStatusSurface.tsx:264`. Test both lifecycles.
5. `src/controllers/gameLifecycleDecision.ts`: do **not** add
   `game_sync_disabled` to `SILENT_SKIPPED_REASONS`. Add a test asserting it is
   absent, so a future edit cannot silently suppress the banner.

Tests: extend the existing `autoSyncStatusSurface` and renderer tests to cover
the new mapping, the rendered text, and auto-hide behavior.

### Task 9 — Documentation

Update `README.md` where the `Automatic Sync` behavior is described: document the
per-game `Sync This Game` toggle, that it defaults to on, that it blocks both
launch restore and exit backup, that it has no effect while global Automatic Sync
is off, and that a disabled game shows a brief in-game notice at launch.

Record the session log under `docs/agent_conversations/` per the repo protocol.

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
pnpm test
pnpm run build
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

`scripts/orchestration/run-quality-gates` runs exactly this set via
`scripts/orchestration-hooks/quality-gates`; running the gate script is
sufficient. Expected: every command exits 0, with new tests present for each of
Tasks 1, 2, 4, 5, 7, and 8.

Tasks 2 and 4 add required fields that break existing constructors and fixtures
across eight test files. Those updates belong in the same commit as the field
that forces them — a commit that leaves the suite red is not a complete task.

Targeted checks to confirm before marking the round complete:

1. `git grep -n "game_sync_disabled"` shows the reason at **five** `lifecycle.py`
   call sites (`check_game_start`, `restore_game_on_start`,
   `resolve_game_start_conflict`, `check_game_exit`, `backup_game_on_exit`), the
   `_skip` non-recording tuple in `service.py`, `AutoSyncStatusKind`,
   `autoSyncStatusText`, and the `complete()` mapping in
   `autoSyncStatusSurface.tsx` — and **not** in `SILENT_SKIPPED_REASONS`.
2. `git grep -n "sync_disabled_games"` shows the key in `SETTINGS_KEYS`,
   `get_settings`, `_load_state`, `_save_state`, the `Settings` TS type,
   `defaultSettings()`, and `normalizeSettings`.
3. A settings file written by the new code contains a sorted, de-duplicated
   `sync_disabled_games` array, and an old settings file with no such key loads
   with every game enabled.

Deferred verification — cannot be done in this environment, state it explicitly
in the session log rather than claiming it passed:

- On-device Steam Deck run: the `Sync This Game` toggle renders below
  `Browse Backups`, persists across a plugin reload, and reflects the selected
  game when the dropdown changes.
- On-device launch of a disabled game with global Automatic Sync on: the
  `SAVE SYNC DISABLED FOR THIS GAME` bar appears briefly and auto-hides, the game
  is not visibly paused at launch, and no restore runs.
- On-device exit of a disabled game: no backup runs, no post-game Syncthing watch
  starts (check the logs for the absence of a `post_game` watch start), no new
  `game_history` entry is recorded, and **no status bar appears at all** — no
  disabled notice, and no leftover `VERIFYING GAME SAVE` bar lingering after the
  quit. The notice is start-only.
- On-device launch of a game whose Steam name differs from its Ludusavi name
  (appID or alias resolution), and of a game whose name is a substring of a
  disabled game's name: the first is correctly treated as disabled, the second is
  not.
- On-device: disable a game, force-quit Steam or reload the plugin, and confirm
  the opt-out survived; then toggle a second game and confirm the first is still
  disabled.
- On-device launch with global Automatic Sync off: no bar appears for a disabled
  game, confirming the per-game toggle has no effect in that state.
- Plugin logs at `/home/deck/homebrew/logs/SDH-Ludusavi` show the
  `sync_disabled_games_count` field in `startup_settings_hydrated` and the
  `game_sync_disabled=` field on the `App started:` line.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished per-game-sync-toggle
```

This writes:

```text
/tmp/sdh_ludusavi/per-game-sync-toggle_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer per-game-sync-toggle`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/per-game-sync-toggle-review-*.md
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
   scripts/orchestration/clear-finished per-game-sync-toggle
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
   git add docs/review/per-game-sync-toggle-review-*.md
   git commit -m "docs(review): record per-game-sync-toggle review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished per-game-sync-toggle
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer per-game-sync-toggle` after the next review note is created.

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
   scripts/orchestration/check-review-notes-committed per-game-sync-toggle
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize per-game-sync-toggle
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/per-game-sync-toggle_finalized
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
scripts/orchestration/finalize per-game-sync-toggle
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/per-game-sync-toggle_finished
/tmp/sdh_ludusavi/per-game-sync-toggle_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
