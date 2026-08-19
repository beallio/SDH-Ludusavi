# Review — accepted-overengineering-simplifications (round 07)

Branch: `feat/accepted-overengineering-simplifications`
Reviewed against: `docs/plans/2026-08-18_accepted-overengineering-simplifications.md`

## Verdict

Task 7 is implemented and meets every validated target, with three residual cleanups that must
land before Task 8 proceeds. The seven setting-specific RPCs are gone from the frontend, the
public plugin, and the compatibility expectations; one `update_settings` entry point replaces
them; the backend merges each patch against the latest on-disk settings document while holding
the service state lock; and updater preferences travel the same path.

Proceed with the three required cleanups below and Task 8 only in the next implementation round.

## Gate status

- Reviewed branch commit: `01d708ed1aea3f9c2351c50db6733d703f4ce643`.
- Working tree was clean and the round marker was valid at the reviewed commit.
- Independent focused backend run: 180 tests passed across `tests/test_service.py`,
  `tests/test_main.py`, and `tests/test_compatibility.py`.
- Independent `ty check py_modules/sdh_ludusavi/`: all checks passed.
- Independent `vitest run src/settings/settingsMutationRuntime.test.ts
  src/state/ludusaviState.test.tsx`: 27 tests passed across 2 files.
- Independent `pnpm run typecheck`: clean.
- Independent review-note deletion check passed.

## Verified counts

- Setting RPC definitions: 7 to 1 (`updateSettingsCall`); no frontend source references any
  removed name.
- Public plugin RPCs: 41 to 35 (`^    async def [a-z]` in `main.py`), matching the plan target.
- Mutable workflow values in `settingsMutationRuntime.ts`: 20 to 6 (`settingsQueue`,
  `latestSequenceByKey`, `settingsProcessing`, `nextSequence`, `persistedSettings`,
  `lastQueuedSelectedGame`).
- Runtime line count: 535 to 346, matching the approximate target exactly.

## Verified behavior

- `SDHLudusaviService.update_settings` validates `kind` and every field before mutating, raises
  `ValueError` on malformed input, and performs the merge inside
  `self._state_lock` -> `self._persistence.mutate_settings(...)`, so the patch is applied to the
  freshly read on-disk document rather than to stale in-memory state.
- The state lock is an `RLock`, so the nested `PluginUpdater.adopt_persisted_settings` acquisition
  inside `_adopt_persisted_settings` does not deadlock.
- Cross-instance merging is covered: two service instances writing different fields both survive,
  and the reload assertion confirms persistence.
- Persistence errors now propagate instead of being swallowed, which is the fail-closed behavior
  the plan asked for and is what makes frontend rollback correct.
- Frontend semantics are covered by name: per-key supersession (including a second case for
  `update_channel`), timeout rollback, late success after rollback, late resolution applying only
  its owned field, per-game isolation, same-game failure recovery, displayed-game preservation on
  both auto-sync and game-sync results, and the no-busy-label-flicker regression.
- The failure notifier survived the move out of `src/index.tsx`: `LudusaviContent.tsx` supplies
  `notifyFailure` to `createController`, and the queue and sequence map remain runtime-scoped
  rather than per-component.

## Required changes

1. Delete the two now-unreachable service helpers. `SDHLudusaviService.set_update_channel` and
   `SDHLudusaviService.set_automatic_update_checks` have zero callers in production code and zero
   callers in tests; the only surviving mentions of those names are the frontend denylist in
   `tests/test_compatibility.py`. The plan permits helpers to remain "only where backend-internal
   tests/behavior still require them," and nothing requires these two. Removing them also removes
   the second persistence route for updater preferences, since `PluginUpdater.set_channel` and
   `set_automatic_checks` persist through `_save_callback` (whole settings plus cache) while the
   patch path persists through `mutate_settings`. Decide deliberately whether the now test-only
   `PluginUpdater.set_channel`, `set_automatic_checks`, and `load_state` stay or go, and say which
   in the commit body; production reaches the updater only through `adopt_persisted_settings` and
   `adopt_persisted_cache` now.

2. Restore the empty-game-name guard lost in the `game_sync` branch. The previous
   `set_game_sync_enabled` returned early when `sanitize_game_name` produced an empty string. The
   new branch adds that empty string to the disabled set and writes it into
   `sync_disabled_games` on disk. In-memory state stays clean because
   `_coerce_sync_disabled_games` discards empties on adoption, so the damage is confined to a
   stray `""` entry in the persisted document, but the guard should not have been dropped. Add a
   backend test that a `game_sync` patch whose name sanitizes to empty leaves the persisted list
   unchanged, then reinstate the guard.

3. Close the sequence-reuse window in `dispose()`. `dispose()` sets `nextSequence = 0` while
   in-flight mutations still hold their old sequence numbers. A mutation that was in flight across
   a dispose can be treated as latest again once a new mutation for the same key is issued the
   same sequence number, and its result will then be written into the new store. The prior runtime
   guarded this with `mutationGeneration`; the per-key sequence map alone does not. Either leave
   `nextSequence` monotonic across `dispose()` or carry a generation stamp on `QueuedMutation` and
   check it in `isLatest`. Add a frontend test that a mutation in flight at dispose time cannot
   apply after a new same-key mutation is issued.

4. After the cleanups above, implement Task 8, "Make debug logging observational for Syncthing,"
   and no later task in this round. Write the parameterized INFO/DEBUG release test first and
   capture the RED difference before touching the watcher, and record the accepted tradeoff that
   delete-pruning is no longer observed after the frontend releases a completed watch.

5. Run all focused and full gates. Commit the three cleanups as their own atomic commit under a
   `refactor(settings):` or `fix(settings):` subject, then commit Task 8 separately as
   `refactor(syncthing): keep debug logging observational`. Write a new round-complete marker as
   the last action of the round.

STATUS: CHANGES_REQUESTED
