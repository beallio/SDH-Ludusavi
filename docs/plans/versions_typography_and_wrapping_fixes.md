# Plan: Versions Typography and Last Operation Wrapping Fixes

Adjust the Versions list layout and font size, and fix the premature wrapping behavior on the "Last Operation" status message.

## Problem Definition
1. **Versions Rows font size & indent**:
   - The versions text font size needs to be increased by 1px (from 15px to 16px).
   - Each record needs to be indented slightly further to the right (paddingLeft from 12px to 24px).
2. **Last Operation wrap prematurity**:
   - The status/last operation message is wrapping too early despite available space.
   - The timestamp font size is 12px (same as the message itself, but with opacity 0.65).
   - The premature wrapping occurs because the value wrapper `div` has `flexGrow: 1` but lacks `minWidth: 0` in a nested flex layout, preventing correct layout boundary calculations.

## Architecture Overview
All adjustments will be made in the frontend codebase:
- `src/index.tsx` is the primary React component file.
- `tests/test_frontend_static.py` validates the inline styling assertions on elements inside the HTML source of the frontend bundle.

## Proposed Changes

### [Frontend Components]

#### [MODIFY] [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
- Update the Versions text container style to `fontSize: "16px"` and `paddingLeft: "24px"`.
- Add `minWidth: 0` to the Last Operation value container `div` to prevent premature flex wrapping.

#### [MODIFY] [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py)
- Update the static test assertions to match `fontSize: "16px"` and `paddingLeft: "24px"` for the Versions panel.
- Ensure that the Last Operation flex-grow element assertions pass or are updated to include `minWidth: 0`.

## Testing Strategy
1. Run quality control lint and format checks:
   ```bash
   ./run.sh uv run ruff check . --fix
   ./run.sh uv run ruff format .
   ./run.sh uv run ty check py_modules/sdh_ludusavi/
   ```
2. Build frontend and run test suite:
   ```bash
   pnpm run build
   ./run.sh uv run pytest
   ```
