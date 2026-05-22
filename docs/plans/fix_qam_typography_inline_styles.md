# Plan - Fix QAM Typography Inline Styles

## Problem Definition
The styling rules defined in `src/index.css` for the QAM's "Status" message, "Last Operation" results/time, and the "Versions" list are not being applied. This is because the CSS is injected into the background module-loading document context during initialization rather than the active document of the Gamepad UI window context where the QAM actually renders.

To resolve this issue and align with the standard practices of the Decky plugin ecosystem, we will migrate the font-size and color rules from `src/index.css` to inline React `style` props in `src/index.tsx`.

## Architecture Overview
- We will update the React components in [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx):
  - Add inline style props to set `fontSize: "10px"` and `color: "#cbd5e1"` (or other specific styling) directly on the versions list divs, status value container/spans, last operation row, and last operation time.
  - Keep layout-only rules (like flex alignments, margins, and overflow ellipsis) in `src/index.css`.
- We will clean up the overrides in [src/index.css](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.css):
  - Remove target font-size and color properties from `.sdh-ludusavi-versions-list`, `.sdh-ludusavi-status-value`, and `.sdh-ludusavi-last-operation-*`.
- We will update the frontend unit tests in [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py) to assert the presence of inline styles rather than external CSS font-size/color rules.

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. **Red**: Update [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py) assertions to look for `style={{ fontSize: "10px", ... }}` on the respective components and ensure the test suite fails under `pytest`.
2. **Green**: Update `src/index.tsx` and `src/index.css` with the inline styles and clean up the redundant CSS definitions.
3. **Refactor & Validate**: Run `./run.sh uv run pytest` and verify that the tests pass. Run `pnpm run build` and `pnpm run typecheck` to ensure the build bundle is correctly compiled and free of TypeScript compilation errors.
