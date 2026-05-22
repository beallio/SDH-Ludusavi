# Plan - Fix Frontend Font Sizes

## Problem Definition
The user reports that the recent update increased the font sizes of:
1. The version section (which displays the version info).
2. The field labels "Status:" and "Last Operation:".

These sizes need to be fixed to be more compact and consistent with the intended QAM layout design:
- "Status:" and "Last Operation:" labels (via `CompactFieldLabel` helper) should be reduced back to `11px` (from `13px`).
- The versions section content (via `.sdh-ludusavi-versions-list` in `src/index.css`) should be reduced to `12px` (from `14px`).

## Architecture Overview
- We will modify `CompactFieldLabel` in [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx) to return a span with `fontSize: "11px"` instead of `"13px"`.
- We will update the `.sdh-ludusavi-versions-list` class in [src/index.css](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.css) to set `font-size: 12px;` instead of `14px;`.
- We will update the corresponding assertions in the test suite.

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. **Red**: Update the test `test_frontend_qam_status_and_last_operation_use_compact_typography` in [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py) to assert `fontSize: "11px"` instead of `"13px"`.
2. Add a new check in [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py) to assert that `.sdh-ludusavi-versions-list` defines `font-size: 12px;` (instead of `14px;`).
3. Run `./run.sh uv run pytest` and verify that the tests fail (Red phase).
4. **Green**: Implement the font size changes in `src/index.tsx` and `src/index.css`.
5. Run `./run.sh uv run pytest` to ensure all tests pass (Green phase).
6. Verify styling using `pnpm run build` and typecheck via `pnpm run typecheck`.
