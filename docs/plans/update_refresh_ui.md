# Plan - Update Refresh UI Behavior

Improve user feedback during manual game refreshes by disabling inputs and showing a progress status.

## Problem Definition
Users currently don't have clear visual feedback that a refresh is in progress other than the button spinner. The game dropdown should be disabled to prevent inconsistent state, and the status line should explicitly mention the refresh.

## Architecture Overview
The UI uses `busyLabel` and `isBusy` to track active operations. I will extend the status rendering logic to handle the `Refreshing games` state.

## Proposed Solution
1. Update `DropdownItem` in `src/index.tsx` to include `disabled={isBusy}`.
2. Update the status display div to show "Game refresh in progress..." when `busyLabel === "Refreshing games"`.

## Key Files & Context
- `src/index.tsx`

## Phased Implementation Plan
- **Phase 1: UI Updates**
    - T1: Add `disabled={isBusy}` to the "Select Game" `DropdownItem`.
    - T2: Update the Status line conditional rendering to handle `busyLabel === "Refreshing games"`.
- **Phase 2: Verification**
    - V1: Run `npm run build` to ensure frontend integrity.
    - V2: Run `run.sh uv run pytest` for regression testing.

## Git Strategy
- Branch: `feat/refresh-ui-feedback`
- Commits:
    - `feat(ui): disable game dropdown during operations`
    - `feat(ui): show progress status during game refresh`

## Verification & Testing
- Run `npm run build` to verify compilation.
- Manual verification on device: Click "Refresh Games", observe dropdown is disabled and status text changes.
