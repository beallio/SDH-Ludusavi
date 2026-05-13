# Plan - Update Toast Duration

Shorten the display duration of all toast notifications to 2 seconds.

## Problem Definition
Toast notifications currently stay on screen for 5 seconds (default or hardcoded), which the user finds too long. They should be shortened to 2 seconds for a snappier feel.

## Architecture Overview
The frontend uses `@decky/api`'s `toaster.toast` function. Some calls go through a `showToast` helper, while others are called directly.

## Proposed Solution
1. Update the `showToast` helper in `src/index.tsx` to set `duration: 2000`.
2. Update all direct calls to `toaster.toast` in `src/index.tsx` to include `duration: 2000`.

## Key Files & Context
- `src/index.tsx`: Main UI logic and toast triggers.

## Phased Implementation Plan
- **Phase 1: Implementation**
    - T1: Update `showToast` duration in `src/index.tsx`.
    - T2: Add `duration: 2000` to direct `toaster.toast` calls (refresh, logs error, settings error, force operations).
- **Phase 2: Verification**
    - V1: Run `npm run build` to ensure frontend integrity.
    - V2: Run `run.sh uv run pytest` for regression testing.

## Git Strategy
- Branch: `feat/shorter-toast-duration`
- Commit: `feat(ui): shorten toast notification duration to 2s`

## Verification & Testing
- Run `npm run build` to verify compilation.
- Manual verification on device: Trigger various toasts (refresh, backup, etc.) and confirm they disappear after ~2 seconds.
