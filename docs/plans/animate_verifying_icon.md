# Plan - Animate Verifying Icon & Align Theme Colors

Animate the icon on the "Verifying Game Save" status bar and update its default color to the standard theme blue (`#1a9fff`) to match the rest of the application.

## Problem Definition
1. The checking/verifying icon in the BrowserView-based status strip (`VERIFYING GAME SAVE`) is currently static, whereas standard Decky Loader / Steam UI loaders rotate.
2. The color of the status bar icons (success, checking, etc.) currently defaults to `#66c0f4` (Steam Blue) instead of the brand/theme blue (`#1a9fff`) used consistently for other spinners and UI highlights in the QAM panel.

## Architecture Overview
The "Verifying Game Save" status bar is rendered as a raw HTML document inside a Steam client `BrowserView`. The layout, styles, and inline SVG assets are generated via `renderAutoSyncStatusHtml` and `iconSvgForAutoSyncStatus` in `src/index.tsx`. 
We will introduce CSS `@keyframes` and a `.spin` animation rule to rotate the SVG icon during checking, and update the default theme color for icons from `#66c0f4` to `#1a9fff`.

## Core Data Structures
No change to core TS/Python data structures.

## Public Interfaces
No change to public APIs or RPC methods.

## Dependency Requirements
None. No external icon packages or utility libraries will be introduced.

## Proposed Changes

### [Component Name: Frontend Overlay UI]

#### [MODIFY] [index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
- Add `@keyframes spin` rule and `.icon-spin svg` styles to the embedded stylesheet.
- Conditionally apply the `icon-spin` class to the `.icon` element when the status is `checking`.
- Update the default/success color of the icon container in the style template from `#66c0f4` to `#1a9fff`.

#### [MODIFY] [test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py)
- Update static HTML string matching assertion from checking `"#66c0f4"` to checking `"#1a9fff"`.

## Testing Strategy
- Run unit tests to verify that the static HTML structure and assertions pass:
  `./run.sh uv run pytest`
- Check typechecker status:
  `pnpm run typecheck`
- Verify formatting/linting using Ruff:
  `./run.sh uv run ruff check .` and `./run.sh uv run ruff format .`
