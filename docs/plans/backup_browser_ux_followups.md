# Backup Browser UX Follow-ups

## Problem Definition

Three UX issues reported after the backup browser feature shipped (2026-06-12):

1. The Backup Browser modal opens scrolled to the bottom. Gamepad focus lands on
   the footer Close button when the modal mounts, dragging the scroll position
   down. The modal should open showing the header and the newest snapshot.
2. The QAM "Force Restore" button is redundant now that Browse Backups offers
   per-snapshot restore with a confirmation step. It should be removed.
3. The snapshot card background (`rgba(255, 255, 255, 0.05)` over `#212224`,
   ~`#2c2e2f`) should match the Steam DialogButton fill used by the Restore
   button (`#43464c`, sampled from a Deck screenshot).

## Architecture Overview

All changes are frontend-only markup/props edits:

- `src/components/modals/BackupBrowserModal.tsx`: scroll/focus behavior (issue 1)
  and card background color (issue 3).
- `src/components/qam/GameSettingsSection.tsx`: drop the Force Restore
  `SpinnerButton` row and the `onForceRestore` prop (issue 2).
- `src/components/qam/LudusaviContent.tsx`: stop passing `onForceRestore`;
  remove the now-unused `forceRestoreCall` import. The backend `force_restore`
  RPC endpoint stays (snapshot restore uses `restore_backup_version`; the
  full-restore endpoint remains valid API surface).
- `src/components/qam/NotificationSettingsSection.tsx`: update the description
  that references "Force Restore".

## Core Data Structures

None added. `GameSettingsSectionProps` loses `onForceRestore`.

## Public Interfaces

- Open-at-top: a `ref` on the scrollable list container plus a
  `scrollTo(0)`/`scrollTop = 0` effect once loading settles, and
  `Focusable` with `preferredFocus` (from `FooterLegendProps`) wrapping the
  first snapshot card so the gamepad focus engine starts at the top instead of
  the footer Close button.

## Dependency Requirements

None. `@decky/ui` already exposes `Focusable` and `preferredFocus`.

## Testing Strategy

Markup/style-only changes with no extractable logic; the repo has no React
component test rig (consistent with the original backup-browser feature).
Gates: `vitest` suite, `tsc` typecheck, plus backend suite unaffected. Manual
verification on the Deck via the next dev release.
