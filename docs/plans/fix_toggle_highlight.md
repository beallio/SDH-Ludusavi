# Plan: Fix Focus Highlight Width via PanelSectionRow and ToggleField Focus Delegation

Wrap all `ToggleField` elements in `<PanelSectionRow>` containers and remove the `highlightOnFocus` prop from the `ToggleField` components. This delegates focus highlighting to the outer row container, matching the standard pattern from other Decky Loader plugins.

## Problem Definition
- Our previous implementation placed `ToggleField` elements directly under `<PanelSection>` with the `highlightOnFocus` prop.
- To match standard Decky Loader plugin patterns and delegate focus highlighting to `<PanelSectionRow>`, we will wrap all 5 `ToggleField` components in `<PanelSectionRow>` and remove the `highlightOnFocus` prop from the toggles.

## Proposed Changes

### [Frontend Components]

#### [MODIFY] [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
- Wrap each of the 5 `ToggleField` elements in a `<PanelSectionRow>`.
- Remove the `highlightOnFocus` prop from all 5 `ToggleField` components.

### [Tests]

#### [MODIFY] [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py)
- Replace `test_frontend_toggles_not_wrapped_in_panel_section_row` with a new test `test_frontend_toggles_wrapped_in_panel_section_row_without_highlight_on_focus` that verifies the wrapped, non-highlighted layout.
- Update assertions in `test_frontend_qam_rows_use_native_full_row_focus` to reflect the changes.

## Verification Plan

### Automated Tests
- Build the frontend and run pytest:
  ```bash
  pnpm run build
  ./run.sh uv run pytest
  ```
