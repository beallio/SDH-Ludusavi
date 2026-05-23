# Plan: Fix Focus Highlight Width via Native ToggleField Highlight

Remove the `<PanelSectionRow>` wrappers from all `ToggleField` elements and configure them with native `highlightOnFocus` props to restore full-width focus highlights in the Quick Access Menu (QAM).

## Problem Definition
- In the previous approach, all `ToggleField` elements were wrapped in `<PanelSectionRow>` containers. This broke the native focus highlighting mechanism of `ToggleField`, making it fail to render correctly or function at all.
- In `@decky/ui`, `ToggleField` is a self-contained row component designed to be a direct child of a `<PanelSection>`. Placing it inside `<PanelSectionRow>` causes focus/highlight rendering conflicts.

## Proposed Changes

### [Frontend Components]

#### [MODIFY] [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
- Remove the `<PanelSectionRow>` wrapper elements around the 5 `ToggleField` instances.
- Ensure all 5 `ToggleField` components are direct children of their respective `<PanelSection>` elements and have `highlightOnFocus` set.

### [Tests]

#### [MODIFY] [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py)
- Update static assertions to match the unwrapped layout structure.
- Add a test checking that no `ToggleField` component is wrapped inside a `PanelSectionRow`.

## Verification Plan

### Automated Tests
- Build the frontend and run pytest:
  ```bash
  pnpm run build
  ./run.sh uv run pytest
  ```
