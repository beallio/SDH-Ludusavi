# Plan - Decrease Last Operation Font Size and Space Natively

## Problem Definition
The user wants to:
1. Decrease the font size of the "Last Operation" field (both the label and value).
2. Decrease the space between the "Status" and "Last Operation" fields in the QAM panel.
Our previous attempt used a wrapper `div` with negative margin, which made it look worse (likely due to focus outline/highlight rendering issues in Decky Loader).

## Architecture Overview
To achieve a cleaner, native layout adjustment:
1. Set `padding="compact"` on both `Status:` and `Last Operation:` Fields. This natively decreases their vertical paddings and reduces spacing without overlapping element bounds.
2. Add a CSS class `sdh-ludusavi-last-operation-field` directly to the `Field` component itself (no wrapper `div` needed).
3. Target the label of the "Last Operation" field in `qamPanelStyles` via `.sdh-ludusavi-last-operation-field [class*="Label"]` to set its `font-size` to `12px`.
4. Apply a mild, safe negative margin (e.g., `margin-top: -4px`) to `.sdh-ludusavi-last-operation-field` to tighten the space further without causing focus boundary glitching.
5. Decrease the value font size in the children of "Last Operation" to `12px` and the timestamp font size to `10px`.

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. Modify `tests/test_frontend_static.py`:
   - Change `'fontSize: "14px"'` to `'fontSize: "12px"'` in `test_frontend_qam_last_operation_uses_single_line_ellipsis`.
2. Run `./run.sh uv run pytest` to ensure all 232 tests pass.
3. Run `pnpm run typecheck` to verify TypeScript compile checks.
