# Review — accepted-overengineering-simplifications (round 08)

Branch: `feat/accepted-overengineering-simplifications`
Reviewed against: `docs/plans/2026-08-18_accepted-overengineering-simplifications.md`

## Verdict

The three round-07 cleanups landed correctly in `7c3c78c`, and Task 8 in `3ec945a` matches its
specification item for item. One coverage gap remains: `stop_all()` no longer has a test proving
it stops every registered watch, which is precisely the behavior Task 8 was told to preserve.

Close that gap and proceed with Task 9 only in the next implementation round.

## Gate status

- Reviewed branch commit: `3ec945a5bf93c8d7f2f31ce15826ee4c1d5f168b`.
- Working tree was clean and the round marker was valid at the reviewed commit.
- Independent focused backend run: 298 tests passed across `tests/test_watcher.py`,
  `tests/test_service.py`, and `tests/test_activity.py`.
- Independent `ty check py_modules/sdh_ludusavi/`: all checks passed.
- Independent `vitest run src/settings/settingsMutationRuntime.test.ts
  src/state/ludusaviState.test.tsx`: 28 tests passed across 2 files.
- Independent `pnpm run typecheck`: clean.
- RED evidence verified: the `[debug]` case of
  `test_debug_logging_does_not_change_watch_stop_semantics` fails against the pre-change watcher
  with `{'status': 'observing'} != {'status': 'stopped'}`, while the `[info]` case passes.
- Negative control verified against the same assertion and the same failure signature.

## Round-07 cleanups confirmed

1. `SDHLudusaviService.set_update_channel` and `set_automatic_update_checks` are gone, and so are
   the now test-only `PluginUpdater.set_channel`, `set_automatic_checks`, and `load_state`. The
   updater tests were migrated onto `adopt_persisted_settings` and `adopt_persisted_cache`, so the
   second persistence route for updater preferences no longer exists. Production reaches the
   updater only through the adoption path; `_save_callback` survives for cache persistence only,
   which is correct.
2. The empty-game-name guard is restored, and its placement is right: the early return runs after
   `_patch_game_name`, so a non-string `game_name` still raises `ValueError` while a name that
   sanitizes to empty returns the current settings without touching the persisted document.
3. `dispose()` no longer resets `nextSequence`, and the added test genuinely covers the window —
   with the reset in place the pre-dispose mutation would reclaim sequence 1 for the `auto_sync`
   key and clobber the newer value.

## Task 8 confirmed

- Removed exactly what the plan named: the `debug_logging` constructor flag, the
  `_on_observation_finished` and `_released_for_observation` state, `begin_released_observation`,
  `_deregister_finished_debug_observation`, the alternate completion branch,
  `is_debug_extending_peer_completion`, `_observing_watches`, and
  `_deregister_finished_observation`.
- `stop_watch` now stops and joins unconditionally and returns
  `{"status": "stopped", "watch_id": ...}` with no `observing` path.
- `stop_all()` snapshots with `list(self.watches.values())` before `clear()` and stops every watch
  outside the manager lock.
- `SDHLudusaviService.start_syncthing_watch` no longer threads `debug_logging` through.
- The peer-completion latch keeps its sanitized transition-only INFO line, with the
  `debug_observation_selected` field dropped along with the behavior it described.
- Sanitization coverage is intact: the event-subscription reset, completion-initialization
  failure, malformed-completion-event, unchanged-outbound-need, and both probe-failure tests all
  survive.
- The accepted tradeoff is recorded in the commit body: delete-pruning is no longer observed after
  the frontend releases a completed watch.

## Required changes

1. Restore multi-watch coverage for `stop_all()`. The deleted
   `test_manager_stop_all_stops_debug_extended_and_normal_watches` was the only test asserting that
   `stop_all()` stops more than one registered watch and empties the registry. What remains is
   `test_stop_all_does_not_hold_lock_while_joining`, which registers a single watch and asserts
   only the lock-release property. Add a test that registers two watches, calls `stop_all()`, and
   asserts both `stop()` calls happened and `manager.watches` is empty afterward. This is the
   snapshot-before-clear behavior the plan explicitly asked Task 8 to preserve, so it must not rest
   on the lock test alone.

2. Implement Task 9, "Strengthen the evaluated TypeScript boundaries," and no later task in this
   round. Inventory production `any` occurrences before editing, clear them from exactly the eleven
   listed files, and do not widen into `src/utils/steam.ts`, `steamRuntime.ts`, launcher casts,
   lifecycle command casts, browser-view shims, or global declaration files. Make the RPC-status
   callbacks real type predicates rather than casts, use `unknown` for caught values and the unused
   Decky installer response, and use the browser timer return type. Runtime behavior must not
   change.

3. Record both the scoped and repository-wide `any` counts before and after. The validated scoped
   target is 31 to zero and the repository-wide production target is 86 to 54; report the actual
   numbers and explain any drift with file-level evidence rather than adjusting the target.

4. Run the focused suites the plan lists for Task 9 plus the full gates. Commit the `stop_all`
   test as its own small `test(syncthing):` commit, then commit Task 9 separately as
   `refactor(types): strengthen frontend boundaries`. Write a new round-complete marker as the last
   action of the round.

STATUS: CHANGES_REQUESTED
