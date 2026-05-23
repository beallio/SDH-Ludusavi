# Plan: Versions Typography and Last Operation Wrapping Fixes

Adjust the Versions list layout and font size, and fix the premature wrapping behavior on the "Last Operation" status message. Also refine the timestamp placement, formatting, and layout widths.

## Problem Definition
1. **Versions Rows font size & indent**:
   - The versions text font size needs to be increased by 1px (from 15px to 16px).
   - The indentation (paddingLeft) of the version box needs to be set to `10px`.
2. **Last Operation wrap prematurity**:
   - The status/last operation message is wrapping too early despite available space.
   - The premature wrapping occurs because the value wrapper `div` has `flexGrow: 1` but lacks `minWidth: 0` in a nested flex layout, preventing correct layout boundary calculations.
3. **Timestamp Refinement**:
   - Place the timestamp under the Last Operation message (displaying in a column).
   - Change the timestamp representation from 24-hour to 12-hour format.
4. **Width Preference**:
   - Retain the user's change of the label width from `120px` to `110px`.

## Architecture Overview
All adjustments will be made in the frontend codebase:
- `src/index.tsx` is the primary React component file.
- `tests/test_frontend_static.py` validates the inline styling assertions on elements inside the HTML source of the frontend bundle.

## Proposed Changes

### [Frontend Components]

#### [MODIFY] [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx)
- Keep label widths at `110px`.
- Set the Versions wrapper style to `fontSize: "16px"` and `paddingLeft: "10px"`.
- Wrap the Last Operation status text and timestamp in a flex column container (`display: "flex", flexDirection: "column"`).
- Implement a `formatTime12h` helper function to convert the 24-hour ISO time string extraction into 12-hour AM/PM format.

#### [MODIFY] [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py)
- Update static test assertions to expect label width `110px`.
- Update static test assertions to expect `fontSize: "16px"` and `paddingLeft: "10px"` on the Versions container.
- Ensure tests verify the layout wrapper changes for Last Operation.

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
