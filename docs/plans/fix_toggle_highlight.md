# Plan: Fix Focus Highlight Width via PanelSectionRow Wrapper

Wrap all `ToggleField` elements in standard `<PanelSectionRow>` components to restore correct focus navigation and full-width highlighting in the QAM panel.

## Problem Definition
- Removing the custom `FullWidthToggle` wrapper and placing `ToggleField` directly under `<PanelSection>` broke focus navigation and highlight rendering entirely.
- In the Decky Loader UI framework (`@decky/ui`), all interactive controls inside a `<PanelSection>` must be wrapped in a `<PanelSectionRow>` to be registered correctly in the QAM's vertical navigation container and to receive native focus highlight styling.

## Architecture Overview
- We will modify `src/index.tsx` to wrap each of the 5 `ToggleField` elements in a `<PanelSectionRow>`.
- We will update the test suite to ensure that these `ToggleField` elements are correctly identified as wrapped inside `PanelSectionRow` components.

## Proposed Changes

### [Frontend Components]

#### [MODIFY] [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
- Wrap the "Automatic Sync" `ToggleField` in `<PanelSectionRow>`.
- Wrap the "All Notifications", "Manual Operations", "Refresh Status", and "Failures and Errors" `ToggleField` components in `<PanelSectionRow>` elements.

### [Tests]

#### [MODIFY] [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py)
- Update static test assertions in `tests/test_frontend_static.py` to expect the `<PanelSectionRow>` wrappers.

## Testing Strategy
1. Build the frontend via `pnpm run build`.
2. Run pytest suite `./run.sh uv run pytest` and verify all tests pass.
