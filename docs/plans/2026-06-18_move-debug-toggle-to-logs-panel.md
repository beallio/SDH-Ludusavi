# Move Debug Logging Toggle to the Logs Panel

```text
TITLE=Move Debug Logging Toggle to the Logs Panel
SLUG=move-debug-toggle-to-logs-panel
PLAN_PATH=docs/plans/2026-06-18_move-debug-toggle-to-logs-panel.md
BRANCH=feat/move-debug-toggle-to-logs-panel
```

## Context

The `Debug Logging` toggle currently sits in the **GLOBAL** panel
(`src/components/qam/AutoSyncSettingsSection.tsx`), next to `Automatic Sync` and
`Refresh Games`. It is a logging/diagnostics control, so it belongs with the other
logging actions in the **Logs** panel (`LogsSection` in
`src/components/qam/VersionAndLogsSection.tsx`, alongside "View Logs" / "View Ludusavi
Logs"). This is a pure UI relocation: the setting, persistence, RPC, hydration, and the
`toggleDebugLogging` mutation are unchanged — only the rendered location and its prop
wiring move.

## Scope

Frontend only. No backend, settings-store, RPC, type, or state changes. The
`debug_logging` setting and `set_debug_logging` RPC stay exactly as they are.

## Execution Rules

- Use the `implementer` skill for the implementation.
- Develop on branch `feat/move-debug-toggle-to-logs-panel`, created off `dev`. Do not
  commit to `dev` directly until finalization.
- This plan is your only instruction source. Do not write your own review. Do not create or
  delete files under `docs/review/`.
- Follow the repo protocol in `CLAUDE.md`: conventional commits, caches under
  `/tmp/sdh_ludusavi`, all backend tooling through `./run.sh`. This change is UI-only and
  TypeScript-compiler/build-guarded (see Testing strategy); no new test is required, but the
  full quality gates must pass.
- Record a session log under `docs/agent_conversations/` after implementation.
- Steam Deck / on-device testing is deferred until after the dev push.

## Changes

### 1. `src/components/qam/VersionAndLogsSection.tsx` — add the toggle to `LogsSection`
- Import `ToggleField` from `@decky/ui` (currently imports `ButtonItem, Field,
  PanelSection, PanelSectionRow`).
- Extend `LogsSectionProps` with:
  - `debugLogging: boolean`
  - `isBusy: boolean`
  - `onToggleDebugLogging: (enabled: boolean) => void`
  Pass these primitives rather than the whole `Settings` object to keep the section
  decoupled (it does not import `Settings` today).
- Render a new `PanelSectionRow` with the `ToggleField` after the two log buttons:
  ```tsx
  <PanelSectionRow>
    <ToggleField
      label="Debug Logging"
      description="Enables verbose logging for troubleshooting."
      bottomSeparator="none"
      checked={debugLogging}
      disabled={isBusy}
      onChange={(enabled: boolean) => onToggleDebugLogging(enabled)}
    />
  </PanelSectionRow>
  ```
- Separator tidy-up: the toggle is now the last item in the panel, so it uses
  `bottomSeparator="none"`. Leave `View Ludusavi Logs` at `bottomSeparator="standard"`
  so there is a visual divider between the log-view actions and the setting.

### 2. `src/components/qam/AutoSyncSettingsSection.tsx` — remove the toggle
- Delete the `Debug Logging` `PanelSectionRow`.
- Remove `onToggleDebugLogging` from `AutoSyncSettingsSectionProps` and from the
  destructured params.
- Leave `Automatic Sync` (`bottomSeparator="none"`) and `Refresh Games` as-is.

### 3. `src/components/qam/LudusaviContent.tsx` — move the wiring
- In the `<AutoSyncSettingsSection ... />` element (~line 797), remove the
  `onToggleDebugLogging={(enabled) => void toggleDebugLogging(enabled)}` prop.
- In the `<LogsSection ... />` element (~line 839), add:
  ```tsx
  debugLogging={settings.debug_logging}
  isBusy={isBusy}
  onToggleDebugLogging={(enabled) => void toggleDebugLogging(enabled)}
  ```
- `toggleDebugLogging` is already destructured from `settingsController` — keep it; it is
  now consumed by `LogsSection` instead of `AutoSyncSettingsSection`.

## Testing strategy

No existing test asserts the toggle's panel placement (only
`src/runtime/startupHydration.test.ts` references `debug_logging`, for hydration, and is
unaffected). The move is JSX relocation plus prop threading, so correctness is enforced by
the TypeScript compiler (prop types) and the build.

- Required gates: `pnpm run typecheck` (catches any prop mismatch from the moved props)
  and `pnpm run test:unit` (must stay green), plus `pnpm run build`.
- There is currently no React render-test harness for these QAM sections, so no
  component-render test is added. If one is introduced later, add a small assertion that
  `LogsSection` renders a "Debug Logging" toggle and `AutoSyncSettingsSection` does not.

## Verification

1. `pnpm run typecheck` — clean (this is the primary guard for the prop move).
2. `pnpm run test:unit` — 198 tests still pass.
3. `pnpm run build` — succeeds.
4. Manual/visual (deferred to on-device): the `Debug Logging` toggle appears in the
   **Logs** panel under the log-view buttons, no longer in **GLOBAL**, and toggling it
   still calls `set_debug_logging` (unchanged behavior).

## Risks

- Minimal. The only failure mode is a prop wiring mismatch, which `tsc` catches. Watch the
  `bottomSeparator` values so the Logs panel keeps a clean divider layout.
- Backend quality gates (`ruff`/`ty`/`pytest`) are unaffected but should still pass since
  the pre-commit hook runs them.

## Commit

Single atomic commit:
`refactor(ui): move Debug Logging toggle from GLOBAL panel to Logs panel`

## Orchestration Contract

Plan path:
```text
docs/plans/2026-06-18_move-debug-toggle-to-logs-panel.md
```
Implementation branch:
```text
feat/move-debug-toggle-to-logs-panel
```
Round-complete marker:
```text
/tmp/sdh_ludusavi/move-debug-toggle-to-logs-panel_finished
```
Finalized marker:
```text
/tmp/sdh_ludusavi/move-debug-toggle-to-logs-panel_finalized
```
Review notes:
```text
docs/review/move-debug-toggle-to-logs-panel-review-*.md
```
Each review note ends with exactly one of `STATUS: CHANGES_REQUESTED` or `STATUS: APPROVED`.

### On completing an implementation/review round
1. Run the quality gates (`./run.sh` backend suite + `pnpm run test` + `pnpm run typecheck`).
2. Ensure the working tree is clean.
3. Commit all relevant changes.
4. Write the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished move-debug-toggle-to-logs-panel
   ```
Then exit cleanly. Do not poll in-session; the orchestrator resumes you with
`scripts/orchestration/continue-implementer move-debug-toggle-to-logs-panel` once the next
review note is committed. On resume, scan existing committed review notes first and read the
latest note's committed content (e.g. `git show HEAD:docs/review/...`).

### When the latest committed review note is `STATUS: CHANGES_REQUESTED`
1. Clear the marker: `scripts/orchestration/clear-finished move-debug-toggle-to-logs-panel`
2. Implement every requested change.
3. Run quality gates.
4. Commit the fixes.
5. Commit the review note if not already committed.
6. Recreate the marker: `scripts/orchestration/mark-finished move-debug-toggle-to-logs-panel`
7. Exit cleanly.

### When the latest committed review note is `STATUS: APPROVED`
1. Confirm all review notes are committed and the working tree is clean.
2. Finalize: `scripts/orchestration/finalize move-debug-toggle-to-logs-panel`
3. Confirm `/tmp/sdh_ludusavi/move-debug-toggle-to-logs-panel_finalized` exists, then exit.

Finalization merges the working branch into `dev`, cleans up the branch, pushes `dev`, and
requests a dev release via the project release script. Steam Deck/user testing is deferred
until after the dev push.

> Review notes are durable audit records and must be committed. Do not write your own review
> and do not create or delete files under `docs/review/`.
