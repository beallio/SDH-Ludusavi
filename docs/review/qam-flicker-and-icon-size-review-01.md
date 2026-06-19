# Review — qam-flicker-and-icon-size (round 01)

Branch: `feat/qam-flicker-and-icon-size`
Reviewed against: `docs/plans/2026-06-15_qam-flicker-and-icon-size.md`
Commit reviewed: `a272313` (tip)

## Verdict

APPROVED on the first round. Both units are implemented exactly to plan, with
test-first coverage, gates green, scope respected, and no out-of-scope changes.

## Unit 1 — toggle flicker

- `src/settings/settingsMutationRuntime.ts`: removed only the busy *reporting*
  (`markBusy()`/`"Updating settings"`, `getQueueBusy`, `subscribeQueue`,
  `notifyQueueListeners`, `queueListeners`); `setBusyLabel`/`isMounted` are now
  optional. The serial queue (`settingsQueue`, `processSettingsQueue`,
  `enqueueSettingsUpdate`), the per-setting sequence counters, `lastPersisted*`
  rollback, and `withTimeout` are all preserved — verified by grep.
- `src/components/qam/LudusaviContent.tsx`: removed the `queueBusy` state and the
  `subscribeQueue` effect; `isBusy` is now
  `operation.is_running || busyLabel !== null || backgroundRefreshBusy` (no
  settings-write transient). Since `"Updating settings"` is no longer set,
  `busyLabel` only reflects real operations, so controls still disable during
  load/refresh/backup/restore but no longer flash on a settings write.
- Tests: added `"settings writes do not trigger a disabling busy label (flicker
  regression)"` (spies `setBusyLabel`, asserts it is never called with `"Updating
  settings"` / never called at all). The rollback and supersede tests are kept.
  The three removed tests (`busy-flag lifecycle`, `two runtimes isolated`,
  `dispose clears + notifies false`) only exercised the deleted busy-reporting
  API — a legitimate removal, not masking a behavior change.

## Unit 2 — status-strip icons

- `src/surfaces/autoSyncStatusRenderer.tsx`: `.icon` 18px → 22px and added
  `.icon svg { width: 100%; height: 100%; display: block; }` so the single
  `.icon` size scales every icon uniformly (also normalizes the Unit-E inlined
  `syncthing_complete` icon). BrowserView bounds left unchanged (judged no clip).
- Test: `"renders a 22px filling icon box"` asserts both CSS rules in the rendered
  HTML.

## Gate status (independently re-run on `a272313`)

- `pytest` — 591 passed, coverage 85.97% (backend untouched).
- `pnpm test` — 20 files, 188 tests passed; `tsc --noEmit` clean.
- `pnpm run build` — rollup build succeeded.
- `ruff check` / `ty check` — passed.
- Working tree clean; review notes intact.

## Prior findings

None — first review round, approved directly.

## Non-blocking notes (no change required)

- `setBusyLabel`/`isMounted` are now optional-but-unused controller params; fine
  to leave, could be dropped in a future cleanup.
- The 22px icon vs. the strip height is the one thing tests can't confirm —
  validate on-device after the dev push (and that toggles no longer flicker).

## Finalization instructions

```bash
scripts/orchestration/check-review-notes-committed qam-flicker-and-icon-size
git status --short
scripts/orchestration/finalize qam-flicker-and-icon-size
```

Confirm `/tmp/sdh_ludusavi/qam-flicker-and-icon-size_finalized` exists, then stop
polling and exit cleanly. Steam Deck / user testing is deferred until after `dev`
is pushed and the dev release is requested.

STATUS: APPROVED
