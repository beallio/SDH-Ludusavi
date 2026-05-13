# Plan - Update Backup/Restore Status UI

Show "Backup in progress..." and "Restore in progress..." in the status line when those operations are active.

## Problem Definition
Users currently only see "Backup running" or "Restore running" as a spinner on the button. The main status line should reflect the active operation in the same bold blue style used for loading and refreshing.

## Architecture Overview
The UI uses `busyLabel` and `isBusy` to track active operations. I will extend the status rendering logic to handle "Backup running" and "Restore running" states.

## Proposed Solution
Update the status display div in `src/index.tsx` to include conditional branches for:
- `busyLabel === "Backup running"` -> "Backup in progress..."
- `busyLabel === "Restore running"` -> "Restore in progress..."

## Key Files & Context
- `src/index.tsx`

## Phased Implementation Plan
- **Phase 1: UI Updates**
    - T1: Update the Status line conditional rendering in `src/index.tsx`.
- **Phase 2: Verification**
    - V1: Run `npm run build` to ensure frontend integrity.
    - V2: Run `run.sh uv run pytest` for regression testing.

## Git Strategy
- Branch: `feat/backup-restore-status-ui`
- Commit: `feat(ui): show progress status during backup and restore`

## Verification & Testing
- Run `npm run build` to verify compilation.
- Manual verification on device: Click "Force Backup", observe status text changes to "Backup in progress...". Repeat for "Force Restore".
