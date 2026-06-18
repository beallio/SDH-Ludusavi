# Review — move-debug-toggle-to-logs-panel (round 01)

Branch: `feat/move-debug-toggle-to-logs-panel`
Reviewed against: `docs/plans/2026-06-18_move-debug-toggle-to-logs-panel.md`

## Verdict

Approved. The change matches the plan exactly and is a clean, self-contained UI move.

- `src/components/qam/VersionAndLogsSection.tsx`: imports `ToggleField`; `LogsSectionProps`
  extended with `debugLogging`, `isBusy`, `onToggleDebugLogging`; the `Debug Logging`
  `ToggleField` renders in the **Logs** panel after the two log-view buttons as the last item
  (`bottomSeparator="none"`), with `View Ludusavi Logs` kept at `bottomSeparator="standard"`
  as the divider — exactly as specified.
- `src/components/qam/AutoSyncSettingsSection.tsx`: the `Debug Logging` row and the
  `onToggleDebugLogging` prop are removed; `Automatic Sync` and `Refresh Games` unchanged.
  `settings` and `ToggleField` are still used (by `Automatic Sync`), so no dead imports/props.
- `src/components/qam/LudusaviContent.tsx`: the prop is removed from `<AutoSyncSettingsSection>`
  and added to `<LogsSection>` (`debugLogging={settings.debug_logging}`, `isBusy`,
  `onToggleDebugLogging`); `toggleDebugLogging` was already in scope and is now consumed there.

No backend, settings-store, RPC, type, state, or hydration changes — `debug_logging` and
`set_debug_logging` are untouched, as intended.

## Gate status

Independently verified on the current tree:
- `pnpm run typecheck` (`tsc --noEmit`) — clean (primary guard for the prop move).
- `pnpm run test:unit` — 198 passed (20 files).
- `pnpm run build` — succeeds.
- Backend sanity (unaffected): `ruff check .` clean, `pytest` 601 passed.

## Required changes

None. Proceed to finalization: merge `feat/move-debug-toggle-to-logs-panel` into `dev`, clean
up the branch, push `dev`, and request a dev release per the plan. Steam Deck / on-device
verification of the toggle's new placement is deferred until after the dev push.

STATUS: APPROVED
