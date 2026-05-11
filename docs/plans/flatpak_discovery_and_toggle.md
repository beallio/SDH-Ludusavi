# Flatpak Discovery and Toggle UI

## Problem Definition

Runtime testing shows the backend still reports that the Ludusavi Flatpak cannot be
found, and the Automatic Sync control is rendered as a raw checkbox instead of a Decky
toggle switch. Decky's backend environment may not expose `/usr/bin` on `PATH`, so
checking only `shutil.which("flatpak")` is too fragile.

## Architecture Overview

Keep the `PyludusaviAdapter` and vendored `pyludusavi` integration, but make Flatpak
discovery accept well-known executable paths such as `/usr/bin/flatpak` when `PATH`
lookup fails. The frontend should use Decky's `ToggleField` component so the control
matches Steam Deck UI conventions.

## Core Data Structures

- Ludusavi command prefix: unchanged list of command arguments, now allowed to begin
  with an absolute Flatpak executable.
- Settings payload: unchanged `{"auto_sync_enabled": bool}`.

## Public Interfaces

No backend callable names or payloads change. Automatic Sync remains controlled by
`set_auto_sync_enabled(enabled)`.

## Dependency Requirements

No new dependencies. The Flatpak fallback uses standard-library path constants and the
existing verification command.

## Testing Strategy

Add tests that simulate `flatpak` missing from `PATH` while `/usr/bin/flatpak` verifies,
and update frontend static tests to require `ToggleField` and reject the raw checkbox
control.
