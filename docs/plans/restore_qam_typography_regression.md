# Plan - Restore QAM Typography Regression

## Problem Definition
A regression was introduced in the typography rebase/conflict-resolution:
1. The labels "Status:" and "Last Operation:" were made smaller (11px) when they should remain at their prior baseline size of 12px (established in prior styling to keep them compact but legible).
2. The status message and last operation message/value text, along with the versions section content, were increased or failed to scale down because CSS rules from a prior fix were lost or overridden during rebasing.

We must fix this regression:
- Set field labels ("Status:" and "Last Operation:") to 12px (via `CompactFieldLabel`).
- Reduce the status messages, last operation values, and the versions list box content to 11px so they are smaller than the labels.
- Enforce the 11px size using `!important` and child `div`/`span` selectors in CSS to override Decky UI defaults.

## Architecture Overview
- We will modify `CompactFieldLabel` in [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx) to set `fontSize: "12px"` instead of `"11px"`.
- We will update the CSS classes in [src/index.css](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.css) to explicitly target child elements with `!important` to enforce `11px` font size on:
  - `.sdh-ludusavi-versions-list` and `.sdh-ludusavi-versions-list div`
  - `.sdh-ludusavi-last-operation-row` and its child `div` and `span` elements
  - `.sdh-ludusavi-status-value` and its child `span` elements
- We will update the frontend static test suite assertions to match these requirements.

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. **Red**: Update [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py):
   - Modify the assertion `assert 'fontSize: "11px"' in source` to `assert 'fontSize: "12px"' in source`.
   - Update assertions checking the CSS classes to check for the child selectors and `11px !important` declarations.
   - Run the tests using `./run.sh uv run pytest` and verify they fail.
2. **Green**:
   - Apply the fixes in `src/index.tsx` and `src/index.css`.
   - Run `./run.sh uv run pytest` to ensure they pass.
3. **Validation**:
   - Run `pnpm run build` and `pnpm run typecheck` to verify the frontend bundles correctly and typechecking passes.
