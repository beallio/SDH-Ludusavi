# Restore Ludusavi Shortcut Logo

## Problem Definition

The managed Ludusavi Steam shortcut should again include the bundled logo overlay.
The previous artwork update removed `logo.png` and the logo-positioning path, but the
shortcut now needs the logo restored with explicit upper-left positioning.

## Architecture Overview

- Restore `assets/steamgrid/ludusavi/logo.png` from the existing repository history.
- Import the restored PNG through the frontend artwork manifest so Rollup emits it into
  `dist/assets/`.
- Apply the logo as Steam artwork asset type `2` after the shortcut overview exists.
- Persist the requested logo position for plugin-managed shortcuts only; user-created
  `Ludusavi` shortcuts remain untouched.
- Keep runtime artwork fully local with no SteamGridDB network lookup.

## Core Data Structures

- `LUDUSAVI_ARTWORK`: bundled artwork map containing `grid_p`, `grid_l`, `hero`, and
  `logo`.
- `LOCAL_ARTWORK_ASSET_TYPES`: Steam artwork type mapping with `logo=2`.
- `LogoPositionForApp`: Steam custom-logo positioning payload containing
  `nVersion=1` and the requested `logoPosition`.

## Public Interfaces

- No backend RPC or settings changes.
- Extend frontend Steam ambient types for logo positioning support.
- `applyLudusaviArtworkToShortcut` continues as the internal frontend entry point and
  now includes the restored logo.

## Dependency Requirements

- No new Python or npm dependencies.
- Do not modify vendored or upstream packages.
- Use only committed local PNG assets at runtime.

## Testing Strategy

- Update static artwork tests to require `logo.png`, verify it has alpha, and assert
  the exact upper-left logo positioning payload.
- Update package tests to require the built logo asset in the Decky plugin zip.
- Validate with focused tests, frontend typecheck/build/verify, Python lint/type/test
  checks, and package creation.
