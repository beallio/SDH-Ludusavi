# Plan - Increase QAM Typography Font Size

## Problem Definition
The user finds the current font size of `11px` for the QAM Status message, Last Operation details, and the Versions list text to be too small. We need to increase it to a more legible size, such as `12px`, while maintaining a consistent visual hierarchy with the `13px` labels.

## Architecture Overview
- We will update [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx):
  - Increase the inline `fontSize` style values from `"11px"` to `"12px"` for:
    - The versions list wrapper `div` (`sdh-ludusavi-versions-list`).
    - The status value container `div` (`sdh-ludusavi-status-value`).
    - The busy status loader `span` elements (`sdh-ludusavi-status-busy`).
    - The last operation row `div` (`sdh-ludusavi-last-operation-row`).
    - The last operation result `div` (`sdh-ludusavi-last-operation-result`).
    - The last operation time `div` (`sdh-ludusavi-last-operation-time`).
- We will update the test suite assertions in [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py) to assert `"12px"` font-size in these inline styles.

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. **Red**: Update `tests/test_frontend_static.py` to assert `fontSize: "12px"` inline styling. Run `./run.sh uv run pytest` and verify the test failures.
2. **Green**: Update `src/index.tsx` inline style declarations to `"12px"`.
3. **Refactor & Validate**: Run `./run.sh uv run pytest` to ensure all tests pass. Build the bundle with `pnpm run build` and run typechecks.
