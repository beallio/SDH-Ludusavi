# QAM UI Cleanup

## Problem Definition

The Quick Access Menu panel currently groups global sync controls, game-specific controls, and status rows under a single `Sync` panel. The plugin icon still uses a generic `react-icons` database backup icon, the title markup uses Decky's title class, and several rows do not opt into Decky's native full-row focus behavior.

## Architecture Overview

This change is frontend-only in `src/index.tsx`. It keeps backend RPC contracts, settings schema, and dependencies unchanged while reorganizing the existing React panel markup into clearer `GLOBAL` and `GAME` sections. Static frontend tests in `tests/test_frontend_static.py` guard the QAM layout and UI primitives.

## Core Data Structures

No backend or persisted data structures change. Existing frontend structures continue to drive the UI:

- `Settings` for automatic sync and notification toggles.
- `GameStatus` and `GameOperationHistory` for selected-game status and last operation.
- `Versions` for the version panel rows.

## Public Interfaces

No RPC methods or public backend interfaces change. The user-visible panel order changes to:

1. `GLOBAL`: Automatic Sync and Refresh Games.
2. `GAME`: game dropdown, current status, last operation, Force Backup, Force Restore.
3. `Notifications`
4. `Ludusavi`
5. `Logs`
6. `Versions`

The QAM plugin icon becomes a local inline React SVG component named `PluginIcon`. It
uses `1em` width and height so Decky's plugin list sizes it like the prior
`react-icons` component instead of rendering the raw SVG viewport at an oversized
default.

Follow-up visual refinements:

- Increase the last-operation value and timestamp text for readability.
- Wrap `ToggleField` rows in a local full-width container because the installed
  `@decky/ui` `ToggleField` type does not expose `className` or `style` props.
- Use scoped CSS to expand the toggle focus background to the QAM panel edges.

## Dependency Requirements

No dependency changes are required. The implementation uses existing Decky UI exports, including `Field`, `ToggleField`, and existing button/dropdown components.

## Testing Strategy

Follow red-green-refactor:

- Add static assertions for the new `GLOBAL` and `GAME` sections and removed `Sync` section.
- Assert the inline `PluginIcon` replaces `LuDatabaseBackup`.
- Assert focusable/full-row Decky primitives are used for toggle, status, last-operation, and versions rows.
- Assert last-operation layout uses no-wrap ellipsis safeguards.
- Assert last-operation value text uses the larger 14px size.
- Assert `PluginIcon` uses `1em` dimensions.
- Assert toggles are wrapped in the full-width focus container and scoped CSS.
- Assert version rows are ordered as `SDH-ludusavi`, `Ludusavi`, `pyludusavi`, `Decky`.
- Assert `titleView` no longer uses `staticClasses.Title`.

Final validation uses:

- `./run.sh uv run ruff check . --fix`
- `./run.sh uv run ruff format .`
- `./run.sh uv run ty check py_modules/sdh_ludusavi/`
- `./run.sh uv run pytest`
- `./run.sh pnpm run typecheck`
- `./run.sh pnpm run verify`
