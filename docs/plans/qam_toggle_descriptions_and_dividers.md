# QAM Toggle Descriptions And Divider Cleanup

## Problem Definition

The QAM panel toggles need short explanatory helper text so their scope is clear on
Steam Deck. The panel also shows default Decky horizontal separators in places where
they visually cut through compact controls, including the selected game/status area,
log buttons, and versions row.

## Architecture Overview

This is a frontend-only QAM presentation change in `src/index.tsx`. It uses Decky's
existing item props instead of custom controls:

- `ToggleField.description` for smaller helper text under each toggle label.
- `bottomSeparator="none"` on Decky item controls that should not render row divider
  lines.

## Core Data Structures

No persisted data structures change. The existing `Settings.notifications` object and
automatic sync setting remain unchanged.

## Public Interfaces

No backend RPC, settings schema, or package interface changes are required. The visible
QAM copy changes only by adding descriptions under the five current toggles:

- Automatic Sync
- All Notifications
- Manual Operations
- Refresh Status
- Failures and Errors

## Dependency Requirements

No dependency changes are required. The current `@decky/ui` item props already expose
`description` and `bottomSeparator`.

## Testing Strategy

- Add static frontend tests that require the exact toggle descriptions.
- Add static frontend tests that require separator removal on toggles, selected game,
  status, last operation, log buttons, and versions.
- Run the focused frontend static tests before and after implementation, then run the
  repository validation stack.
