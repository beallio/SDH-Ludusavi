# Plan: Disabled Notice Save-Off Icon

## Problem Definition

The per-game disabled status strip (`game_sync_disabled`) currently uses an
ad-hoc circle-with-diagonal-slash icon invented during the per-game sync toggle
implementation. It should use the Lucide `save-off` glyph (`lu/LuSaveOff` in
`react-icons`), which reads as "saving is off" rather than a generic prohibition
sign.

## Architecture Overview

The autosync status strip is rendered as standalone HTML injected into a Steam
browser view (`renderAutoSyncStatusHtml`), not as React. Icons are therefore raw
SVG strings returned by `iconSvgForAutoSyncStatus`, and `react-icons` components
cannot be used there. The glyph geometry is transcribed from the authoritative
`react-icons` definition instead of being hand-drawn.

Note that this repo pins `react-icons` 5.3.0, which predates `LuSaveOff`
(it exposes only `LuSave` and `LuSaveAll`). The geometry is taken verbatim from
`react-icons` 5.6.0. No dependency bump is required, because the consumer is a
raw SVG string rather than a React component.

## Core Data Structures

None. One branch of `iconSvgForAutoSyncStatus` changes its returned string.

## Public Interfaces

Unchanged. `iconSvgForAutoSyncStatus(status: AutoSyncStatusKind): string` keeps
its signature; only the `game_sync_disabled` return value differs.

## Dependency Requirements

None. No package added, removed, or upgraded.

## Testing Strategy

`src/surfaces/autoSyncStatusSurface.test.ts` currently asserts the old geometry
(`<circle cx="10" cy="10"` and `stroke="#0b151f"`). Those assertions are replaced
with ones matching the Lucide glyph — the 24x24 viewBox, the `m2 2 20 20` slash
stroke, and `stroke="currentColor"` so the amber `.icon` colour still applies.

This is a test-expectation change required by the requested behavior change, not
a test edited to make an unrelated failure pass. Red is confirmed before the
implementation edit.

The existing assertion that the rendered HTML contains the amber `#f59e0b` is
retained: the new glyph is stroke-based, so `currentColor` must still resolve to
the amber group.
