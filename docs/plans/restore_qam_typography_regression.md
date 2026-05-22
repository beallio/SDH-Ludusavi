# Plan - Restore QAM Typography Regression

## Problem Definition
A regression was introduced in the typography rebase/conflict-resolution:
1. The labels "Status:" and "Last Operation:" were made smaller (11px, then 12px) when they should remain at their prior baseline size of 13px (established in prior styling to keep them compact but legible).
2. The status message and last operation message/value text, along with the versions section content, were increased or failed to scale down because CSS rules from a prior fix were lost or overridden during rebasing.
3. In a previous attempt, grouping container selectors with child selectors (e.g. `.sdh-ludusavi-last-operation-row, .sdh-ludusavi-last-operation-row div`) with layout properties (like `display: flex`) inadvertently applied those layout rules to the child elements, breaking the layout completely.

We must fix this regression:
- Set field labels ("Status:" and "Last Operation:") to 13px (via `CompactFieldLabel`).
- Reduce the status messages, last operation values, and the versions list box content to 12px so they are smaller than the labels.
- Set the last operation timestamp to 10px.
- Enforce the font sizes using `!important` in CSS to override Decky UI defaults.
- Fix CSS selector scoping so layout properties are only applied to the container, while typography/color rules are applied to the container and relevant descendants.

## Architecture Overview
- We will modify `CompactFieldLabel` in [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx) to set `fontSize: "13px"` instead of `"12px"`.
- We will update the CSS classes in [src/index.css](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.css) to:
  - Separate container layout styles from typography styles.
  - Enforce `12px !important` on `.sdh-ludusavi-versions-list` and nested `div`s.
  - Enforce `12px !important` on `.sdh-ludusavi-last-operation-row` and `.sdh-ludusavi-last-operation-result`.
  - Enforce `10px !important` on `.sdh-ludusavi-last-operation-time`.
  - Enforce `12px !important` on `.sdh-ludusavi-status-value` and its child `span` elements.
- We will update the frontend static test suite assertions to match these requirements.

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. **Red**: Update [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py):
   - Modify the assertion `assert 'fontSize: "12px"' in source` to `assert 'fontSize: "13px"' in source`.
   - Update assertions checking the CSS classes to check for the correct layout separation and `12px !important` / `10px !important` declarations.
   - Run the tests using `./run.sh uv run pytest` and verify they fail.
2. **Green**:
   - Apply the fixes in `src/index.tsx` and `src/index.css`.
   - Run `./run.sh uv run pytest` to ensure they pass.
3. **Validation**:
   - Run `pnpm run build` and `pnpm run typecheck` to verify the frontend bundles correctly and typechecking passes.

