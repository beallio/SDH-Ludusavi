# Plan - Decrease Status and Last Operation Font Size

## Problem Definition
The user wants to decrease the font size of both "Status:" and "Last Operation:" fields in the QAM panel. We also researched how other Decky Loader plugins change formatting (using custom CSS targeting native CSS class substrings like `[class*="Label"]` or injecting styles to the container).

Currently:
- "Status:" label has default font size, and its value has `14px` font size. Its padding is `standard`.
- "Last Operation:" label has `12px` font size (via `.sdh-ludusavi-last-operation-field [class*="Label"]` style), and its value has `12px` font size. Its padding is `compact`.

To decrease the font size for both and make them look consistent and compact:
1. Set the label font size of both fields to `11px`.
2. Set the value font size of both fields to `12px`.
3. Keep the current native padding split: `Status:` remains `standard`, while `Last Operation:` remains `compact`.

## Architecture Overview
1. Add `className="sdh-ludusavi-status-field"` to the `Status:` `Field` component in `src/index.tsx`.
2. Keep `padding="standard"` on the `Status:` `Field` component to preserve its spacing from the game dropdown.
3. Decrease the value font size of the status text from `14px` to `12px` in the child `div` of the `Status:` Field.
4. Update `qamPanelStyles` to use one scoped label rule for both fields:
   ```css
   .sdh-ludusavi-status-field [class*="Label"],
   .sdh-ludusavi-last-operation-field [class*="Label"] {
     font-size: 11px;
   }
   ```
5. Keep the existing `Last Operation:` value at `12px`, timestamp at `10px`, `padding="compact"`, and `margin-top: -6px`.

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. Update `tests/test_frontend_static.py` to:
   - Verify `className="sdh-ludusavi-status-field"` is present.
   - Verify `fontSize: "12px"` is used for the status value container.
   - Verify the shared scoped label selector uses `font-size: 11px`.
   - Verify `Status:` remains `padding="standard"` and `Last Operation:` remains `padding="compact"`.
2. Run tests via `./run.sh uv run pytest` to ensure all tests pass.
3. Run `./run.sh uv run ty check py_modules/sdh_ludusavi/`, `./run.sh uv run ruff check . --fix`, `./run.sh uv run ruff format .`, `./run.sh pnpm run typecheck`, and `./run.sh pnpm run verify`.
